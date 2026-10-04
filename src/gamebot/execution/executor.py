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
from typing import TYPE_CHECKING, Any

from ..exceptions import StepFailed
from ..types import ActionResult
from ..utils.logging import get_logger
from ..utils.timing import Stopwatch
from .journal import Journal, NullJournal
from .policy import ErrorMode
from .step import Step

if TYPE_CHECKING:
    from ..context import RunContext

log = get_logger("execution.executor")

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "attempts": self.attempts,
            "elapsed": round(self.elapsed, 4),
            "message": self.message,
            "children": [c.to_dict() for c in self.children],
        }

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
    ) -> None:
        self.ctx = ctx
        self.hooks = hooks or ExecutorHooks()
        self.journal = journal or NullJournal()
        self.dry_run = dry_run
        self.outcomes: list[StepOutcome] = []

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #
    def run(self, step: Step) -> StepOutcome:
        """执行一个步骤（含重试与失败处理），返回结果记录。"""
        raise NotImplementedError(
            "待实现流程: "
            "1) 求 precondition / skip_if -> 跳过则返回 skipped 的 StepOutcome; "
            "2) 循环 attempts，每次调用 step.run(self.ctx) 并计时; "
            "3) 超预算或不再重试时跳出; "
            "4) 按 policy.on_error 处理并触发 hooks / journal; "
            "5) 复合步骤把 children 填上。"
        )

    def run_many(self, steps: list[Step]) -> list[StepOutcome]:
        """顺序执行多个步骤。默认不因单个失败中断 —— 由每个步骤自己的
        ``on_error`` 决定要不要抛异常中断。"""
        return [self.run(step) for step in steps]

    # ------------------------------------------------------------------ #
    # 策略判断（供 run 使用）
    # ------------------------------------------------------------------ #
    def _check_skip(self, step: Step) -> str:
        """返回跳过原因；空串表示不跳过。"""
        raise NotImplementedError("待实现：在当前帧上求 skip_if / precondition")

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
