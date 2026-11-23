"""局内：地图选节点 → 战斗 → 赠礼 → 回地图 / 本局结束。

战斗是**全程托管**：和竞技场一样先点「取消」关掉换牌弹窗，再点「托管」，
然后等「点击空白区域到下一步」。不做出牌/取消等战斗操作。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.atomic.query import ImageQuery, any_image
from gamebot.execution.builtins import click_image, press, wait_for
from gamebot.types import ActionResult, Point, Region
from games.mingjiangsha.utils import (
    click_cyan_glow,
    click_gold_frame,
    gold_frame_enabled,
)

from ..pages import CLAIM_ROI, NODE_REGION, POCKET_CONFIRM_ROI, START_BATTLE_ROI
from ..store import (
    COPPER_REGION,
    RewardKind,
    get_run_state,
    parse_copper_text,
    parse_general_name,
    pick_reward_kind,
    pick_reward_slot,
    rank_token_slots,
    refresh_copper_coins,
    resolve_general_priority,
)
from ..templates import (
    T_EVENT_BATTLE_LEFT,
    T_EVENT_BATTLE_RIGHT,
    T_EVENT_FEIFEI_BARGAIN,
    T_EVENT_FEIFEI_HELP,
    T_EVENT_FEIFEI_SLEEP,
    T_FIGHT_AUTO,
    T_FIGHT_CANCEL,
    T_FIGHT_END,
    T_FIGHT_MENU,
    T_FIGHT_WIN_CLOSE,
    T_NODE_BATTLE,
    T_NODE_FEI_FEI,
    T_NODE_KA_KA,
    T_NODE_MO_ZI,
    T_NODE_POCKET,
    T_NODE_REST,
    T_NODE_SHI_CHANG,
    T_NODE_SHOP_BA_QING,
    T_NODE_ZHUGE,
    T_NODE_ZUO_CI,
    T_POCKET_CONFIRM,
    T_POCKET_OPTION,
    T_REWARD_BUFF,
    T_REWARD_CARD,
    T_REWARD_HELP,
    T_REWARD_JOINT,
    T_REWARD_TOKEN,
    T_SHI_ATTACK,
    T_SHOP_CONFIRM,
    T_SHOP_EXIT,
    T_START_BATTLE,
    T_ZHUGE_CONTINUE,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "BATTLE_END_TIMEOUT",
    "ESCAPE_BUTTON_REGION",
    "EVENT_ENTER_REGION",
    "EVENT_OPTION_POINTS",
    "EVENT_OPTION_PRIORITY",
    "EVENT_OPTION_REGIONS",
    "MOZI_OPTION_POINTS",
    "PENDING_GENERAL_KEY",
    "REST_OPTION_POINT",
    "SHOP_MIN_COINS",
    "SKILL_PANEL_CLOSE",
    "ZHUGE_CARD_POINT",
    "choose_event_option",
    "choose_mozi",
    "choose_node",
    "choose_pocket",
    "choose_rest",
    "claim_reward",
    "close_congrats",
    "close_skill_panel",
    "confirm_ba_qing_exit",
    "confirm_pocket",
    "do_zhuge",
    "enter_event",
    "escape_battle",
    "fight_cancel_hand_swap",
    "fight_choose_auto",
    "fight_click_end",
    "fight_click_next",
    "fight_close_menu",
    "fight_open_menu_or_wait",
    "pick_gift",
    "pick_kind",
    "resolve_ba_qing_buy",
    "shop_ba_qing_pick",
    "start_battle",
    "start_event_duel",
    "trigger_shi_battle",
]

#: 选赠礼武将时，暂存在黑板里的名字（给第二屏选类别用）。
PENDING_GENERAL_KEY = "qianli.pending_general"

#: 赠礼类别 → 模板（点击标签中心）。
REWARD_KIND_IMAGES: dict[RewardKind, str] = {
    RewardKind.TOKEN: T_REWARD_TOKEN,
    RewardKind.JOINT: T_REWARD_JOINT,
    RewardKind.CARD: T_REWARD_CARD,
    RewardKind.HELP: T_REWARD_HELP,
    RewardKind.BUFF: T_REWARD_BUFF,
}

#: 赠礼第一屏三个武将标题的 OCR 区域（源坐标）。
REWARD_TITLE_REGIONS = (
    Region(390, 1010, 260, 90),
    Region(1170, 1010, 250, 90),
    Region(1940, 1010, 260, 90),
)

#: 三个标题的中心（OCR 不可用时默认点第一个）。
REWARD_SLOT_POINTS = (Point(505, 1052), Point(1280, 1052), Point(2054, 1052))

#: 地图上节点的匹配阈值。
NODE_CONFIDENCE = 0.9

#: 战斗最长等多久（秒）。自动战斗一局可能几分钟。
BATTLE_END_TIMEOUT = 1200.0

#: 本场战斗是否已经处理/确认过托管（黑板键）。
AUTO_READY_KEY = "qianli.fight.auto_ready"

#: 关「武将技能」弹窗的点击位置（客户区坐标；旧代码点 1300,1150 窗口坐标）。
SKILL_PANEL_CLOSE = Point(1300, 1127)

#: 铜币少于这个数就不进巴清商店（旧脚本的阈值）。
SHOP_MIN_COINS = 30

#: 购买弹窗底部两个按钮（金框购买 / 青色取消）所在的区域。
BA_QING_BUTTON_REGION = Region(600, 880, 1150, 250)

#: 商店右上角退出箭头的搜索区域。
#: **必须限定 ROI**：箭头是个小花纹图，全屏找在默认阈值下会卡在临界分之下
#: （真机实测：ROI 里 0.85 稳定命中，全屏 not_found），还会到处假命中。
SHOP_EXIT_REGION = Region(2300, 20, 260, 200)
SHOP_EXIT_CONFIDENCE = 0.85

#: 休息界面随便点一个选项（第一个）。
REST_OPTION_POINT = Point(457, 1150)

#: 墨子三选一的三个选项中心。
MOZI_OPTION_POINTS = (Point(1450, 380), Point(1450, 650), Point(1450, 920))

#: 诸葛亮：上卦/下卦中间那张卡的位置（外观随机、位置固定）。
ZHUGE_CARD_POINT = Point(1935, 690)
#: 出现「请点击继续」后点界面任意处。
ZHUGE_CONTINUE_POINT = Point(1300, 600)

#: 锦囊三选一的三个选项中心（随便点一个）。
# ---- 奇遇 ----
#: 「想逃？」意外战斗事件的金色按钮。
ESCAPE_BUTTON_REGION = Region(900, 1030, 780, 210)

#: 奇遇介绍页左下角的金色按钮（选择事件/选择武将）。
EVENT_ENTER_REGION = Region(650, 1140, 620, 220)

#: 奇遇选择页两行选项的 OCR 区域与点击点。
EVENT_OPTION_REGIONS = (Region(1000, 450, 900, 140), Region(1000, 700, 900, 140))
EVENT_OPTION_POINTS = (Point(1300, 530), Point(1300, 775))

#: 妃妃选项优先级（老代码：我来帮你 > 讨价还价）。
EVENT_OPTION_PRIORITY = ("快睡午觉", "我来帮你", "讨价还价")


def choose_node(ctx: RunContext) -> ActionResult[Any]:
    """地图上选一个节点：战斗优先，其次巴清商店（点两次）。"""
    battle = ctx.frame().find_all_images(
        T_NODE_BATTLE,
        region=NODE_REGION,
        confidence=NODE_CONFIDENCE,
        max_count=10,
        min_distance=80,
    )
    if battle.ok and battle.value:
        point = min(battle.value, key=lambda p: p.y)
        clicked = actions.click_source_point(ctx.session, point)
        if not clicked.ok:
            return clicked
        ctx.invalidate_frame()
        ctx.sleep(0.4)
        return clicked.with_meta(
            point=(point.x, point.y), count=len(battle.value), kind="battle"
        )

    # 没有战斗：巴清商店（铜币够才进）> 休息
    shop = ctx.frame().find_image(T_NODE_SHOP_BA_QING, region=NODE_REGION, confidence=0.9)
    if shop.ok and shop.value is not None:
        coins = refresh_copper_coins(ctx)
        if coins is None or coins >= SHOP_MIN_COINS:
            point = shop.value
            first = actions.click_source_point(ctx.session, point)
            if not first.ok:
                return first
            ctx.sleep(0.4)
            second = actions.click_source_point(ctx.session, point)
            if not second.ok:
                return second
            ctx.invalidate_frame()
            ctx.sleep(0.9)
            return second.with_meta(
                point=(point.x, point.y), kind="shop_ba_qing", coins=coins
            )

    pocket = ctx.frame().find_image(T_NODE_POCKET, region=NODE_REGION, confidence=0.9)
    if pocket.ok and pocket.value is not None:
        point = pocket.value
        first = actions.click_source_point(ctx.session, point)
        if not first.ok:
            return first
        ctx.sleep(0.4)
        second = actions.click_source_point(ctx.session, point)
        if not second.ok:
            return second
        ctx.invalidate_frame()
        ctx.sleep(0.9)
        return second.with_meta(point=(point.x, point.y), kind="pocket")

    rest = ctx.frame().find_image(T_NODE_REST, region=NODE_REGION, confidence=0.9)
    if rest.ok and rest.value is not None:
        point = rest.value
        first = actions.click_source_point(ctx.session, point)
        if not first.ok:
            return first
        ctx.sleep(0.4)
        second = actions.click_source_point(ctx.session, point)
        if not second.ok:
            return second
        ctx.invalidate_frame()
        ctx.sleep(0.9)
        return second.with_meta(point=(point.x, point.y), kind="rest")

    for template, kind in (
        (T_NODE_FEI_FEI, "fei_fei"),
        (T_NODE_SHI_CHANG, "shi_chang"),
        (T_NODE_MO_ZI, "mo_zi"),
        (T_NODE_ZHUGE, "zhuge"),
        (T_NODE_ZUO_CI, "zuo_ci"),
        (T_NODE_KA_KA, "ka_ka"),
    ):
        node = ctx.frame().find_image(template, region=NODE_REGION, confidence=0.9)
        if node.ok and node.value is not None:
            point = node.value
            clicked = actions.click_source_point(ctx.session, point)
            if not clicked.ok:
                return clicked
            ctx.invalidate_frame()
            ctx.sleep(0.8)
            return clicked.with_meta(point=(point.x, point.y), kind=f"event_{kind}")

    return ActionResult.not_found(
        "地图上没有可点的战斗/商店/休息/奇遇节点（其他节点后续再支持）",
        template=T_NODE_BATTLE,
    )


def start_battle(ctx: RunContext) -> ActionResult[Any]:
    """战斗预览 → 点「开始对局」。

    先按 404x107 的整按钮模板点（实测 1.0）；失败再用通用确认
    （金色花纹按钮，只认边框、不认文字）。
    """
    ctx.blackboard[AUTO_READY_KEY] = False
    # 先精确模板（单张匹配快、实测 1.0）；失败再走通用确认（全屏多模板，慢）
    clicked = click_image(
        ctx, T_START_BATTLE, region=START_BATTLE_ROI, confidence=0.9, settle=0.6
    )
    if not clicked.ok:
        clicked = click_gold_frame(ctx, region=START_BATTLE_ROI, settle=0.6)
    if clicked.ok:
        # 等战斗界面出现（右上角菜单），别让引擎把加载态当成"认不出来"等 5 秒
        wait_for(ctx, ImageQuery(T_FIGHT_MENU), timeout=8.0)
    return clicked


def fight_cancel_hand_swap(ctx: RunContext) -> ActionResult[Any]:
    """换牌弹窗：把鼠标移开 hover，再点取消。"""
    actions.move_to(ctx.session, Point(20, 20), duration=0.1)
    ctx.sleep(0.2)
    ctx.blackboard[AUTO_READY_KEY] = False
    return click_image(ctx, T_FIGHT_CANCEL, settle=0.4)


def fight_open_menu_or_wait(ctx: RunContext) -> ActionResult[Any]:
    """战斗主界面：没处理托管就开菜单；处理过就等结束提示。"""
    if ctx.blackboard.get(AUTO_READY_KEY):
        ended = wait_for(
            ctx,
            any_image(T_FIGHT_END, T_FIGHT_WIN_CLOSE, confidence=0.9),
            timeout=BATTLE_END_TIMEOUT,
        )
        if not ended.ok or ended.value is None:
            return ActionResult.not_found(
                f"战斗 {BATTLE_END_TIMEOUT:.0f}s 内没结束", template=T_FIGHT_END
            )
        return ActionResult.success("战斗结束提示", action="wait")
    return click_image(ctx, T_FIGHT_MENU, settle=0.4)


def fight_choose_auto(ctx: RunContext) -> ActionResult[Any]:
    """菜单展开且显示「托管」：点托管。"""
    clicked = click_image(ctx, T_FIGHT_AUTO, settle=0.4)
    if clicked.ok:
        ctx.blackboard[AUTO_READY_KEY] = True
    return clicked


def fight_close_menu(ctx: RunContext) -> ActionResult[Any]:
    """菜单展开且显示「取消托管」：确认托管已开，点菜单关闭。

    有的机器上胜利结算会把菜单图标挡住，但「取消托管」还在；这时
    点不到 menu.png 不能无限重试，看到「点击空白处关闭」就交给 ended。
    """
    ctx.blackboard[AUTO_READY_KEY] = True
    clicked = click_image(ctx, T_FIGHT_MENU, settle=0.4)
    if clicked.ok:
        return clicked
    # 菜单已经自动关闭：不要报错重试，等战斗结束
    return ActionResult.success("托管中，菜单已关", action="wait")


def fight_click_end(ctx: RunContext) -> ActionResult[Any]:
    """点「点击空白区域到下一步」。"""
    ended = click_image(ctx, T_FIGHT_END, settle=0.6)
    if ended.ok:
        return ended
    return click_image(ctx, T_FIGHT_WIN_CLOSE, settle=0.6)


def fight_click_next(ctx: RunContext) -> ActionResult[Any]:
    """结算后「下一步」：公共 gold_frame 按钮。"""
    return click_gold_frame(ctx, region=Region(900, 1100, 700, 250), settle=0.6)


def pick_gift(ctx: RunContext) -> ActionResult[Any]:
    """赠礼第一屏：OCR 三个武将名 → 按优先表选一个点它。"""
    # 三个标题拼一张画布只 OCR 一次；返回按区域分组的文本框
    read = ctx.frame().read_regions(REWARD_TITLE_REGIONS)
    groups = read.value if read.ok and read.value else []
    titles = [
        next((box.text for box in groups[i] if box.text), "") if i < len(groups) else ""
        for i in range(len(REWARD_TITLE_REGIONS))
    ]

    state = get_run_state(ctx)
    slot = pick_reward_slot(titles, state)
    name = parse_general_name(titles[slot]) if titles else ""
    ctx.blackboard[PENDING_GENERAL_KEY] = name

    point = REWARD_SLOT_POINTS[min(slot, len(REWARD_SLOT_POINTS) - 1)]
    clicked = actions.click_source_point(ctx.session, point)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.9)
    return clicked.with_meta(slot=slot, wu_jiang=name, titles=titles)


def pick_kind(ctx: RunContext) -> ActionResult[Any]:
    """赠礼第二屏：按武将优先表选一个类别（信物/资助/驰援…）。"""
    state = get_run_state(ctx)
    name = str(ctx.blackboard.get(PENDING_GENERAL_KEY, ""))
    entry = resolve_general_priority(name)

    available: dict[RewardKind, Point] = {}
    for kind, template in REWARD_KIND_IMAGES.items():
        hit = ctx.frame().find_image(template)
        if hit.ok and hit.value is not None:
            available[kind] = hit.value

    kind = pick_reward_kind(available.keys(), entry, state)
    if kind is None:
        return ActionResult.not_found("赠礼界面没有可点的类别")

    clicked = actions.click_source_point(ctx.session, available[kind])
    if not clicked.ok:
        return clicked
    if name:
        state.mark_general_reward(name, kind)
    else:
        state.mark_reward(kind)
    ctx.invalidate_frame()
    ctx.sleep(0.8)
    return clicked.with_meta(kind=kind.value, wu_jiang=name)


def close_skill_panel(ctx: RunContext) -> ActionResult[Any]:
    """武将技能/属性变动弹窗：点一下空白关闭，回地图。"""
    clicked = actions.click_source_point(ctx.session, SKILL_PANEL_CLOSE)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.6)
    return clicked


def shop_ba_qing_pick(ctx: RunContext) -> ActionResult[Any]:
    """商店主界面：按优先级点一个**买得起**的商品；都买不起就点退出箭头。

    铜币每轮重新 OCR（买完一件钱就变少，不能用旧值）；价格认不出数字
    的槽位视为已售罄，直接跳过。钱不够**跳过这一件看下一件**——
    优先级序不等于价格序，不能 break。
    """
    title_regions = (
        Region(1260, 260, 320, 80),
        Region(1715, 260, 320, 80),
        Region(2170, 260, 320, 80),
    )
    price_regions = (
        Region(1360, 625, 140, 70),
        Region(1815, 625, 140, 70),
        Region(2270, 625, 140, 70),
    )
    token_points = (Point(1416, 302), Point(1870, 302), Point(2326, 302))

    # 一次画布 OCR：钱包 + 3 个名字 + 3 个价格
    read = ctx.frame().read_regions((COPPER_REGION, *title_regions, *price_regions))
    groups = read.value if read.ok and read.value else []

    def _first_text(group: list[Any]) -> str:
        return next((box.text for box in group if box.text), "")

    wallet_text = _first_text(groups[0]) if groups else ""
    wallet = parse_copper_text(wallet_text)
    titles = [_first_text(groups[i]) if i < len(groups) else "" for i in range(1, 4)]
    prices = [
        parse_copper_text(_first_text(groups[i])) if i < len(groups) else None
        for i in range(4, 7)
    ]

    for slot, name in rank_token_slots(titles):
        price = prices[slot] if slot < len(prices) else None
        if price is None:
            continue  # 已售罄 / 认不出价格：跳过
        if wallet is not None and price > wallet:
            continue  # 钱不够这件：看下一件
        point = token_points[min(slot, len(token_points) - 1)]
        clicked = actions.click_source_point(ctx.session, point)
        if not clicked.ok:
            return clicked
        ctx.invalidate_frame()
        ctx.sleep(0.4)
        return clicked.with_meta(
            slot=slot, wu_jiang=name, price=price, wallet=wallet, titles=titles
        )

    # 没有可买的：点右上角退出箭头（引擎在下一帧认出结束弹窗或地图）
    exit_btn = ctx.frame().find_image(
        T_SHOP_EXIT, region=SHOP_EXIT_REGION, confidence=SHOP_EXIT_CONFIDENCE
    )
    if exit_btn.ok and exit_btn.value is not None:
        clicked = actions.click_source_point(ctx.session, exit_btn.value)
        if not clicked.ok:
            return clicked
        ctx.invalidate_frame()
        ctx.sleep(0.5)
        return clicked.with_meta(action="exit", wallet=wallet, titles=titles)

    return ActionResult.not_found(
        "商店里没有买得起的商品，也没找到退出箭头", template=T_SHOP_EXIT
    )


def resolve_ba_qing_buy(ctx: RunContext) -> ActionResult[Any]:
    """购买弹窗：金框购买按钮 = 钱够，买；灰框 = 钱不够，点「取消」。

    金/灰共用同一副花纹，边框环分不出来 —— 用 :func:`gold_frame_enabled`
    按饱和度分（见 buttons.py 的说明）。
    """
    enabled = gold_frame_enabled(ctx, BA_QING_BUTTON_REGION)
    if enabled is None:
        return ActionResult.not_found(
            "购买弹窗里没找到购买按钮", region=BA_QING_BUTTON_REGION
        )
    if enabled:
        clicked = click_gold_frame(ctx, BA_QING_BUTTON_REGION, settle=0.8)
        if clicked.ok:
            return clicked.with_meta(action="buy")
        return clicked
    clicked = click_cyan_glow(ctx, BA_QING_BUTTON_REGION, settle=0.6)
    if clicked.ok:
        return clicked.with_meta(action="cancel_insufficient")
    return clicked


def confirm_ba_qing_exit(ctx: RunContext) -> ActionResult[Any]:
    """是否结束购买？点「确认」回地图。"""
    confirm = ctx.frame().find_image(T_SHOP_CONFIRM)
    if not confirm.ok or confirm.value is None:
        return ActionResult.not_found(
            "结束购买弹窗里没找到「确认」按钮", template=T_SHOP_CONFIRM
        )
    clicked = actions.click_source_point(ctx.session, confirm.value)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.8)
    return clicked.with_meta(point=(confirm.value.x, confirm.value.y))


def choose_rest(ctx: RunContext) -> ActionResult[Any]:
    """休息：三个选项随便点一个，结束回地图。"""
    clicked = actions.click_source_point(ctx.session, REST_OPTION_POINT)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.9)
    return clicked.with_meta(point=(REST_OPTION_POINT.x, REST_OPTION_POINT.y))


def choose_pocket(ctx: RunContext) -> ActionResult[Any]:
    """锦囊三选一：用卡片左上角花纹找出三个选项，随机点一个。"""
    ctx.blackboard[AUTO_READY_KEY] = False
    hits = ctx.frame().find_all_images(T_POCKET_OPTION, min_distance=80, max_count=3)
    if not hits.ok or not hits.value:
        return ActionResult.not_found("锦囊三选一没找到选项", template=T_POCKET_OPTION)
    point = random.choice(hits.value)
    clicked = actions.click_source_point(ctx.session, point)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.8)
    return clicked.with_meta(point=(point.x, point.y))


def confirm_pocket(ctx: RunContext) -> ActionResult[Any]:
    """锦囊确认页：点「确认」。"""
    ctx.blackboard[AUTO_READY_KEY] = False
    return click_image(ctx, T_POCKET_CONFIRM, region=POCKET_CONFIRM_ROI, settle=1.0)


def enter_event(ctx: RunContext) -> ActionResult[Any]:
    """奇遇介绍页：点左边金色按钮（「选择事件」已加入 gold_frame 家族）。"""
    return click_gold_frame(ctx, EVENT_ENTER_REGION, settle=0.8)


def choose_event_option(ctx: RunContext) -> ActionResult[Any]:
    """奇遇选择页：妃妃按图片优先级选；其他事件先选第一行。

    妃妃优先级：快睡午觉 > 我来帮你 > 讨价还价（艺术字，用模板不 OCR）。
    """
    for template, name in (
        (T_EVENT_FEIFEI_SLEEP, "快睡午觉"),
        (T_EVENT_FEIFEI_HELP, "我来帮你"),
        (T_EVENT_FEIFEI_BARGAIN, "讨价还价"),
    ):
        hit = ctx.frame().find_image(template)
        if hit.ok and hit.value is not None:
            clicked = actions.click_source_point(ctx.session, hit.value)
            if not clicked.ok:
                return clicked
            ctx.invalidate_frame()
            ctx.sleep(0.8)
            return clicked.with_meta(option=name, point=(hit.value.x, hit.value.y))

    # 其他事件没有这几张模板：退回 OCR，再不行点第一行
    texts: list[str] = []
    for region in EVENT_OPTION_REGIONS:
        read = ctx.frame().read_text(region)
        texts.append(read.value if read.ok and read.value is not None else "")

    slot = 0
    for name in EVENT_OPTION_PRIORITY:
        for i, text in enumerate(texts):
            if name in text:
                slot = i
                break
        else:
            continue
        break

    point = EVENT_OPTION_POINTS[min(slot, len(EVENT_OPTION_POINTS) - 1)]
    clicked = actions.click_source_point(ctx.session, point)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.8)
    return clicked.with_meta(slot=slot, texts=texts)


def trigger_shi_battle(ctx: RunContext) -> ActionResult[Any]:
    """十常侍：点左边人物插画 5 次，触发战斗彩蛋。"""
    ctx.blackboard[AUTO_READY_KEY] = False
    click = ctx.frame().find_image(T_SHI_ATTACK)
    if not click.ok or click.value is None:
        return ActionResult.not_found("十常侍界面没找到左边人物插画", template=T_SHI_ATTACK)
    for _ in range(5):
        actions.click_source_point(ctx.session, click.value)
        ctx.sleep(0.2)
    ctx.invalidate_frame()
    ctx.sleep(0.8)
    return ActionResult.success(
        "十常侍插画点了 5 次", action="sequence", point=(click.value.x, click.value.y)
    )


def do_zhuge(ctx: RunContext) -> ActionResult[Any]:
    """诸葛亮占星：中间卡点两次（间隔 2s）→ 出现请点击继续 → 点任意处回地图。"""
    for i in range(2):
        actions.click_source_point(ctx.session, ZHUGE_CARD_POINT)
        if i == 0:
            ctx.sleep(2.0)
    ctx.invalidate_frame()
    ctx.sleep(0.6)

    cont = ctx.frame().find_image(T_ZHUGE_CONTINUE, confidence=0.99)
    if cont.ok:
        actions.click_source_point(ctx.session, ZHUGE_CONTINUE_POINT)
        ctx.invalidate_frame()
        ctx.sleep(0.8)
    return ActionResult.success(
        "诸葛亮占星完成", action="sequence", continued=bool(cont.ok)
    )


def choose_mozi(ctx: RunContext) -> ActionResult[Any]:
    """墨子三选一：随便点一行制造，选完回地图。"""
    point = random.choice(MOZI_OPTION_POINTS)
    clicked = actions.click_source_point(ctx.session, point)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.9)
    return clicked.with_meta(point=(point.x, point.y))


def escape_battle(ctx: RunContext) -> ActionResult[Any]:
    """想逃？→ 点「与项羽、范增战斗」，直接进战斗。"""
    return click_gold_frame(ctx, ESCAPE_BUTTON_REGION, settle=1.0)


def start_event_duel(ctx: RunContext) -> ActionResult[Any]:
    """意外战斗事件：用按钮左右两个金边角定位，点中间进战斗。"""
    left = ctx.frame().find_image(T_EVENT_BATTLE_LEFT)
    right = ctx.frame().find_image(T_EVENT_BATTLE_RIGHT)
    if not left.ok or not right.ok or left.value is None or right.value is None:
        return ActionResult.not_found("事件战斗按钮左右角没同时找到")
    point = Point((left.value.x + right.value.x + 64) // 2, left.value.y + 27)
    clicked = actions.click_source_point(ctx.session, point)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(1.0)
    return clicked.with_meta(point=(point.x, point.y))


def claim_reward(ctx: RunContext) -> ActionResult[Any]:
    """本局结束 → 点「确定」。"""
    return click_gold_frame(ctx, region=CLAIM_ROI, settle=1.2)


def close_congrats(ctx: RunContext) -> ActionResult[Any]:
    """「恭喜获得」浮层 → Esc 关闭，回到选将界面。"""
    return press(ctx, "esc", settle=1.0)
