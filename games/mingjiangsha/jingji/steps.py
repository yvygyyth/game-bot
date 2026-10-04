"""竞技场 —— 本功能的步骤。

步骤只做"做一次"的事；重试和失败代价交给 ``policy``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.execution.step import Step
from gamebot.types import ActionResult

from ..shortcuts import T_JINGJI, click_jingji_entry

if TYPE_CHECKING:
    from gamebot.context import RunContext
    from gamebot.execution.policy import StepPolicy

__all__ = ["EnterJingjiStep"]


class EnterJingjiStep(Step):
    """在首页点「竞技」入口。

    点完之后**等一下再让出**：点下去到竞技场渲染出来有个过渡，
    不等的话下一轮还在首页（视觉上"多点了一下"），而且会白跑一轮识别。

    ``settle`` 给 1.2 秒是过渡时间；太短会重复点，太长纯浪费。
    """

    #: 点完之后给页面切换留的时间（秒）
    SETTLE = 1.2

    def __init__(self, *, settle: float | None = None, policy: StepPolicy | None = None) -> None:
        super().__init__("进入竞技场", policy=policy, needs_fresh_frame=True)
        self.settle = self.SETTLE if settle is None else settle

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        result = click_jingji_entry(ctx)
        if not result.ok:
            # 找不到就如实返回，**绝不"就近点一下试试"**
            return result
        ctx.sleep(self.settle)
        ctx.invalidate_frame()  # 画面肯定变了，别让后面的步骤看旧帧
        return result

    def used_templates(self) -> tuple[str, ...]:
        """这个步骤用到的模板 —— 覆写它，``games check`` 才查得出缺图。"""
        return (T_JINGJI,)
