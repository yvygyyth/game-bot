"""每日领奖 —— 步骤。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.builtins import click_image, press
from gamebot.types import ActionResult, Point

from ..templates import (
    T_ACTIVITY_ENTRY,
    T_GALLERY_ENTRY,
    T_GALLERY_GIFT,
    T_MAIL_ENTRY,
    T_MAIL_ONE_CLICK,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "ACTIVITY_CARD_POINTS",
    "claim_gallery_then_finish",
    "draw_then_gallery",
    "finish_daily",
    "mail_claim_then_activity",
    "open_mail",
]

#: 活动卜卦：抽两张卡的位置（牌堆第一、第二张的中心）。
ACTIVITY_CARD_POINTS = (Point(754, 579), Point(986, 579))

SETTLE = 0.9


def _esc(ctx: RunContext, times: int = 2) -> None:
    for _ in range(times):
        press(ctx, "esc", settle=0.4)


def open_mail(ctx: RunContext) -> ActionResult[Any]:
    """首页 → 点邮件入口。"""
    return click_image(ctx, T_MAIL_ENTRY, confidence=0.85, settle=1.0)


def mail_claim_then_activity(ctx: RunContext) -> ActionResult[Any]:
    """邮箱：一键领取 → 关弹窗/关邮箱 → 点活动入口。"""
    claim = click_image(ctx, T_MAIL_ONE_CLICK, settle=SETTLE)
    if not claim.ok:
        # 没有可领也继续，不能卡在这
        pass
    _esc(ctx, 2)
    return click_image(ctx, T_ACTIVITY_ENTRY, confidence=0.9, settle=1.0)


def draw_then_gallery(ctx: RunContext) -> ActionResult[Any]:
    """活动：抽两张卡（今日卦象）→ 关活动 → 点丹青阁入口。"""
    for point in ACTIVITY_CARD_POINTS:
        actions.click_source_point(ctx.session, point)
        ctx.invalidate_frame()
        ctx.sleep(0.8)
    _esc(ctx, 2)
    return click_image(ctx, T_GALLERY_ENTRY, confidence=0.9, settle=1.0)


def claim_gallery_then_finish(ctx: RunContext) -> ActionResult[Any]:
    """丹青阁：点每日礼包；如果被购买弹窗挡住，先 Esc 再点。"""
    gift = click_image(ctx, T_GALLERY_GIFT, settle=SETTLE)
    if not gift.ok:
        # 刚进来可能弹「丹青月令」购买；Esc 关掉后再找礼包
        press(ctx, "esc", settle=0.6)
        gift = click_image(ctx, T_GALLERY_GIFT, settle=SETTLE)
    if not gift.ok:
        return ActionResult.not_found("丹青阁没找到「每日礼包」", template=T_GALLERY_GIFT)
    _esc(ctx, 2)
    return ActionResult.success("每日礼包已领取", action="sequence")


def finish_daily(ctx: RunContext) -> ActionResult[Any]:
    """收尾：返回 not_found 让末梢判定结束。"""
    return ActionResult.not_found("每日领奖完成")
