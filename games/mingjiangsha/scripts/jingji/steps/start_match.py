"""推进队伍流程：创建队伍 → 添加伙伴 → 开始匹配。

按钮点击各走**对应家族的方法**（:func:`~games.mingjiangsha.utils.click_shadow_confirm`
/ :func:`~games.mingjiangsha.utils.click_pattern_confirm`）：底层只比**边框环**、
不认中间文字，所以换文案不用重裁图。

## 提示框不在这里了

「开始匹配」之后可能弹的提示框现在是**状态**：

| 状态 | 认什么 | 节点 / 步骤 |
|---|---|---|
| `tip/unchecked` | 框体 + 复选框（未勾） | `tip_check` / :func:`check_tip` |
| `tip/checked` | 框体 + 复选框（已勾） | `tip_confirm` / :func:`confirm_tip` |

流程图上 `match` 有三条出边：弹框未勾 → `tip_check`；弹框已勾 → `tip_confirm`；
没弹框、直接进选将 → `pick_general`。**没弹框是正常分支**，不是意外。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gamebot.execution.builtins import click_image
from gamebot.types import ActionResult, Region
from games.mingjiangsha.utils import click_pattern_confirm, click_shadow_confirm

from ..templates import T_TIP_CHECK

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["add_pet", "check_tip", "confirm_tip", "create_team", "start_match"]

#: 点按钮之后等界面反应的时间（秒）。
CLICK_SETTLE = 0.6

#: 按钮区（源坐标，2560x1369 客户区实测位置 + 余量）。
#: 给了 region 就不用全屏找 —— 找按钮从 ~0.8s 降到 ~0.05s。
#: 换分辨率/窗口大小后要跟着改（状态树的 roi 同理）。
TEAM_BUTTON_REGION = Region(2190, 820, 300, 160)
START_MATCH_REGION = Region(1900, 1120, 420, 160)

#: 提示框里两个可点位置（同样按实测位置 + 余量）。
TIP_CHECKBOX_REGION = Region(1080, 810, 150, 140)
TIP_CONFIRM_REGION = Region(930, 880, 330, 150)


def create_team(ctx: RunContext) -> ActionResult[object]:
    """建队前：点「创建队伍」。"""
    return click_shadow_confirm(ctx, TEAM_BUTTON_REGION, settle=CLICK_SETTLE)


def add_pet(ctx: RunContext) -> ActionResult[object]:
    """建队后：点「添加伙伴」。

    和「创建队伍」同一个位置、同一个家族（只有文字不同）——
    公共方法只比边框，所以它俩共用一套模板。
    """
    return click_shadow_confirm(ctx, TEAM_BUTTON_REGION, settle=CLICK_SETTLE)


def start_match(ctx: RunContext) -> ActionResult[object]:
    """加完伙伴：点「开始匹配」。

    之后弹不弹提示框由**状态**说了算（`tip/unchecked` / `tip/checked`），
    流程图会自己分流 —— 这个步骤不猜、不等待。
    """
    return click_pattern_confirm(ctx, START_MATCH_REGION, settle=0.8)


def check_tip(ctx: RunContext) -> ActionResult[object]:
    """提示框 · 未勾：点「本次登录不再提示」复选框。

    用复选框模板本身定位（和状态识别同一张图），点它的中心。
    """
    return click_image(ctx, T_TIP_CHECK, region=TIP_CHECKBOX_REGION, settle=0.4)


def confirm_tip(ctx: RunContext) -> ActionResult[object]:
    """提示框 · 已勾：点「确定」。

    「确定」和别的金色确认按钮同家族，所以直接用
    :func:`~games.mingjiangsha.utils.click_shadow_confirm`。
    """
    return click_shadow_confirm(ctx, TIP_CONFIRM_REGION, settle=0.8)
