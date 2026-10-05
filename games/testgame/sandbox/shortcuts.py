"""沙盒测试游戏的快捷方法。

真实游戏里这里是"这个游戏专用的一招"（比如"一路退到主界面"）。
沙盒里不需要真操作，所以它是一个**有意留空的样板**：展示了位置和写法，
但不做任何危险动作。

为什么沙盒的步骤都只写黑板、不点鼠标：这样即使有人手滑真的把引擎跑起来
（`tick` 实现之后），最坏结果也只是日志里多几行，不会去点真实窗口。
测试用的东西**必须是安全的**。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gamebot.types import ActionResult

if TYPE_CHECKING:
    from gamebot.context import RunContext

#: 沙盒里"点了什么"都记在这儿，断言用
COUNTER_KEY = "testgame.actions"


def note(ctx: RunContext, action: str) -> ActionResult[str]:
    """记一笔"在某个页面上做了某事"，并返回成功。

    这是沙盒版的"动作"：真实脚本在这里会 ``click_image``，
    而测试关心的是**流程走到哪一步了**，不是鼠标动了没有。
    """
    ctx.blackboard.bump(COUNTER_KEY)
    ctx.blackboard.set("testgame.last_action", action)
    return ActionResult.success(action, action=action)


def times_acted(ctx: RunContext) -> int:
    """已经做过几次动作（兜底边用它来判断"卡住了"）。"""
    value = ctx.blackboard.get(COUNTER_KEY, 0)
    return value if isinstance(value, int) else 0
