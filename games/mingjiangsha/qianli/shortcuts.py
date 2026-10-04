"""千里单骑 —— 这个玩法专用的快捷方法。

和游戏级 ``mingjiangsha.shortcuts`` 的区别：那些是"名将杀里到处都用"的
（关弹窗、回主界面），这里是只有这个玩法才用得到的。

**什么时候值得抽一个快捷方法**：同一段 2~5 步的操作在流程里出现两次以上，
或者它需要一点"读图结果 + 坐标"的组合技巧（比如下面按序号选关卡）。
只出现一次的话，直接写在步骤里更好读。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gamebot.atomic import actions
from gamebot.types import ActionResult, Point

if TYPE_CHECKING:
    from gamebot.context import RunContext

#: 关卡按钮：同一张图在列表里重复排布
T_STAGE = "stage_button.png"
T_START = "start_challenge.png"


def pick_stage(ctx: RunContext, index: int = 0) -> ActionResult[Point]:
    """按**序号**选关卡。

    关卡按钮是同一张图重复排布的，``find_image`` 只会给你第一个，
    所以这里用 ``find_all_images`` 拿全部再取第 ``index`` 个。

    注意返回的点是**源坐标**，所以点击必须用 :func:`actions.click_source_point`
    而不是 ``click_point`` —— 后者收逻辑坐标，配了缩放会二次换算点偏。
    """
    found = ctx.frame().find_all_images(T_STAGE, confidence=0.9)
    if not found.ok:
        return ActionResult(found.status, None, f"没找到关卡按钮: {found.message}")
    points: list[Point] = found.value or []
    if index >= len(points):
        return ActionResult.not_found(f"只找到 {len(points)} 个关卡，取不到第 {index + 1} 个")
    return actions.click_source_point(ctx.session, points[index])


def start_challenge(ctx: RunContext) -> ActionResult[Point]:
    """点「开始挑战」。体力不够时游戏会弹提示，这里不管 —— 那是流程层的事。"""
    return actions.click_image(ctx.session, T_START, confidence=0.85)


def stage_cleared(ctx: RunContext, stage: str = "1-1") -> bool:
    """边条件：某个关卡是不是已经通关了。

    真正的实现应该是"读界面上的通关标记"::

        result = ctx.frame().is_image_visible(f"stages/{stage}_cleared.png")
        return result.ok and result.value is True

    这里就是那个实现，只是对应的模板还没截。把图放进去就能用 ——
    找不到时 ``is_image_visible`` 返回 ``success(False)`` 而不是报错，
    所以"图还没截"不会让流程崩，只是这个条件永远不成立（安全的一侧）。
    """
    result = ctx.frame().is_image_visible(f"stages/{stage}_cleared.png")
    return result.ok and result.value is True
