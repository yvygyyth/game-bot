"""推进队伍流程：创建队伍 → 添加伙伴 → 开始匹配（+ 提示框善后）。

三个函数各管一个按钮，都用 :func:`~gamebot.execution.builtins.click_image`
（它自带"找到 → 点 → 作废帧"）。

## 现在**全图找**，没给 ``region``

用户要求：默认不加 roi，误命中多了再加。理由见 `pages.py` 里那段说明 ——
一句话：模板刚裁、界面位移还没量过，这时候设紧框的风险是"框差 10px →
永远找不到"，而症状和"模板裁错了"一样难查。

**想提速或防误命中就加 ``region=``**。三个按钮分两处位置，别共用一个框：

| 步骤 | 按钮在哪（客户区） |
|---|---|
| :func:`create_team` / :func:`add_pet` | 右侧偏中，约 x 2230~2430, y 855~915 |
| :func:`start_match` | 右下角，约 x 1935~2275, y 1165~1245 |

## 为什么三个按钮分成三个函数

它们在同一块面板的**同一个位置**，只有文字不同。合并成一个"找到哪个点哪个"
会丢掉两样东西：

* **状态守卫**：关联表把它们放在三个不同状态上，位置不对时根本轮不到这个函数；
* **失败信息**：现在能说清是"创建队伍"没认出来；合并之后只能说"三个都没认出来"。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.builtins import click_image
from gamebot.types import ActionResult, Region
from gamebot.types import Point as _Point

from ..templates import T_AFTER_ADD, T_AFTER_CREATE, T_BEFORE_CREATE, T_TIP

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["add_pet", "create_team", "start_match"]

#: 点按钮之后等界面反应的时间（秒）。
CLICK_SETTLE = 0.6


def create_team(ctx: RunContext) -> ActionResult[Any]:
    """建队前：点「创建队伍」。"""
    return click_image(ctx, T_BEFORE_CREATE, settle=CLICK_SETTLE)


def add_pet(ctx: RunContext) -> ActionResult[Any]:
    """建队后：点「添加伙伴」。

    和「创建队伍」同一个位置（只有文字不同），加框时可以共用同一个框。
    """
    return click_image(ctx, T_AFTER_CREATE, settle=CLICK_SETTLE)


def start_match(ctx: RunContext) -> ActionResult[Any]:
    """加完伙伴：点「开始匹配」，然后处理**可能**弹出的提示框。

    不"等弹窗出现"（没弹就白等），而是：点按钮 → 睡一下 → 认一下在不在 →
    在就勾选 + 确定。看不出来就不点，避免误点别处。
    """
    clicked = click_image(ctx, T_AFTER_ADD, settle=0.8)
    if not clicked.ok:
        return clicked

    tip = _find_tip(ctx)
    if tip is None:
        return clicked.with_meta(tip="没弹")

    # 先勾「本次登录不再提示」，再点确定（顺序反了勾选不生效）。
    # 偏移相对提示框左上角（tip1：框 (829,592)，复选框 (1148,874)，确定 (1085,951)）。
    ox, oy = tip.x, tip.y
    checkbox = _Point(ox + 319, oy + 282)
    checked = actions.click_logic_point(ctx.session, checkbox)
    if not checked.ok:
        return checked
    ctx.invalidate_frame()

    confirm = _Point(ox + 256, oy + 359)
    confirmed = actions.click_logic_point(ctx.session, confirm)
    if not confirmed.ok:
        return confirmed
    ctx.invalidate_frame()

    return clicked.with_meta(tip="已勾选并确认", tip_at=(ox, oy))


def _find_tip(ctx: RunContext) -> Region | None:
    """提示框在不在？在则返回其框（源坐标）。模板不含「确定」，点确定靠相对偏移。"""
    found = ctx.frame().find_image(T_TIP)
    if not found.ok or found.value is None:
        return None
    # find_image 返回中心点；相对偏移要从左上角算，取 meta.rect。
    rect = found.meta.get("rect")
    if not isinstance(rect, Region):  # pragma: no cover
        return None
    return rect
