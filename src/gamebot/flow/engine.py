"""流程层的引擎 —— 主循环。

一轮 tick 的完整数据流（这就是两个对象怎么协作的全部内容）::

    ① frame = ctx.frame()                        拿帧（TTL 内复用，否则重截）
    ② match = scenario.tree.locate(frame, hint)  空间：我现在在哪
    ③ tracker.update(match)                      跟踪层：连续几帧了 / 从何时起
    ④ 终态判断（stop_pages / 页面 terminal）
    ⑤ 未知页面处理（宽容期内只等，超时后按 on_unknown）
    ⑥ 位置检查 —— 实测页面 != 当前节点期望的页面时：
         记一条警告，本轮**一个动作都不做**。
         注意是"只拦不跳"：跳转必须由图里的边显式表达（见 _position_ok）
    ⑦ 守卫通过（页面已确认 + 位置对 + 未超次数 + 冷却已过）才执行节点步骤
    ⑧ cursor.step()                              时间：条件满足就换目标
    ⑨ 检查预算（时长 / 轮数），sleep(tick_interval)

第 ⑥ 步是整套设计**最重要的安全属性**：实际页面和节点期望的页面不一致时，
一个动作都不做。识图脚本最危险的失败模式就是在错误页面上瞎点 ——
点错一个"确认"可能就是消耗道具或者进错关卡。

第 ⑥ 步之所以"只拦不跳"，是为了让控制流只有一个出处：图。
自动跳转虽然省事，但那次移动在 RunReport.decisions 里是隐形的，
排查"它怎么跑那儿去了"时只能靠猜。

第 ⑨ 步的 sleep 和所有等待一样是可中止的（``ctx.sleep`` → ``Event.wait``），
所以点了停止是毫秒级响应，不是等满这一轮。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..exceptions import Cancelled, FlowError
from ..state.page import PageId
from ..state.tracker import PageChange, PageTracker
from ..utils.logging import get_logger
from ..utils.timing import Stopwatch, humanize
from .graph import Decision, GraphCursor, NodeId
from .scenario import Scenario, UnknownPolicy

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from ..context import RunContext
    from ..execution.executor import Executor, StepOutcome

log = get_logger("flow.engine")

__all__ = ["FlowEngine", "RunReport", "StopReason"]


class StopReason(StrEnum):
    """流程为什么停。报告里必须给出这个，否则"脚本跑完没跑完"说不清。"""

    STOP_PAGE = "stop_page"
    """进入了 stop_pages 里的页面（正常结束）。"""

    TERMINAL_NODE = "terminal_node"
    """停在了终态节点。"""

    MAX_RUNTIME = "max_runtime"
    """到了总时长预算。"""

    MAX_TICKS = "max_ticks"
    """到了轮数预算。"""

    USER = "user"
    """外部请求中止（UI 停止按钮 / Ctrl+C）。"""

    UNKNOWN = "unknown"
    """长时间认不出页面，且策略是 STOP。"""

    ERROR = "error"
    """未捕获异常，流程带着错误停下。"""

    COMPLETED = "completed"
    """一次性流程自然跑完（没有可做的事且没有出边）。"""


@dataclass(slots=True)
class RunReport:
    """一次运行的完整报告。**排查问题的第一手材料**，不要精简字段。"""

    scenario: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    ticks: int = 0
    stop_reason: StopReason = StopReason.COMPLETED
    stop_message: str = ""
    initial_page: PageId = ""
    final_page: PageId = ""
    final_node: NodeId = ""
    changes: list[PageChange] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    """转移决策轨迹。**没走成的那次也在里面** —— "为什么它不动"靠这个回答。"""

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
        return self.stop_reason in (
            StopReason.STOP_PAGE,
            StopReason.TERMINAL_NODE,
            StopReason.COMPLETED,
            StopReason.USER,
        )

    def summary(self) -> str:
        return (
            f"脚本 {self.scenario!r} 结束: {self.stop_reason.value} "
            f"({self.stop_message or '无说明'}), "
            f"{self.ticks} 轮 / {self.step_count} 步 / 耗时 {humanize(self.duration)}, "
            f"{self.initial_page} -> {self.final_page} @ {self.final_node}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "stop_reason": self.stop_reason.value,
            "stop_message": self.stop_message,
            "ticks": self.ticks,
            "duration": round(self.duration, 3),
            "initial_page": self.initial_page,
            "final_page": self.final_page,
            "final_node": self.final_node,
            "changes": [c.to_dict() for c in self.changes],
            "decisions": [d.to_dict() for d in self.decisions],
            "steps": [o.to_dict() for o in self.outcomes],
            "errors": self.errors,
        }


class FlowEngine:
    """流程主循环。

    :param scenario: 蓝图（页面树 + 流程图 + 参数）。
    :param ctx: 运行时上下文（提供 session / 帧 / 黑板 / 中止）。
    :param executor: 执行器；None 时用 ``ctx.executor``。
    :param tracker: 页面跟踪器；None 时用 ``ctx.pages``。
    """

    def __init__(
        self,
        scenario: Scenario,
        ctx: RunContext,
        *,
        executor: Executor | None = None,
        tracker: PageTracker | None = None,
        start_node: NodeId = "",
    ) -> None:
        """
        :param start_node: 从哪个节点开始跑；留空 = ``graph.initial``。

            **用途是调试**：想测"战斗结束"那条分支，不用真从头把游戏玩到那一步 ——
            把游戏手动摆到对应状态、选那个节点、点开始就行。
            没有它，调一条后期分支的成本是"每次重跑整个流程"。

            注意起始节点**不影响位置守卫**：它声明的 ``page`` 和实测不符时，
            动作照样一个都不执行（这是"只拦不跳"的另一面）。
        """
        self.scenario = scenario
        self.ctx = ctx
        self.executor = executor or getattr(ctx, "executor", None)
        self.tracker: PageTracker = tracker or ctx.pages
        self.start_node = start_node or scenario.graph.initial
        if start_node and scenario.graph.node(start_node) is None:
            raise FlowError(f"起始节点不存在: {start_node!r}")
        self.cursor = GraphCursor(scenario.graph, current=self.start_node)
        self.report = RunReport(scenario=scenario.name)

        self._stop_reason: StopReason | None = None
        self._stop_message = ""
        self._unknown_since: float | None = None
        self._visited_nodes: dict[NodeId, int] = {}
        self._position_warned: set[tuple[NodeId, PageId]] = set()

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

        * 每轮先检查 ``max_runtime`` / ``max_ticks`` / 外部中止请求；
        * 一轮结束 ``ctx.sleep(tick_interval)``（**可被中止立刻唤醒**）；
        * 异常一律收进 ``report.errors`` 并停止，不往上抛 ——
          脚本跑到一半崩掉时，报告比 traceback 有用得多。
        """
        options = self.scenario.options
        self.scenario.validate()

        watch = Stopwatch()
        self.report.started_at = self.ctx.now()
        self.report.initial_page = self.tracker.current_id
        # 从配置的起始节点开始（不是 graph.initial）—— 起点是运行参数的一部分
        self.cursor.reset(to=self.start_node)
        log.info(
            "脚本 %r 启动: 起始节点 %s, 初始页面 %s",
            self.scenario.name,
            self.start_node,
            self.tracker.current_id,
        )

        try:
            while self.running:
                if options.max_runtime is not None and watch.elapsed >= options.max_runtime:
                    self.stop(StopReason.MAX_RUNTIME, f"超过 {options.max_runtime}s 预算")
                    break
                if options.max_ticks and self.report.ticks >= options.max_ticks:
                    self.stop(StopReason.MAX_TICKS, f"超过 {options.max_ticks} 轮")
                    break
                if self.ctx.stop_requested:
                    self.stop(StopReason.USER, self.ctx.stop_reason)
                    break

                self.report.ticks += 1
                self.tracker.advance_tick()
                self.tick()
                if self.running:
                    self.ctx.sleep(self._tick_interval())
        except KeyboardInterrupt:  # pragma: no cover - 人工中断
            self.stop(StopReason.USER, "用户中断 (Ctrl+C)")
        except Cancelled as cancelled:
            # 中止不是错误：报告里必须写成"外部请求停止"，
            # 否则一次正常的中止会被记成 ERROR，看报告的人会以为脚本崩了。
            self.stop(StopReason.USER, cancelled.reason)
        except Exception as exc:
            log.exception("流程异常终止")
            self.report.errors.append(f"{type(exc).__name__}: {exc}")
            self.stop(StopReason.ERROR, str(exc))

        self.report.ended_at = self.ctx.now()
        self.report.stop_reason = self._stop_reason or StopReason.COMPLETED
        self.report.stop_message = self._stop_message
        self.report.final_page = self.tracker.current_id
        self.report.final_node = self.cursor.current
        self.report.changes = self.tracker.changes
        self.report.blackboard = self.ctx.blackboard.as_dict()
        if self.executor is not None:
            self.report.outcomes = list(self.executor.outcomes)
        log.info(self.report.summary())
        return self.report

    # ------------------------------------------------------------------ #
    # 单轮
    # ------------------------------------------------------------------ #
    def tick(self) -> StepOutcome | None:
        """执行一轮。返回本轮"做了什么"，什么都没做（纯等待）时返回 None。

        待实现 —— 按模块 docstring 里的 ①~⑨ 走。依赖 ``PageTree.locate()``。
        """
        raise NotImplementedError(
            "待实现: frame -> tree.locate -> tracker.update -> 终态判断 -> "
            "未知页面宽限 -> 位置对齐(node_for_page) -> cursor.should_run -> "
            "executor.run_many(node.steps) -> cursor.step"
        )

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _tick_interval(self) -> float:
        """本轮结束后的等待时长。

        节点声明了 cooldown 时取较大者 —— 防止"某个界面原地空转刷屏"的第一道闸。
        """
        node = self.scenario.graph.node(self.cursor.current)
        base = self.scenario.options.tick_interval
        if node is not None and node.cooldown > 0:
            return max(base, node.cooldown)
        return base

    def _handle_unknown(self, now: float) -> None:
        """未知页面处理：先宽容等待，超时后按策略执行。"""
        if self._unknown_since is None:
            self._unknown_since = now
            return
        if now - self._unknown_since < self.scenario.options.unknown_grace:
            return

        policy = self.scenario.options.on_unknown
        log.warning(
            "认不出页面已持续 %.2fs，按策略 %s 处理", now - self._unknown_since, policy.value
        )
        if policy is UnknownPolicy.STOP:
            self.stop(StopReason.UNKNOWN, "长时间无法识别页面")
        elif policy is UnknownPolicy.RECOVERY and self.scenario.options.recovery_node:
            self.cursor.advance(self.scenario.options.recovery_node, now=now)
            self._unknown_since = None
        elif policy is UnknownPolicy.RELOAD_TICK:
            self._unknown_since = None
        # WAIT: 什么都不做，继续等

    def _position_ok(self, page_id: PageId) -> tuple[bool, str]:
        """实测页面和当前节点声明的 ``page`` 一致吗。

        ## 只拦不跳（这是刻意选的）

        不一致时**只返回 False**（本轮一个动作都不执行），**不**自动跳到
        "认领了该页面的节点"。跳转必须由图里的边显式表达。理由：

        * 控制流只有一个出处 —— "为什么它动了"永远能在图里找到答案；
        * 每次移动都会进 :attr:`RunReport.decisions`，可调试性最好；
        * 反过来做（自动跳）虽然"忘写边也能跑"，但那次移动在报告里
          是隐形的，排查时只能靠猜。

        代价是忘写边就原地不动。所以这里返回的说明会被引擎记成一条
        警告（:meth:`_warn_position`）—— "不动"必须是有解释的，不是静默的。

        ``Node.page is None`` 的节点不绑定页面，永远通过。
        """
        node = self.scenario.graph.node(self.cursor.current)
        if node is None:
            return False, f"当前节点不存在: {self.cursor.current!r}"
        if node.page is None:
            return True, "节点不绑定页面"
        if node.page == page_id:
            return True, "位置正确"
        return False, f"节点 {node.id!r} 期望页面 {node.page!r}，实测是 {page_id!r}"

    def _warn_position(self, node_id: NodeId, page_id: PageId, reason: str) -> None:
        """位置不符时记一条警告 —— 但**同一组合只记一次**。

        每轮都记的话，一个卡住的脚本会在一分钟内刷出几千行同样的日志，
        真正有用的信息反而被埋掉。
        """
        key = (node_id, page_id)
        if key in self._position_warned:
            return
        self._position_warned.add(key)
        log.warning(
            "本轮不执行动作：%s。如果这是意料之外的，检查图里有没有从 %r 到"
            '"认领该页面的节点"的边',
            reason,
            node_id,
        )

    def _run_node(self, state_id: NodeId) -> list[StepOutcome]:
        """执行某节点的步骤（含 on_enter 首次执行）。"""
        raise NotImplementedError("待实现：取 node -> 首次进入跑 on_enter -> 跑 steps -> 汇总")

    def _check_terminal(self, page_id: PageId, *, now: float) -> bool:
        """终态判断：stop_pages 或页面的 terminal 标记。"""
        if page_id in self.scenario.options.stop_pages:
            self.stop(StopReason.STOP_PAGE, f"进入终态页面 {page_id}")
            return True
        page = self.scenario.tree.get(page_id)
        if page is not None and page.terminal:
            self.stop(StopReason.STOP_PAGE, f"页面 {page_id} 是终态")
            return True
        return False

    def _frame(self) -> Frame:
        """拿当前帧。需要新帧就说清楚，别默默多截一张。"""
        return self.ctx.frame()

    def _note_decision(self, decision: Decision) -> None:
        """记一笔决策（含没走成的），并把它里面的条件异常暴露出来。"""
        self.report.decisions.append(decision)
        for message in decision.errors:
            log.warning("边条件异常: %s", message)
            self.report.errors.append(f"边条件异常: {message}")

    def _note_outcome(self, outcome: StepOutcome) -> None:
        """记录一个步骤结果；失败且开了截图存档就把当帧存下来。"""
        if self.executor is not None:
            self.executor.outcomes.append(outcome)
        if not outcome.ok and self.scenario.options.save_frames_on_error:
            frame = self.ctx.current_frame
            if frame is not None:
                path = self.ctx.screenshot_path(f"fail_t{self.report.ticks}_{outcome.step}")
                saved = frame.save(path)
                if saved.ok:
                    log.info("失败帧已存: %s", path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.name,
            "running": self.running,
            "cursor": self.cursor.to_dict(),
            "tracker": self.tracker.to_dict(),
            "options": self.scenario.options.to_dict(),
        }

    def __repr__(self) -> str:
        return (
            f"FlowEngine(scenario={self.scenario.name!r}, "
            f"node={self.cursor.current!r}, page={self.tracker.current_id!r})"
        )
