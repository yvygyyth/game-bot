"""进战役 / 进千里单骑 / 打开选将 / 开始挑战。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.builtins import click_image
from gamebot.types import ActionResult, Point, Region

from ..pages import MAIN_PLACEHOLDER_ROI, START_ROI
from ..store import reset_run_state
from ..templates import T_NEXT, T_PLACEHOLDER, T_QIANLI_CARD, T_START

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["continue_run", "enter_campaign", "enter_qianli", "open_pick", "start_run"]

#: 首页「战役」卡的中心（源坐标）。这张卡在不同光照下分数只有 0.88 左右，
#: 而位置是固定的 —— 直接点中心比卡在阈值上更稳。
HOME_CAMPAIGN_POINT = Point(1995, 683)

#: 点完按钮等界面切换（秒）。
ENTER_SETTLE = 1.0
PICK_SETTLE = 0.8
START_SETTLE = 1.5


def enter_campaign(ctx: RunContext) -> ActionResult[Any]:
    """首页 → 点「战役」卡。"""
    clicked = actions.click_source_point(ctx.session, HOME_CAMPAIGN_POINT)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(ENTER_SETTLE)
    return clicked.with_meta(point=(HOME_CAMPAIGN_POINT.x, HOME_CAMPAIGN_POINT.y))


def enter_qianli(ctx: RunContext) -> ActionResult[Any]:
    """战役界面 → 点「千里单骑」卡。"""
    return click_image(
        ctx,
        T_QIANLI_CARD,
        region=Region(700, 480, 320, 390),
        settle=ENTER_SETTLE,
    )


def open_pick(ctx: RunContext) -> ActionResult[Any]:
    """主界面 → 点「选择武将」占位卡，打开选将面板。"""
    return click_image(
        ctx,
        T_PLACEHOLDER,
        region=MAIN_PLACEHOLDER_ROI,
        settle=PICK_SETTLE,
    )


def start_run(ctx: RunContext) -> ActionResult[Any]:
    """已选将 → 点红色「开始挑战」，进入局内（开新一局的状态）。"""
    reset_run_state(ctx)
    return click_image(ctx, T_START, region=START_ROI, settle=START_SETTLE)


def continue_run(ctx: RunContext) -> ActionResult[Any]:
    """已有进行中的局 → 点红色「继续挑战」，直接进局内。

    继续的是**原来那局**：铜币/赠礼记录可能还在，这里不重置，
    由局内流程按实际画面自己补。
    """
    return click_image(ctx, T_NEXT, region=START_ROI, settle=START_SETTLE)
