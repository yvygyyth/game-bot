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

import numpy as np

from gamebot.atomic import actions
from gamebot.execution.builtins import click_image
from gamebot.types import ActionResult, Region

from ..pages import (
    CONF,
    T_AFTER_ADD,
    T_AFTER_CREATE,
    T_BEFORE_CREATE,
    TIP_CHECKBOX,
    TIP_CONFIRM,
    TIP_SAMPLE,
    TIP_SAMPLE_BRIGHTNESS,
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
    :data:`~..pages.TIP_SETTLE` → **看一眼那个复选框在不在** →
    在就勾选 + 确定，不在就直接成功返回。

    **"看不出来就不做"是这里的核心**：宁可漏掉一次勾选（下次登录还会弹，
    只影响体验），也不能在没弹窗时往那个坐标点一下（可能点到别的东西）。
    """
    clicked = click_image(ctx, T_AFTER_ADD, confidence=CONF, settle=TIP_SETTLE)
    if not clicked.ok:
        return clicked

    if not _tip_visible(ctx):
        # 不记成失败 —— 没弹窗是**正常情况**，不是出错
        return clicked.with_meta(tip="没弹")

    # 先勾「本次登录不再提示」，再点确定。
    # 顺序反了会先关掉弹窗，那次勾选就没生效（下次登录还会弹）。
    checked = actions.click_logic_point(ctx.session, TIP_CHECKBOX)
    if not checked.ok:
        return checked
    ctx.invalidate_frame()

    confirmed = actions.click_logic_point(ctx.session, TIP_CONFIRM)
    if not confirmed.ok:
        return confirmed
    ctx.invalidate_frame()

    return clicked.with_meta(tip="已勾选并确认")


def _tip_visible(ctx: RunContext) -> bool:
    """提示框在不在？

    ## 判据：复选框那一小块方格的**平均亮度**

    弹窗里那个复选框是**浅色面板上的一个亮方块**，而同一个位置在别的界面上
    是深色地形。实测（15 张截图，客户区 ``TIP_SAMPLE``）：:

        tip1.png   219.5   <- 弹窗（未勾选）
        tip2.png   219.5   <- 弹窗（已勾选）
        zhandou1   199.4   <- 最接近的"非弹窗"
        其余 12 张  50~166

    阈值 :data:`~..pages.TIP_SAMPLE_BRIGHTNESS` 取 **210**，落在两者之间。

    ## 为什么不用模板匹配

    试过了：复选框**太素**（灰白方格），裁出来的模板在别的界面的空白块上
    能拿到 0.89 分，比阈值还高 —— 会误判成"弹了"。而这一步误判的代价是
    **往固定坐标点两下**，所以宁可换一个更钝但更可靠的判据。

    这个判据**只在这一步成立**：调用它的时机是"刚点完开始匹配"，
    此刻游戏一定还在竞技场界面上（那个位置是深色），所以对比是干净的
    —— 和那 15 张截图里量到的一致。
    """
    patch = _sample(ctx.frame(), TIP_SAMPLE)
    if patch is None:  # pragma: no cover - 拿不到像素时保守返回"没弹"
        return False
    return float(np.asarray(patch).mean()) >= TIP_SAMPLE_BRIGHTNESS


def _sample(frame: Any, region: Region) -> np.ndarray | None:
    """从帧里取一块像素（**源坐标**）。

    走 ``to_numpy()`` 而不是直接读 ``frame.array`` —— 前者是公开接口，
    而且拿到的一定是 BGR ndarray；后者是实现细节。
    """
    try:
        full = frame.to_numpy()
    except Exception:  # pragma: no cover - 后端不支持时保守返回 None
        return None
    y1, x1 = region.y, region.x
    return np.asarray(full[y1 : y1 + region.h, x1 : x1 + region.w])
