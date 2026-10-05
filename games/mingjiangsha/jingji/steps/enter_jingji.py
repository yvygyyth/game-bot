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

#: 点完默认等多久（秒）。**只作为声明的镜像** —— 真正生效的值来自表单参数，
#: 这里留着是为了让"不传任何参数直接构造步骤"（测试里会这么干）仍然有合理行为。
DEFAULT_SETTLE = 1.2


class EnterJingjiStep(Step):
    """在首页点「竞技」入口。找不到就**如实返回**，绝不"就近点一下试试"。"""

    def __init__(self, *, policy: StepPolicy | None = None) -> None:
        super().__init__("进入竞技场", policy=policy, needs_fresh_frame=True)

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        """点入口。

        点完**等一下再让出**：点下去到竞技场渲染出来有个过渡，不等的话下一轮
        还在首页（视觉上"多点了一下"），而且会白跑一轮识别。

        等多久来自**运行参数** ``jingji.settle``（表单可调）—— 它不在构造函数里，
        因为步骤是 ``build_scenario()`` 里的静态对象，那次调用拿不到表单值。
        """
        result = click_jingji_entry(ctx)
        if not result.ok:
            return result
        ctx.sleep(ctx.param("jingji.settle", DEFAULT_SETTLE))
        ctx.invalidate_frame()
        return result

    def used_templates(self) -> tuple[str, ...]:
        return (T_JINGJI,)
