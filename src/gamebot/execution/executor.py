"""执行层 —— Executor：把策略套在步骤上，跑完给出可观测的结果。

执行器只做四件事，多一件都别加：

1. 检查 ``skip_if`` / ``precondition``（不满足就跳过，不算失败）；
2. 在 ``timeout`` 预算内反复尝试步骤，按 ``RetryPolicy`` 决定间隔；
3. 按 ``ErrorMode`` 处理最终失败（抛异常 / 继续 / 停流程 / 放弃本轮）；
4. 把每次尝试写进 journal，并回调 hooks。

**故意不做的事**：不做状态判断、不做流程跳转、不截图（除步骤要求）、不识别游戏 ——
那些是状态层和流程层的事。执行器保持"哑"，才能被复用和测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import StepFailed
from ..types import ActionResult, ActionStatus
from ..utils.logging import get_logger
from ..utils.timing import Stopwatch
from ..vision.recorder import prune_old
from .journal import Journal, NullJournal
from .policy import ErrorMode
from .step import Step, _evaluate

if TYPE_CHECKING:
    from ..context import RunContext

log = get_logger("execution.executor")

#: 失败帧的文件名前缀。
#:
#: **这个前缀不是装饰**：留存清理靠它圈定范围（``fail_*.png``）。名字不带
#: 前缀的话，"清理旧失败帧"要么扫不到（图无限涨），要么只能不带 pattern 地
#: 删 —— 而截图目录里还躺着识图记录和用户手工截的图，误删比涨满更烦。
FAILED_FRAME_PREFIX = "fail_"

__all__ = ["Executor", "ExecutorHooks", "StepOutcome"]


@dataclass(slots=True)
class StepOutcome:
    """一个步骤跑完之后的完整记录。"""

    step: str
    result: ActionResult[Any]
    attempts: int = 1
    elapsed: float = 0.0
    skipped: bool = False
    skip_reason: str = ""
    children: list[StepOutcome] = field(default_factory=list)
    action: dict[str, Any] = field(default_factory=dict)
    """这次生效的动作描述（``{"kind": "click", "point": [960, 540]}``）。

    从 ``result.meta`` 里拾取常见的几个键填上，给 journal 用 ——
    journal 的格式约定里 ``action`` 是独立字段（方便以后当训练数据的锚点），
    所以不能只丢在 meta 里。
    """

    frame_path: str = ""
    """这次执行时的帧存盘路径（存了才有）。帧**不内联**进 journal。"""

    @property
    def ok(self) -> bool:
        """跳过也算成功 —— 它没有失败。"""
        return self.skipped or self.result.ok

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        return self.result.status.value

    @property
    def message(self) -> str:
        return self.skip_reason if self.skipped else self.result.message

    @classmethod
    def of(cls, step: Any, result: ActionResult[Any], **kwargs: Any) -> StepOutcome:
        """造一个 outcome 并把 ``result.meta`` 里的动作信息拾进 ``action``。

        journal 的契约里 ``action`` 是独立字段，所以这里做一次拾取：
        ``{"kind": ..., "point": ...}`` 是回放和以后做训练数据要用的锚点。
        **只认已知的键**，别的留在 meta 里 —— 不做"把 meta 整个搬过来"，
        那样 action 会变成一个什么都往里塞的垃圾桶。
        """
        action: dict[str, Any] = {}
        meta = result.meta or {}
        # **不搬 "action" 这个键本身**：meta 里可能已经有一个 {"point": ...}
        # 形状的子字典，把它整个塞进 action 会得到 action={"action": {...}}，
        # journal 里就变成了两层嵌套 —— 那是没人想读的格式。
        for key in ("kind", "point", "logic_point", "template", "text", "key", "keys"):
            if key in meta:
                action[key] = meta[key]
        kind = kwargs.pop("action_kind", "")
        if kind:
            action.setdefault("kind", kind)
        return cls(step, result, action=action, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step": self.step,
            "status": self.status,
            "attempts": self.attempts,
            "elapsed": round(self.elapsed, 4),
            "message": self.message,
            "children": [c.to_dict() for c in self.children],
        }
        if self.action:
            payload["action"] = self.action
        if self.frame_path:
            payload["frame"] = self.frame_path
        return payload

    def __repr__(self) -> str:
        return (
            f"StepOutcome({self.step!r}, status={self.status}, "
            f"attempts={self.attempts}, elapsed={self.elapsed:.3f}s)"
        )


@dataclass(slots=True)
class ExecutorHooks:
    """执行器回调点。默认全空，方便子类只覆写关心的那几个。

    典型用途：失败时截图存档、把关键结果推到 GUI、统计耗时直方图。
    """

    before_step: Any = None
    """``(ctx, step) -> None``"""

    after_step: Any = None
    """``(ctx, outcome) -> None``"""

    on_retry: Any = None
    """``(ctx, step, attempt, result) -> None``"""

    on_failure: Any = None
    """``(ctx, step, outcome) -> None``"""


class Executor:
    """步骤执行器。

    :param ctx: 运行时上下文（步骤要用它拿 session / 帧 / 黑板）。
    :param hooks: 回调。
    :param journal: 落盘记录器；默认不落盘。
    :param dry_run: True 时只做查询类步骤，所有动作步骤直接返回成功不执行。
        用于"看看流程会不会走通"而不真的操作游戏。
    """

    def __init__(
        self,
        ctx: RunContext,
        *,
        hooks: ExecutorHooks | None = None,
        journal: Journal | None = None,
        dry_run: bool = False,
        save_frames_on_error: bool = False,
    ) -> None:
        self.ctx = ctx
        self.hooks = hooks or ExecutorHooks()
        self.journal = journal or NullJournal()
        self.dry_run = dry_run
        # 装配期传进来（不是从 ctx 猜）：执行层不去读流程层的 Options 类型，
        # 由 bootstrap 把这个开关翻译成一个布尔值给它，依赖方向才不乱。
        self.save_frames_on_error = save_frames_on_error
        self.outcomes: list[StepOutcome] = []

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #
    def run(self, step: Step) -> StepOutcome:
        """执行一个步骤（含重试与失败处理），返回结果记录。

        五件事，顺序不能变：

        1. **跳过判断在最前** —— ``precondition`` / ``skip_if`` 不满足就跳过，
           而**跳过不算失败**（``StepOutcome.ok`` 对 skipped 返回 True）；
        2. **重试在超时预算内** —— ``RetryPolicy`` 决定还能不能试、等多久，
           ``StepPolicy.timeout`` 是这一整步（含所有重试与等待）的总预算；
        3. **等待一律走 ``ctx.sleep``** —— 它可被中止立刻唤醒。中止是
           ``Cancelled`` 异常、直接穿透：``RetryPolicy.retry_on`` 是枚举而不是
           "非成功即可重试"，所以中止永远不会被当成可重试
           （写成后者的话表现就是"点了停止但脚本继续转"）；
        4. **失败才交给 ``on_error``** —— 抛异常 / 停流程 / 继续 / 放弃本轮
           是业务决策，执行器只按声明的做；
        5. **每次都记账** —— journal + hooks，**包括跳过的那次**。

        ``dry_run`` 时动作步骤不真的下发，但仍然走完这套流程并标记 ``dry_run``
        —— 这样"空跑一遍看流程走不走得通"得到的是一条真实的决策序列。
        """
        policy = step.policy
        watch = Stopwatch()

        skip_reason = self._check_skip(step)
        if skip_reason:
            outcome = StepOutcome(
                step.name,
                ActionResult.success(None),
                attempts=0,
                skipped=True,
                skip_reason=skip_reason,
            )
            self._record(step, outcome)
            return outcome

        retry = policy.retry
        attempts = 0
        result: ActionResult[Any] = ActionResult.error("步骤没有执行")

        while True:
            attempts += 1
            started = watch.elapsed
            result = self._dry_run_result(step) or step.run(self.ctx)
            result = result.with_elapsed(watch.elapsed - started)

            if result.ok:
                break

            if policy.timeout is not None and watch.elapsed >= policy.timeout:
                result = result.with_meta(timeout_budget=policy.timeout)
                break

            if not retry.should_retry(attempts, result.status):
                break

            delay = retry.delay_for(attempts)
            if policy.timeout is not None:
                delay = min(delay, max(0.0, policy.timeout - watch.elapsed))
            if delay > 0:
                self.ctx.sleep(delay)  # 可被中止立刻唤醒
            if self.hooks.on_retry:
                self.hooks.on_retry(self.ctx, step, attempts, result)

        outcome = StepOutcome.of(step.name, result, attempts=attempts, elapsed=watch.elapsed)
        # 复合 / 条件步骤把子步骤结果挂到父 outcome 上。**在这里做而不是让
        # 引擎做**：子步骤的记账本来就归执行层，而且这样"直接调 executor.run"
        # （测试、临时脚本）也能拿到完整的步骤树。
        children_of = getattr(step, "child_outcomes", None)
        if callable(children_of) and not outcome.children:
            outcome.children = list(children_of())
        self._record(step, outcome)

        if not outcome.ok and (policy.require_success or policy.on_error is not ErrorMode.CONTINUE):
            self._handle_failure(step, outcome)
        return outcome

    def _dry_run_result(self, step: Step) -> ActionResult[Any] | None:
        """空跑时给动作类步骤造一个"假装成功"的结果；查询类步骤照常跑。

        判断标准是 :meth:`Step.performs_action`，**不是步骤类型名** ——
        自定义步骤只要声明了就会被拦下；忘声明的（业务层那些）由基类默认
        返回 True 兜住：**宁可多拦一个，也不能空跑时真去点游戏**。
        """
        if not self.dry_run or not step.performs_action:
            return None
        return ActionResult.success(
            None,
            message=f"空跑，未执行动作: {step.describe()}",
            dry_run=True,
        )

    def run_many(self, steps: list[Step]) -> list[StepOutcome]:
        """顺序执行多个步骤。默认不因单个失败中断 —— 由每个步骤自己的
        ``on_error`` 决定要不要抛异常中断。"""
        return [self.run(step) for step in steps]

    # ------------------------------------------------------------------ #
    # 策略判断（供 run 使用）
    # ------------------------------------------------------------------ #
    def _check_skip(self, step: Step) -> str:
        """返回跳过原因；空串表示不跳过。

        * ``precondition``：**不满足则跳过**（"先确认弹窗出现了，才点确认"）；
        * ``skip_if``：**满足则跳过**（"体力已经满了就不用吃体力药"）。

        求值出错**不跳过**：配置坏了应该让步骤按正常路径失败并留下痕迹，
        而不是静默跳过 —— 跳过在报告里长得像"本来就不需要做"。
        """
        cond = step.policy.precondition
        if cond is not None:
            result = _evaluate(cond, self.ctx)
            if result.status is ActionStatus.ERROR:
                log.warning(
                    "步骤 %r 的 precondition 求值出错，按不跳过处理: %s",
                    step.name,
                    result.message,
                )
            elif not result.ok:
                return f"precondition 不满足: {result.message or cond!r}"

        skip_if = step.policy.skip_if
        if skip_if is not None:
            result = _evaluate(skip_if, self.ctx)
            if result.status is ActionStatus.ERROR:
                log.warning(
                    "步骤 %r 的 skip_if 求值出错，按不跳过处理: %s", step.name, result.message
                )
            elif result.ok:
                return f"skip_if 满足: {result.message or skip_if!r}"
        return ""

    def _record(self, step: Step, outcome: StepOutcome) -> None:
        """存失败帧 -> 落 journal + 触发 hooks。

        **一个步骤只记一条**（含跳过的）：排查时"它跑没跑"和"它成没成"同样重要，
        报告里看不到某一步时，第一个要回答的问题就是它到底有没有被执行。

        **帧必须在写 journal 之前存**：``record_outcome`` 会把
        ``outcome.frame_path`` 写进那一条记录里，而 ``attach_frame`` 是往
        ``outcome`` 上回填路径的。顺序反了就变成"日志里说第 3 步失败了，
        但记录里没有图" —— 图其实躺在磁盘上，只是没人告诉你文件名。
        """
        self._save_failure_frame(outcome)
        self.journal.record_outcome(outcome, tick=getattr(self.ctx.pages, "tick", 0))
        if self.hooks.before_step:
            self.hooks.before_step(self.ctx, step)
        if self.hooks.after_step:
            self.hooks.after_step(self.ctx, outcome)
        if not outcome.ok and self.hooks.on_failure:
            self.hooks.on_failure(self.ctx, step, outcome)

    def _save_failure_frame(self, outcome: StepOutcome) -> None:
        """失败的步骤存一张当帧，并把路径写回 ``outcome``（journal 会带上它）。

        三个约束：

        * 只在**失败**时存 —— 成功的步骤存图没有诊断价值，只会堆盘；
        * **有上限**（``_frame_keep``）：失败帧和识图记录躺在同一个目录里，
          各删各的 pattern，否则跑一晚上就是几千张全尺寸 PNG；
        * 存不下来（磁盘满、没权限）**不抛异常** —— 可观测性不该把脚本弄挂。
        """
        if outcome.ok or not self.save_frames_on_error:
            return
        frame = self.ctx.current_frame
        if frame is None:
            return
        directory = self.ctx.config.paths.resolve(self.ctx.config.paths.screenshots)
        path = self.journal.attach_frame(
            outcome,
            frame,
            directory=directory,
            prefix=FAILED_FRAME_PREFIX,
            tick=int(getattr(self.ctx.pages, "tick", 0)),
        )
        if not path:
            return
        prune_old(Path(directory), f"{FAILED_FRAME_PREFIX}*.png", self._frame_keep)
        log.debug("失败帧已存: %s", path)

    @property
    def _frame_keep(self) -> int:
        """失败帧最多留几张。

        跟着识图记录的上限走（它的 5 倍，至少 20）：两者都在教同一件事
        "留最近那几次就够看了"，没必要再往配置里加一个要用户理解的旋钮。
        """
        recorder = getattr(self.ctx, "recorder", None)
        keep = getattr(recorder, "keep", 0) or 0
        return max(20, keep * 5)

    def _handle_failure(self, step: Step, outcome: StepOutcome) -> None:
        """按 ``policy.on_error`` 决定抛异常还是继续。"""
        mode = step.policy.on_error
        if mode is ErrorMode.RAISE:
            raise StepFailed(f"步骤失败: {step.describe()} — {outcome.result.message}")
        if mode is ErrorMode.STOP_FLOW:
            self.ctx.request_stop(f"步骤失败: {step.describe()}")
        # CONTINUE / ABORT_TICK 都不抛，交给调用方看 outcome

    def _elapsed(self, watch: Stopwatch) -> float:
        return watch.elapsed

    def close(self) -> None:
        self.journal.close()

    def __enter__(self) -> Executor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# 供子类实现参考的辅助函数，避免到处重复
def _summarize(outcomes: list[StepOutcome]) -> ActionResult[list[Any]]:
    """把一组结果汇总成一个 ActionResult（全部成功才成功）。"""
    failed = [o for o in outcomes if not o.ok]
    if failed:
        return ActionResult.not_found(
            f"{len(failed)}/{len(outcomes)} 个步骤失败",
            results=[o.to_dict() for o in outcomes],
        )
    return ActionResult.success([o.result.value for o in outcomes])
