"""在首页点「竞技」入口，进竞技场。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.execution.step import Step
from gamebot.types import ActionResult

from ...shortcuts import T_JINGJI, click_jingji_entry

if TYPE_CHECKING:
    from gamebot.context import RunContext
    from gamebot.execution.policy import StepPolicy

__all__ = ["EnterJingjiStep"]


class EnterJingjiStep(Step):
    """在首页点「竞技」入口。找不到就**如实返回**，绝不"就近点一下试试"。"""

    SETTLE = 1.2
    """点完之后等多久再让出。"""

    def __init__(
        self, *, settle: float | None = None, policy: StepPolicy | None = None
    ) -> None:
        super().__init__("进入竞技场", policy=policy, needs_fresh_frame=True)
        self.settle = self.SETTLE if settle is None else settle

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        """点入口。

        点完**等一下再让出**：点下去到竞技场渲染出来有个过渡，不等的话下一轮
        还在首页（视觉上"多点了一下"），而且会白跑一轮识别。
        """
        result = click_jingji_entry(ctx)
        if not result.ok:
            return result
        ctx.sleep(self.settle)
        ctx.invalidate_frame()
        return result

    def used_templates(self) -> tuple[str, ...]:
        return (T_JINGJI,)
