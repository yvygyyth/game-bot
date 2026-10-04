"""流程层的引擎 —— 主循环。

一轮 tick 的完整流程（``FlowEngine.tick``）::

    ① frame = ctx.frame()                    # 拿帧（必要时截图）
    ② snapshot = detector.detect(frame)      # 状态层：现在是什么状态
    ③ change = store.update(snapshot)        # 状态层：记录 + 判断是否切换
    ④ if 终态: 停
    ⑤ transition = machine.select(...)       # 流程层：该去哪儿
       - 挑到 -> machine.apply() -> 执行目标节点的 on_enter
       - 没挑到 -> 继续做当前节点的事（很常见，不是错误）
    ⑥ executor.run_many(当前节点的 steps)    # 执行层：干活
    ⑦ 检查预算（时长 / 轮数）、tick 间隔、回到 ①

三层在这个循环里各司其职，**谁也别越界**：

* 状态层只回答"是什么"，不认识就不认识，不猜；
* 流程层只回答"去哪儿"，不直接操作键鼠；
* 执行层只回答"怎么可靠地做一次"，不决定做不做。

引擎自己只做四件事：控制节奏、检查预算、处理未知、写报告。

关于"未知状态"：这是**常态**而非异常（过场动画、加载、切场景）。设计上给了
``unknown_grace`` 宽容期 —— 在这段时间内继续等，不触发任何策略；超时后才按
``on_unknown`` 处理。没有这个宽容期，脚本会在每次场景切换时误判并乱点。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..exceptions import Cancelled
from ..state.definition import StateId
from ..state.detector import StateDetector
from ..state.snapshot import StateChange
from ..state.store import StateStore
from ..utils.logging import get_logger
from ..utils.timing import Stopwatch, humanize
from .definition import FlowDefinition, UnknownPolicy
from .machine import FlowMachine

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from ..context import RunContext
    from ..execution.executor import Executor, StepOutcome

log = get_logger("flow.engine")

__all__ = ["EngineOptions", "FlowEngine", "RunReport", "StopReason"]


class StopReason(StrEnum):
    """流程为什么停。报告里必须给出这个，否则"脚本跑完没跑完"说不清。"""

    STOP_STATE = "stop_state"
    """进入了 stop_states 里的状态（正常结束）。"""

    MAX_RUNTIME = "max_runtime"
    """到了总时长预算。"""

    MAX_TICKS = "max_ticks"
    """到了轮数预算。"""

    USER = "user"
    """外部请求停止（Ctrl+C / GUI 按钮）。"""

    UNKNOWN = "unknown"
    """未知状态超时且策略为 STOP。"""

    ERROR = "error"
    """未捕获异常，流程带着错误停下。"""

    COMPLETED = "completed"
    """一次性流程自然跑完（没有可做的事且没有转移）。"""


@dataclass(slots=True)
class EngineOptions:
    """引擎运行参数。通常从 ``FlowDefinition`` 拷一份，也可运行时覆盖。"""

    tick_interval: float = 0.2
    max_runtime: float | None = None
    max_ticks: int = 0
    stop_states: tuple[StateId, ...] = ()
    on_unknown: UnknownPolicy = UnknownPolicy.WAIT
    recovery_state: StateId = ""
    unknown_grace: float = 1.0
    dry_run: bool = False
    """空跑：只识别状态、不执行动作步骤。用来验证流程走向。"""

    save_frames_on_error: bool = False
    """失败时把当帧存盘，方便事后看"当时屏幕上到底有什么"。"""

    @classmethod
    def from_definition(cls, definition: FlowDefinition) -> EngineOptions:
        return cls(
            tick_interval=definition.tick_interval,
            max_runtime=definition.max_runtime,
            max_ticks=definition.max_ticks,
            stop_states=definition.stop_states,
            on_unknown=definition.on_unknown,
            recovery_state=definition.recovery_state,
            unknown_grace=definition.unknown_grace,
        )


@dataclass(slots=True)
class RunReport:
    """一次流程运行的完整报告。**这是排查问题的第一手材料**，不要精简掉字段。"""

    flow: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    ticks: int = 0
    stop_reason: StopReason = StopReason.COMPLETED
    stop_message: str = ""
    initial_state: StateId = ""
    final_state: StateId = ""
    changes: list[StateChange] = field(default_factory=list)
    outcomes: list[StepOutcome] = field(default_factory=list)
    blackboard: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    @property
    def step_count(self) -> int:
        return len(self.outcomes)

    @property
    def failed_steps(self) -> list[StepOutcome]:
        return [o for o in self.outcomes if not o.ok]

    @property
    def ok(self) -> bool:
        return self.stop_reason in (StopReason.STOP_STATE, StopReason.COMPLETED, StopReason.USER)

    def summary(self) -> str:
        return (
            f"流程 {self.flow!r} 结束: {self.stop_reason.value} "
            f"({self.stop_message or '无说明'}), "
            f"{self.ticks} 轮 / {self.step_count} 步 / 耗时 {humanize(self.duration)}, "
            f"{self.initial_state} -> {self.final_state}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow": self.flow,
            "stop_reason": self.stop_reason.value,
            "stop_message": self.stop_message,
            "ticks": self.ticks,
            "duration": round(self.duration, 3),
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "changes": [c.to_dict() for c in self.changes],
            "steps": [o.to_dict() for o in self.outcomes],
            "errors": self.errors,
        }


class FlowEngine:
    """流程主循环。

    :param definition: 蓝图。
    :param ctx: 运行时上下文（提供 session / 帧 / 黑板 / 停止请求）。
    :param detector: 状态识别器；None 时用 ``definition.states`` 现造一个。
    :param executor: 执行器；None 时用 ``ctx.executor``（没有就造一个）。
    :param options: 运行参数。
    """

    def __init__(
        self,
        definition: FlowDefinition,
        ctx: RunContext,
        *,
        detector: StateDetector | None = None,
        executor: Executor | None = None,
        options: EngineOptions | None = None,
    ) -> None:
        self.definition = definition
        self.ctx = ctx
        self.detector = detector or StateDetector(definition.states)
        self.executor = executor
        self.options = options or EngineOptions.from_definition(definition)
        self.machine = FlowMachine(definition)
        self.store: StateStore = ctx.states
        self.report = RunReport(flow=definition.name)
        self._stop_reason: StopReason | None = None
        self._stop_message = ""
        self._unknown_since: float | None = None
        self._node_visits: dict[StateId, int] = {}

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    @property
    def running(self) -> bool:
        return self._stop_reason is None

    def stop(self, reason: StopReason = StopReason.USER, message: str = "") -> None:
        """请求停止。可以在任意时刻调用（包括 hooks 里、信号处理里）。"""
        if self._stop_reason is None:
            self._stop_reason = reason
            self._stop_message = message
            log.info("流程停止请求: %s %s", reason.value, message)

    def run(self) -> RunReport:
        """跑完整个流程，返回报告。

        循环控制（这部分是完整的）：

        * 每轮先检查 ``max_runtime`` / ``max_ticks`` / 外部停止请求；
        * 一轮结束 sleep ``tick_interval``（不 sleep 会打满 CPU 和 adb）；
        * 异常一律收进 ``report.errors`` 并停止，不往上抛 ——
          脚本跑到一半崩掉时，报告比 traceback 有用得多。
        """
        definition = self.definition
        definition.validate()

        watch = Stopwatch()
        self.report.started_at = self.ctx.now()
        self.report.initial_state = definition.initial
        self.store.set_initial(definition.initial, now=self.ctx.now())
        log.info("流程 %r 启动: 初始状态 %s", definition.name, definition.initial)

        try:
            while self.running:
                if (
                    self.options.max_runtime is not None
                    and watch.elapsed >= self.options.max_runtime
                ):
                    self.stop(StopReason.MAX_RUNTIME, f"超过 {self.options.max_runtime}s 预算")
                    break
                if self.options.max_ticks and self.report.ticks >= self.options.max_ticks:
                    self.stop(StopReason.MAX_TICKS, f"超过 {self.options.max_ticks} 轮")
                    break
                if self.ctx.stop_requested:
                    self.stop(StopReason.USER, self.ctx.stop_reason)
                    break

                self.report.ticks += 1
                self.store.advance_tick()
                self.tick()
                if self.running:
                    self.ctx.sleep(self._tick_interval())
        except KeyboardInterrupt:  # pragma: no cover - 人工中断
            self.stop(StopReason.USER, "用户中断 (Ctrl+C)")
        except Cancelled as cancelled:
            # 中止不是错误：报告里必须写成"用户/外部请求停止"，
            # 否则一次正常的中止会被记成 ERROR，看报告的人会以为脚本崩了。
            self.stop(StopReason.USER, cancelled.reason)
        except Exception as exc:
            log.exception("流程异常终止")
            self.report.errors.append(f"{type(exc).__name__}: {exc}")
            self.stop(StopReason.ERROR, str(exc))

        self.report.ended_at = self.ctx.now()
        self.report.stop_reason = self._stop_reason or StopReason.COMPLETED
        self.report.stop_message = self._stop_message
        self.report.final_state = self.machine.current
        self.report.changes = self.machine.history
        self.report.blackboard = self.ctx.blackboard.as_dict()
        if self.executor is not None:
            self.report.outcomes = list(self.executor.outcomes)
        log.info(self.report.summary())
        return self.report

    # ------------------------------------------------------------------ #
    # 单轮
    # ------------------------------------------------------------------ #
    def tick(self) -> StepOutcome | None:
        """执行一轮。

        待实现（按模块 docstring 的 ①~⑦ 走）。返回本轮"做了什么"，
        什么都没做（纯等待）时返回 None。
        """
        raise NotImplementedError(
            "待实现: capture -> detect -> store.update -> 终态判断 -> "
            "machine.select/apply -> 执行节点步骤 -> 未知状态宽限处理"
        )

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #
    def _tick_interval(self) -> float:
        """本轮结束后的等待时长。

        节点声明了 cooldown 时取较大者 —— 这是防止"某个界面原地空转刷屏"的第一道闸。
        """
        node = self.definition.node(self.machine.current)
        if node is not None and node.cooldown > 0:
            return max(self.options.tick_interval, node.cooldown)
        return self.options.tick_interval

    def _handle_unknown(self, now: float) -> None:
        """未知状态处理：先宽容等待，超时后按策略执行。"""
        if self._unknown_since is None:
            self._unknown_since = now
            return
        if now - self._unknown_since < self.options.unknown_grace:
            return

        policy = self.options.on_unknown
        log.warning("未知状态已持续 %.2fs，按策略 %s 处理", now - self._unknown_since, policy.value)
        if policy is UnknownPolicy.STOP:
            self.stop(StopReason.UNKNOWN, "长时间无法识别状态")
        elif policy is UnknownPolicy.RECOVERY and self.options.recovery_state:
            self.machine.current = self.options.recovery_state
            self._unknown_since = None
        elif policy is UnknownPolicy.RELOAD_TICK:
            self._unknown_since = None
        # WAIT: 什么都不做，继续等

    def _run_node(self, state_id: StateId) -> list[StepOutcome]:
        """执行某状态对应节点的步骤（含 on_enter 首次执行）。"""
        raise NotImplementedError("待实现：取 node -> 首次进入跑 on_enter -> 跑 steps -> 汇总")

    def _frame(self) -> Frame:
        """拿当前帧。需要新帧就说清楚，别默默多截一张。"""
        return self.ctx.frame()

    def _check_terminal(self, state_id: StateId) -> bool:
        if state_id in self.options.stop_states or self.machine.is_terminal(state_id):
            self.stop(StopReason.STOP_STATE, f"进入终态 {state_id}")
            return True
        return False

    def _note_outcome(self, outcome: StepOutcome) -> None:
        """记录一个步骤结果；失败且开了截图存档就把当帧存下来。"""
        if self.executor is not None:
            self.executor.outcomes.append(outcome)
        if not outcome.ok and self.options.save_frames_on_error:
            frame = self.ctx.current_frame
            if frame is not None:
                path = self.ctx.screenshot_path(f"fail_t{self.report.ticks}_{outcome.step}")
                saved = frame.save(path)
                if saved.ok:
                    log.info("失败帧已存: %s", path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow": self.definition.name,
            "running": self.running,
            "machine": self.machine.to_dict(),
            "options": {
                "tick_interval": self.options.tick_interval,
                "max_runtime": self.options.max_runtime,
                "max_ticks": self.options.max_ticks,
                "dry_run": self.options.dry_run,
            },
        }
