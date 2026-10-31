"""选将：搜索入参武将 → 点第一个搜索结果。

## 为什么是"固定坐标 + 搜索"而不是滚列表

武将列表很长，靠滚动找「吕布」既慢又容易点错。搜索框是确定的：
点搜索框、输入入参、点「搜索」、结果只剩一个，点它就行。

## 两个坐标是固定值

* 搜索框在「搜索」按钮左边 160px（面板布局固定）；
* 搜索结果的第一张卡在 ``(200, 1100)``（源坐标 2560x1369）。

这两处不随武将变化，所以不裁模板。真换分辨率/改布局时改这两个常量。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.types import ActionResult, Point

from ..form import WUJIANG_PARAM
from ..pages import PICK_PLACEHOLDER_ROI, SEARCH_ROI
from ..templates import T_PLACEHOLDER, T_SEARCH

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["RESULT_POINT", "SEARCH_FOCUS_OFFSET", "pick_general"]

#: 搜索框相对「搜索」按钮中心的横向偏移（像素）。
SEARCH_FOCUS_OFFSET = -160

#: 搜索结果第一张卡的中心（源坐标）。
RESULT_POINT = Point(200, 1100)


def pick_general(ctx: RunContext) -> ActionResult[Any]:
    """在选将面板里搜索入参武将并选中它。"""
    name = str(ctx.param(WUJIANG_PARAM, "吕布")).strip()
    if not name:
        return ActionResult.error("入参武将名为空")

    # ---- 1. 找「搜索」按钮，点它左边的输入框 ----
    found = ctx.frame().find_image(T_SEARCH, region=SEARCH_ROI)
    if not found.ok or found.value is None:
        return ActionResult.not_found(
            "选将面板里没找到「搜索」按钮", template=T_SEARCH
        )
    search_center = found.value
    focus = Point(search_center.x + SEARCH_FOCUS_OFFSET, search_center.y)

    clicked = actions.click_source_point(ctx.session, focus)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.3)

    # ---- 2. 清空旧内容再输入（重试时输入框可能还有上一次的字）----
    actions.hotkey(ctx.session, ["ctrl", "a"])
    typed = actions.type_text(ctx.session, name)
    if not typed.ok:
        return typed
    ctx.sleep(0.2)

    # ---- 3. 点「搜索」----
    clicked = actions.click_source_point(ctx.session, search_center)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.6)

    # ---- 4. 点搜索结果的第一张卡 ----
    picked = actions.click_source_point(ctx.session, RESULT_POINT)
    if not picked.ok:
        return picked
    ctx.invalidate_frame()
    ctx.sleep(0.8)

    # ---- 5. 验证：占位卡应该被武将卡替换 ----
    still = ctx.frame().find_image(T_PLACEHOLDER, region=PICK_PLACEHOLDER_ROI)
    if still.ok:
        return ActionResult.not_found(
            f"搜索并点了结果，但「选择武将」占位卡还在（{name} 没选中？）",
            template=T_PLACEHOLDER,
        )
    return picked.with_meta(wu_jiang=name, result_point=(RESULT_POINT.x, RESULT_POINT.y))
