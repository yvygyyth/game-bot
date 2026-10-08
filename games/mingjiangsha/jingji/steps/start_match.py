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

from ..pages import (
    CONF,
    T_AFTER_ADD,
    T_AFTER_CREATE,
    T_BEFORE_CREATE,
    T_TIP,
    TIP_CHECKBOX_OFFSET,
    TIP_CONFIRM_OFFSET,
    TIP_SETTLE,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["add_pet", "create_team", "start_match"]

#: 点按钮之后等界面反应的时间（秒）。
CLICK_SETTLE = 0.6


def create_team(ctx: RunContext) -> ActionResult[Any]:
    """建队前：点「创建队伍」。"""
    return click_image(ctx, T_BEFORE_CREATE, confidence=CONF, settle=CLICK_SETTLE)


def add_pet(ctx: RunContext) -> ActionResult[Any]:
    """建队后：点「添加伙伴」。

    和「创建队伍」**同一个位置**（只有文字不同），所以加框时可以共用同一个框。
    """
    return click_image(ctx, T_AFTER_CREATE, confidence=CONF, settle=CLICK_SETTLE)


def start_match(ctx: RunContext) -> ActionResult[Any]:
    """加完伙伴：点「开始匹配」，然后处理**可能**弹出的提示框。

    ## 提示框那一步不用状态表达

    理由见 `pages.py` 的模块 docstring：它只在这一处出现，而且是"按了按钮
    **可能**弹"。用它当状态要多一条边和一个"弹了就等"的判断，反而更绕。

    ## 不猜

    不"等弹窗出现"（没弹就白等满 timeout），而是：点按钮 → 睡
    :data:`~..pages.TIP_SETTLE` → **认一下提示框在不在** →
    在就勾选 + 确定，不在就直接成功返回。

    **"看不出来就不做"是这里的核心**：宁可漏掉一次勾选（下次登录还会弹，
    只影响体验），也不能在没弹窗时往那个坐标点一下（可能点到别的东西）。
    """
    clicked = click_image(ctx, T_AFTER_ADD, confidence=CONF, settle=TIP_SETTLE)
    if not clicked.ok:
        return clicked

    tip = _find_tip(ctx)
    if tip is None:
        # 不记成失败 —— 没弹窗是**正常情况**，不是出错
        return clicked.with_meta(tip="没弹")

    # 先勾「本次登录不再提示」，再点确定。
    # 顺序反了会先关掉弹窗，那次勾选就没生效（下次登录还会弹）。
    #
    # 两个点都是**相对提示框左上角**算的（见 pages 里那两个 OFFSET 的说明）：
    # 这样窗口或界面小位移时跟着走，而不是拿写死的绝对坐标去点。
    ox, oy = tip.x, tip.y
    checkbox = _Point(ox + TIP_CHECKBOX_OFFSET[0], oy + TIP_CHECKBOX_OFFSET[1])
    checked = actions.click_logic_point(ctx.session, checkbox)
    if not checked.ok:
        return checked
    ctx.invalidate_frame()

    confirm = _Point(ox + TIP_CONFIRM_OFFSET[0], oy + TIP_CONFIRM_OFFSET[1])
    confirmed = actions.click_logic_point(ctx.session, confirm)
    if not confirmed.ok:
        return confirmed
    ctx.invalidate_frame()

    return clicked.with_meta(tip="已勾选并确认", tip_at=(ox, oy))


def _find_tip(ctx: RunContext) -> Region | None:
    """提示框在不在？在的话返回它的框（**源坐标**）。

    ## 判据：模板 ``jj/tip.png``（整个提示框）

    提示框本体**特征足够丰富**（两行文字 + 复选框），所以单张模板就能可靠
    认出它，实测 15 张截图区分得很干净::

        tip1.png    1.000   <- 弹窗
        tip2.png    0.997   <- 弹窗（已勾选）
        其余 13 张  0.179 ~ 0.327   <- 最接近的只有 0.327

    ## 这里原先是"平均亮度"判据，为什么换掉

    原来取复选框那一小块的平均亮度、和 210 比。它**能work但余量很薄**：

        zhandou1.png  199.4   <- 不是弹窗，离阈值 210 只差 10.6
        tip1/tip2     219.5   <- 弹窗

    也就是说 zhandou1 那张只要再亮一点就会误判成"弹了"，然后往提示框的
    坐标点两下 —— 而这一步误判的代价正是"点了不该点的东西"。

    当时的理由是"复选框太素，当模板会误命中（0.89 > 0.85）"。那条理由
    **只对"只裁复选框"成立**；改成裁**整个提示框**之后，多出来的两行文字
    把区分度拉开了（0.327 vs 1.000）。
    """
    found = ctx.frame().find_image(T_TIP, confidence=CONF)
    if not found.ok or found.value is None:
        return None
    # 命中矩形在 meta 的 ``rect`` 里（``find_image`` 的第一返回值是**中心点**，
    # 而相对偏移要从左上角算，所以需要这个框）。
    rect = found.meta.get("rect")
    if not isinstance(rect, Region):  # pragma: no cover - 后端没给框时保守放弃
        return None
    return rect
