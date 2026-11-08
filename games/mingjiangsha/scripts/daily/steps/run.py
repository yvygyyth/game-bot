"""每日领奖 —— 步骤。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.builtins import click_image, press
from gamebot.types import ActionResult, Point
from games.mingjiangsha.utils import click_gold_frame

from ..entries import ENTRIES
from ..red import has_red
from ..templates import (
    T_FREE_BINGLI,
    T_GALLERY_GIFT,
    T_GALLERY_MONTHLY,
    T_GONGHUI_STORE_ENTRY,
    T_HOME,
    T_MAIL_ONE_CLICK,
    T_MAX,
    T_QINGMEI_ENTRY,
    T_SHOP_LINGXI,
    T_SHOP_MINGJIANG,
    T_SHOP_TAB_COPPER,
    T_SHOP_TAB_JINLAN,
    T_ZHANYI_SHOP_ENTRY,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "ACTIVITY_CARD_POINTS",
    "FLOWER_FRIEND",
    "FLOWER_GIFT",
    "FLOWER_ITEM",
    "FLOWER_X100",
    "JUNXU_CLAIM_POINTS",
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
    "send_flower_finish",
    "visit_next_entry",
    "zhan_yi_step",
    "zhu_jiu_step",
]

#: 活动卜卦：点上排牌堆里随便两张（最左、最右两张牌的中心）。
ACTIVITY_CARD_POINTS = (Point(735, 584), Point(2203, 584))

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

#: 军需月令页：两个「立即领取」按钮（普通 / 高级）。
JUNXU_CLAIM_POINTS = (Point(1054, 1076), Point(1931, 1076))

#: 活动左侧菜单的悬停点（滚轮要指在上面才响应）。
JUNXU_MENU_POINT = Point(180, 800)

#: 丹青阁每日礼包固定点（新布局左下角）。
GALLERY_GIFT_POINT = Point(145, 1205)


def _close_activity_reward(ctx: RunContext) -> None:
    """抽完两张卡会弹「恭喜获得」，先关掉再滚动/点军需月令。"""
    for _ in range(3):
        hit = ctx.frame().find_text("恭喜获得")
        if not hit.ok:
            return
        # 弹窗提示“点击空白处关闭”；先 Esc，没关掉再点空白
        press(ctx, "esc", settle=0.6)
        ctx.invalidate_frame()
        ctx.sleep(0.4)
        if not ctx.frame().find_text("恭喜获得").ok:
            return
        actions.click_source_point(ctx.session, Point(1300, 760))
        ctx.invalidate_frame()
        ctx.sleep(0.5)


def _claim_junxu(ctx: RunContext) -> bool:
    """活动左侧列表往下滚，找到「军需月令」→ 点进去领两个日常。

    找不到就返回 False，不阻断后续抽卡/丹青阁。
    """
    for _ in range(3):
        actions.scroll(ctx.session, -4, point=JUNXU_MENU_POINT)
        ctx.invalidate_frame()
        ctx.sleep(0.6)
        hit = ctx.frame().find_text("军需月令")
        if hit.ok and hit.value is not None:
            actions.click_source_point(ctx.session, hit.value)
            ctx.invalidate_frame()
            ctx.sleep(1.0)
            for point in JUNXU_CLAIM_POINTS:
                actions.click_source_point(ctx.session, point)
                ctx.sleep(0.7)
            press(ctx, "esc", settle=0.8)
            return True
    return False


def _esc(ctx: RunContext, times: int = 2) -> None:
    for _ in range(times):
        press(ctx, "esc", settle=0.4)


def visit_next_entry(ctx: RunContext) -> ActionResult[Any]:
    """首页 hub：按红点挑下一个入口。

    * 邮件/活动/丹青阁/商店：有红点才进；
    * 煮酒/战役/公会/送花：日常流程，没有红点也进一次；
    * 任何一个入口只处理一次，全部处理完置 ``daily.done`` 走 finish。
    """
    # 首页都没确认时绝不按固定点点入口（否则会把“认不出来的画面”点开邮箱）
    home = ctx.frame().find_image(T_HOME, confidence=0.95)
    if not home.ok:
        return ActionResult.not_found("首页未确认", template=T_HOME)

    visited = set(ctx.blackboard.get("daily.visited", []))
    image = ctx.frame().to_numpy()
    for entry in ENTRIES:
        if entry.key in visited:
            continue
        if (
            entry.check_red
            and entry.badge is not None
            and not has_red(image, entry.badge, min_pixels=80)
        ):
            visited.add(entry.key)
            continue
        clicked = actions.click_source_point(ctx.session, entry.click)
        if not clicked.ok:
            return clicked
        visited.add(entry.key)
        ctx.blackboard["daily.visited"] = sorted(visited)
        return clicked.with_meta(entry=entry.key)

    ctx.blackboard["daily.visited"] = []
    ctx.blackboard["daily.done"] = True
    return ActionResult.success("所有入口处理完成")


def mail_claim_then_activity(ctx: RunContext) -> ActionResult[Any]:
    """邮箱：一键领取 → 关弹窗/关邮箱 → 点活动入口。"""
    claim = click_image(ctx, T_MAIL_ONE_CLICK, settle=SETTLE)
    if not claim.ok:
        # 没有可领也继续，不能卡在这
        pass
    _esc(ctx, 2)
    return ActionResult.success("邮件领取完成")


def draw_then_gallery(ctx: RunContext) -> ActionResult[Any]:
    """活动：抽两张卡（今日卦象）→ 关活动 → 点丹青阁入口。"""
    for point in ACTIVITY_CARD_POINTS:
        actions.click_source_point(ctx.session, point)
        ctx.invalidate_frame()
        # 翻牌有动画，等它翻完再点第二张；否则第二张会点在动画上
        ctx.sleep(1.2)
    # 第二张翻完会弹「恭喜获得」，不关掉会挡住军需月令/退出
    _close_activity_reward(ctx)
    # 军需月令在活动左侧列表下面，先滚下去领；找不到也不影响后面的丹青阁
    _claim_junxu(ctx)
    _esc(ctx, 2)
    return ActionResult.success("活动领取完成")


def claim_gallery_then_finish(ctx: RunContext) -> ActionResult[Any]:
    """丹青阁：先关「丹青月令」购买弹窗，再点每日礼包，最后退出。"""
    # 没买丹青月令时进来会直接弹购买页（有「续费」按钮）；先 Esc 回丹青阁
    monthly = ctx.frame().find_image(T_GALLERY_MONTHLY)
    if monthly.ok:
        press(ctx, "esc", settle=0.8)
        ctx.invalidate_frame()
        ctx.sleep(1.0)

    gift = click_image(ctx, T_GALLERY_GIFT, settle=SETTLE)
    if not gift.ok:
        # 刚进来可能弹「丹青月令」购买；Esc 关掉后再找礼包
        press(ctx, "esc", settle=0.6)
        gift = click_image(ctx, T_GALLERY_GIFT, settle=SETTLE)
    if not gift.ok:
        # 新布局/红点变化时模板可能对不上，兜底点左下角每日礼包
        actions.click_source_point(ctx.session, GALLERY_GIFT_POINT)
        ctx.invalidate_frame()
        ctx.sleep(0.8)
        gift = ActionResult.success("点每日礼包固定点")
    _esc(ctx, 2)
    return ActionResult.success("丹青阁领取完成")


def _buy_if_present(ctx: RunContext, template: str) -> bool:
    """商店里看到目标商品才点，没看到就跳过（不按固定格子瞎买）。"""
    item = click_image(ctx, template, confidence=0.85, settle=0.5)
    if not item.ok:
        return False
    click_image(ctx, T_MAX, settle=0.4)
    click_gold_frame(ctx, settle=0.6)
    return True


def buy_shop_then_finish(ctx: RunContext) -> ActionResult[Any]:
    """商店：黄金免费兵力 → 铜钱灵犀宝箱 → 金兰名将册。"""
    actions.click_source_point(ctx.session, SHOP_TAB_GOLD)
    ctx.sleep(0.6)
    free = click_image(ctx, T_FREE_BINGLI, settle=0.5)
    if free.ok:
        click_gold_frame(ctx, settle=0.5)

    # 铜钱页签用「铜钱」艺术字模板，别按固定坐标
    tab = click_image(ctx, T_SHOP_TAB_COPPER, confidence=0.9, settle=0.6)
    if not tab.ok:
        actions.click_source_point(ctx.session, SHOP_TAB_COPPER)
        ctx.sleep(0.6)
    _buy_if_present(ctx, T_SHOP_LINGXI)
    press(ctx, "esc", settle=0.5)

    tab = click_image(ctx, T_SHOP_TAB_JINLAN, confidence=0.9, settle=0.6)
    if not tab.ok:
        actions.click_source_point(ctx.session, SHOP_TAB_JINLAN)
        ctx.sleep(0.6)
    _buy_if_present(ctx, T_SHOP_MINGJIANG)
    press(ctx, "esc", settle=0.5)
    press(ctx, "esc", settle=0.6)
    return ActionResult.success("商店购买完成")


def zhu_jiu_step(ctx: RunContext) -> ActionResult[Any]:
    """煮酒 → 青梅商店：只买名将册/灵犀宝箱，没看到就退出。"""
    shop = click_image(ctx, T_QINGMEI_ENTRY, settle=1.0)
    if not shop.ok:
        return ActionResult.not_found("煮酒没找到「青梅商店」", template=T_QINGMEI_ENTRY)
    _buy_if_present(ctx, T_SHOP_MINGJIANG)
    _buy_if_present(ctx, T_SHOP_LINGXI)
    _esc(ctx, 2)
    return ActionResult.success("煮酒购买完成")


def zhan_yi_step(ctx: RunContext) -> ActionResult[Any]:
    """战役 → 战役商店：只买名将册/灵犀宝箱，不买问鼎令。"""
    shop = click_image(ctx, T_ZHANYI_SHOP_ENTRY, settle=1.0)
    if not shop.ok:
        return ActionResult.not_found("战役没找到「战役商店」", template=T_ZHANYI_SHOP_ENTRY)
    _buy_if_present(ctx, T_SHOP_MINGJIANG)
    _buy_if_present(ctx, T_SHOP_LINGXI)
    _esc(ctx, 2)
    return ActionResult.success("战役购买完成")


def gong_hui_step(ctx: RunContext) -> ActionResult[Any]:
    """公会 → 商店：只买名将册/灵犀宝箱。"""
    shop = click_image(ctx, T_GONGHUI_STORE_ENTRY, settle=1.0)
    if not shop.ok:
        return ActionResult.not_found("公会没找到「商店」入口", template=T_GONGHUI_STORE_ENTRY)
    _buy_if_present(ctx, T_SHOP_MINGJIANG)
    _buy_if_present(ctx, T_SHOP_LINGXI)
    _esc(ctx, 2)
    return ActionResult.success("公会购买完成")


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
    """收尾：清掉本轮 hub 状态，返回 not_found 让末梢判定结束。"""
    ctx.blackboard["daily.visited"] = []
    ctx.blackboard["daily.done"] = False
    return ActionResult.not_found("每日领奖完成")
