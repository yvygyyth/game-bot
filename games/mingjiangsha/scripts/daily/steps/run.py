"""每日领奖 —— 步骤。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.builtins import click_image, press
from gamebot.types import ActionResult, Point
from games.mingjiangsha.utils import click_gold_frame

from ..templates import (
    T_ACTIVITY_ENTRY,
    T_FLOWER_ENTRY,
    T_FREE_BINGLI,
    T_GALLERY_ENTRY,
    T_GALLERY_GIFT,
    T_GONG_HUI_ENTRY,
    T_GONGHUI_STORE_ENTRY,
    T_LINGXI,
    T_MAIL_ENTRY,
    T_MAIL_ONE_CLICK,
    T_MAX,
    T_MINGJIANG,
    T_QINGMEI_ENTRY,
    T_SHOP_ENTRY,
    T_ZHAN_YI_ENTRY,
    T_ZHANYI_SHOP_ENTRY,
    T_ZHU_JIU_ENTRY,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "ACTIVITY_CARD_POINTS",
    "FLOWER_FRIEND",
    "FLOWER_GIFT",
    "FLOWER_ITEM",
    "FLOWER_X100",
    "SHOP_ITEM_GONGHUI",
    "SHOP_ITEM_QINGMEI",
    "SHOP_ITEM_ZHANYI",
    "SHOP_TAB_COPPER",
    "SHOP_TAB_GOLD",
    "SHOP_TAB_JINLAN",
    "buy_shop_then_finish",
    "claim_gallery_then_finish",
    "draw_then_gallery",
    "finish_daily",
    "gong_hui_step",
    "mail_claim_then_activity",
    "open_mail",
    "send_flower_finish",
    "zhan_yi_step",
    "zhu_jiu_step",
]

#: 活动卜卦：抽两张卡的位置（牌堆第一、第二张的中心）。
ACTIVITY_CARD_POINTS = (Point(1179, 979), Point(1767, 979))

#: 商店页签位置（黄金/铜钱/金兰）。
SHOP_TAB_GOLD = Point(1306, 354)
SHOP_TAB_COPPER = Point(1669, 354)
SHOP_TAB_JINLAN = Point(2017, 354)

#: 各商店里「名将册」等商品的大致位置（客户区固定）。
SHOP_ITEM_QINGMEI = Point(525, 600)
SHOP_ITEM_ZHANYI = Point(2050, 600)
SHOP_ITEM_GONGHUI = Point(2050, 600)

#: 送花界面固定点：送礼 / 油菜花 / 赠送x100 / 好友头像。
FLOWER_GIFT = Point(330, 990)
FLOWER_ITEM = Point(1865, 980)
FLOWER_X100 = Point(2270, 1210)
FLOWER_FRIEND = Point(480, 400)

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
        # 翻牌有动画，等它翻完再点第二张；否则第二张会点在动画上
        ctx.sleep(1.2)
    _esc(ctx, 2)
    return click_image(ctx, T_GALLERY_ENTRY, confidence=0.9, settle=1.0)


def claim_gallery_then_finish(ctx: RunContext) -> ActionResult[Any]:
    """丹青阁：点每日礼包；进来可能先弹「丹青月令」购买，Esc 关掉再看。

    第一次找不到先等加载/动画（可能是刚进丹青阁还没画完），不要立刻按 Esc ——
    Esc 在正常丹青阁里会直接退出去，反而把每日礼包关掉。
    """
    gift = None
    for attempt in range(3):
        gift = click_image(ctx, T_GALLERY_GIFT, settle=SETTLE)
        if gift.ok:
            break
        if attempt == 0:
            ctx.sleep(1.0)  # 等丹青阁加载/动画
            continue
        press(ctx, "esc", settle=0.8)  # 关「丹青月令」购买弹窗
        ctx.sleep(1.0)
    if gift is None or not gift.ok:
        return ActionResult.not_found("丹青阁没找到「每日礼包」", template=T_GALLERY_GIFT)
    _esc(ctx, 2)
    # 回首页后点「商店」入口
    return click_image(ctx, T_SHOP_ENTRY, confidence=0.9, settle=1.0)


def buy_shop_then_finish(ctx: RunContext) -> ActionResult[Any]:
    """商店：黄金免费兵力 → 铜钱灵犀盒 → 金兰名将册 → 关。"""
    actions.click_source_point(ctx.session, SHOP_TAB_GOLD)
    ctx.sleep(0.6)
    free = click_image(ctx, T_FREE_BINGLI, settle=0.5)
    if free.ok:
        click_gold_frame(ctx, settle=0.5)

    actions.click_source_point(ctx.session, SHOP_TAB_COPPER)
    ctx.sleep(0.6)
    lingxi = click_image(ctx, T_LINGXI, settle=0.5)
    if lingxi.ok:
        click_image(ctx, T_MAX, settle=0.4)
        click_gold_frame(ctx, settle=0.6)
    press(ctx, "esc", settle=0.5)

    actions.click_source_point(ctx.session, SHOP_TAB_JINLAN)
    ctx.sleep(0.6)
    ming = click_image(ctx, T_MINGJIANG, settle=0.5)
    if ming.ok:
        click_gold_frame(ctx, settle=0.6)
    press(ctx, "esc", settle=0.5)
    press(ctx, "esc", settle=0.6)
    # 打开煮酒（下一段）
    return click_image(ctx, T_ZHU_JIU_ENTRY, confidence=0.8, settle=1.0)


def zhu_jiu_step(ctx: RunContext) -> ActionResult[Any]:
    """煮酒 → 青梅商店 → 买一个 → 关两层 → 开战役。"""
    shop = click_image(ctx, T_QINGMEI_ENTRY, settle=1.0)
    if not shop.ok:
        return ActionResult.not_found("煮酒没找到「青梅商店」", template=T_QINGMEI_ENTRY)
    actions.click_source_point(ctx.session, SHOP_ITEM_QINGMEI)
    ctx.sleep(0.5)
    click_image(ctx, T_MAX, settle=0.4)
    click_gold_frame(ctx, settle=0.7)
    _esc(ctx, 2)
    return click_image(ctx, T_ZHAN_YI_ENTRY, settle=1.0)


def zhan_yi_step(ctx: RunContext) -> ActionResult[Any]:
    """战役 → 战役商店 → 买一个 → 关两层 → 开公会。"""
    shop = click_image(ctx, T_ZHANYI_SHOP_ENTRY, settle=1.0)
    if not shop.ok:
        return ActionResult.not_found("战役没找到「战役商店」", template=T_ZHANYI_SHOP_ENTRY)
    actions.click_source_point(ctx.session, SHOP_ITEM_ZHANYI)
    ctx.sleep(0.5)
    click_image(ctx, T_MAX, settle=0.4)
    click_gold_frame(ctx, settle=0.7)
    _esc(ctx, 2)
    return click_image(ctx, T_GONG_HUI_ENTRY, settle=1.0)


def gong_hui_step(ctx: RunContext) -> ActionResult[Any]:
    """公会 → 商店 → 买一个 → 关两层 → 结束。"""
    shop = click_image(ctx, T_GONGHUI_STORE_ENTRY, settle=1.0)
    if not shop.ok:
        return ActionResult.not_found("公会没找到「商店」入口", template=T_GONGHUI_STORE_ENTRY)
    actions.click_source_point(ctx.session, SHOP_ITEM_GONGHUI)
    ctx.sleep(0.5)
    click_image(ctx, T_MAX, settle=0.4)
    click_gold_frame(ctx, settle=0.7)
    _esc(ctx, 2)
    # 打开好友/送花（下一段）
    return click_image(ctx, T_FLOWER_ENTRY, confidence=0.9, settle=1.0)


def send_flower_finish(ctx: RunContext) -> ActionResult[Any]:
    """好友：送礼 → 选油菜花 → 赠送x100 → 点好友 → 关。"""
    actions.click_source_point(ctx.session, FLOWER_GIFT)
    ctx.sleep(0.6)
    actions.click_source_point(ctx.session, FLOWER_ITEM)
    ctx.sleep(0.4)
    actions.click_source_point(ctx.session, FLOWER_X100)
    ctx.sleep(0.4)
    actions.click_source_point(ctx.session, FLOWER_FRIEND)
    ctx.sleep(0.8)
    _esc(ctx, 2)
    return ActionResult.success("送花完成", action="sequence")


def finish_daily(ctx: RunContext) -> ActionResult[Any]:
    """收尾：返回 not_found 让末梢判定结束。"""
    return ActionResult.not_found("每日领奖完成")
