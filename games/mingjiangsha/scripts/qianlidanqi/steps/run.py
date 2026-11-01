"""局内：地图选节点 → 战斗 → 赠礼 → 回地图 / 本局结束。

战斗是**全程托管**：和竞技场一样先点「取消」关掉换牌弹窗，再点「托管」，
然后等「点击空白区域到下一步」。不做出牌/取消等战斗操作。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.atomic.query import ImageQuery
from gamebot.execution.builtins import click_image, press, wait_for
from gamebot.types import ActionResult, Point, Region
from games.mingjiangsha.utils import click_pattern_confirm

from ..pages import CLAIM_ROI, NODE_REGION, POCKET_CONFIRM_ROI, START_BATTLE_ROI
from ..store import (
    RewardKind,
    get_run_state,
    parse_general_name,
    pick_reward_kind,
    pick_reward_slot,
    rank_token_slots,
    refresh_copper_coins,
    resolve_general_priority,
)
from ..templates import (
    T_CLAIM_REWARD,
    T_FIGHT_AUTO,
    T_FIGHT_AUTO_OFF,
    T_FIGHT_CANCEL,
    T_FIGHT_END,
    T_FIGHT_NEXT,
    T_NODE_BATTLE,
    T_NODE_FEI_FEI,
    T_NODE_KA_KA,
    T_NODE_POCKET,
    T_NODE_REST,
    T_NODE_SHOP_BA_QING,
    T_NODE_ZUO_CI,
    T_POCKET_CONFIRM,
    T_REWARD_BUFF,
    T_REWARD_CARD,
    T_REWARD_HELP,
    T_REWARD_JOINT,
    T_REWARD_TOKEN,
    T_SHOP_BUY_TITLE,
    T_SHOP_CONFIRM,
    T_SHOP_EXIT,
    T_SHOP_EXIT_PROMPT,
    T_START_BATTLE,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "BATTLE_END_TIMEOUT",
    "EVENT_ENTER_REGION",
    "EVENT_OPTION_POINTS",
    "EVENT_OPTION_PRIORITY",
    "EVENT_OPTION_REGIONS",
    "PENDING_GENERAL_KEY",
    "POCKET_OPTION_POINTS",
    "REST_OPTION_POINT",
    "SHOP_BUY_POINT",
    "SHOP_MIN_COINS",
    "SHOP_TOKEN_POINTS",
    "SHOP_TOKEN_TITLE_REGIONS",
    "SKILL_PANEL_CLOSE",
    "buy_ba_qing",
    "choose_event_option",
    "choose_node",
    "choose_pocket",
    "choose_rest",
    "claim_reward",
    "close_congrats",
    "close_skill_panel",
    "confirm_pocket",
    "enter_event",
    "pick_gift",
    "pick_kind",
    "run_battle",
    "start_battle",
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
    Region(390, 1052, 330, 55),
    Region(1060, 1052, 340, 55),
    Region(1780, 1052, 340, 55),
)

#: 三个标题的中心（OCR 不可用时默认点第一个）。
REWARD_SLOT_POINTS = (Point(555, 1082), Point(1230, 1082), Point(1950, 1082))

#: 地图上节点的匹配阈值。
NODE_CONFIDENCE = 0.9

#: 战斗最长等多久（秒）。自动战斗一局可能几分钟。
BATTLE_END_TIMEOUT = 1200.0

#: 关「武将技能」弹窗的点击位置（客户区坐标；旧代码点 1300,1150 窗口坐标）。
SKILL_PANEL_CLOSE = Point(1300, 1127)

# ---- 巴清商店 ----
#: 三个信物标题的 OCR 区域（客户区）。
SHOP_TOKEN_TITLE_REGIONS = (
    Region(1276, 277, 280, 50),
    Region(1730, 277, 280, 50),
    Region(2186, 277, 280, 50),
)

#: 三个信物标题的中心（点它选中）。
SHOP_TOKEN_POINTS = (Point(1416, 302), Point(1870, 302), Point(2326, 302))

#: 购买弹窗里「xx购买」按钮的中心（客户区固定）。
SHOP_BUY_POINT = Point(842, 964)

#: 铜币少于这个数就不进巴清商店（旧脚本的阈值）。
SHOP_MIN_COINS = 30

#: 休息界面随便点一个选项（第一个）。
REST_OPTION_POINT = Point(457, 1150)

#: 锦囊三选一的三个选项中心（随便点一个）。
POCKET_OPTION_POINTS = (Point(457, 1150), Point(1317, 1150), Point(2155, 1150))

# ---- 奇遇 ----
#: 奇遇介绍页左下角的金色按钮（选择事件/选择武将）。
EVENT_ENTER_REGION = Region(680, 1180, 520, 160)

#: 奇遇选择页两行选项的 OCR 区域与点击点。
EVENT_OPTION_REGIONS = (Region(1000, 450, 900, 140), Region(1000, 700, 900, 140))
EVENT_OPTION_POINTS = (Point(1300, 530), Point(1300, 775))

#: 妃妃选项优先级（老代码：我来帮你 > 讨价还价）。
EVENT_OPTION_PRIORITY = ("我来帮你", "讨价还价")


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
        ctx.sleep(0.8)
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
    """战斗预览 → 点「开始对局」。"""
    return click_image(ctx, T_START_BATTLE, region=START_BATTLE_ROI, settle=1.2)


def run_battle(ctx: RunContext) -> ActionResult[Any]:
    """战斗内：取消换牌 → 点托管 → 等结束 → 点下一步。"""
    # ---- 1. 换牌弹窗：和竞技场一样点「取消」----
    cancel = wait_for(ctx, ImageQuery(T_FIGHT_CANCEL), timeout=6.0)
    if cancel.ok and cancel.value is not None:
        actions.click_source_point(ctx.session, cancel.value)
        ctx.invalidate_frame()
        ctx.sleep(0.6)

    # ---- 2. 点「托管」：已经托管（取消托管图标）就不点，免得点成取消 ----
    already = ctx.frame().find_image(T_FIGHT_AUTO_OFF)
    if not already.ok:
        auto = ctx.frame().find_image(T_FIGHT_AUTO)
        if auto.ok and auto.value is not None:
            actions.click_source_point(ctx.session, auto.value)
            ctx.invalidate_frame()
            ctx.sleep(0.6)

    # ---- 3. 等「点击空白区域到下一步」----
    ended = wait_for(ctx, ImageQuery(T_FIGHT_END), timeout=BATTLE_END_TIMEOUT)
    if not ended.ok or ended.value is None:
        return ActionResult.not_found(
            f"战斗 {BATTLE_END_TIMEOUT:.0f}s 内没结束", template=T_FIGHT_END
        )
    actions.click_source_point(ctx.session, ended.value)
    ctx.invalidate_frame()
    ctx.sleep(1.0)

    # ---- 4. 「下一步」条，最多点 5 次 ----
    for _ in range(5):
        nxt = ctx.frame().find_image(T_FIGHT_NEXT)
        if not nxt.ok or nxt.value is None:
            break
        actions.click_source_point(ctx.session, nxt.value)
        ctx.invalidate_frame()
        ctx.sleep(0.8)

    return ActionResult.success("战斗结束", action="sequence")


def pick_gift(ctx: RunContext) -> ActionResult[Any]:
    """赠礼第一屏：OCR 三个武将名 → 按优先表选一个点它。"""
    titles: list[str] = []
    for region in REWARD_TITLE_REGIONS:
        read = ctx.frame().read_text(region)
        titles.append(read.value if read.ok and read.value is not None else "")

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


def buy_ba_qing(ctx: RunContext) -> ActionResult[Any]:
    """巴清商店：按 TOKEN_PRIORITY 买**所有**够钱/在优先表里的信物，再退出。

    商品是随机的，一屏可能 0~3 个在优先表里；所以每买一个就重新 OCR 一次，
    最多买 3 个。钱不够（灰的）点了不弹「购买」，跳过继续看下一个。
    """
    bought: list[str] = []
    tried: set[int] = set()

    for _ in range(3):
        titles: list[str] = []
        for region in SHOP_TOKEN_TITLE_REGIONS:
            read = ctx.frame().read_text(region)
            titles.append(read.value if read.ok and read.value is not None else "")

        ranked = rank_token_slots(titles)
        candidate = next(((slot, name) for slot, name in ranked if slot not in tried), None)
        if candidate is None:
            break
        slot, name = candidate
        tried.add(slot)

        point = SHOP_TOKEN_POINTS[min(slot, len(SHOP_TOKEN_POINTS) - 1)]
        picked = actions.click_source_point(ctx.session, point)
        if not picked.ok:
            return picked
        ctx.invalidate_frame()
        ctx.sleep(0.6)

        # 钱够才会弹「购买」；钱不够/已售罄，点完什么都没发生。
        buy = ctx.frame().find_image(T_SHOP_BUY_TITLE)
        if not buy.ok:
            continue
        clicked = actions.click_source_point(ctx.session, SHOP_BUY_POINT)
        if not clicked.ok:
            return clicked
        bought.append(name)
        ctx.invalidate_frame()
        ctx.sleep(0.8)

    # ---- 退出商店：右上角箭头 → 是否结束购买？→ 确认 ----
    exit_btn = ctx.frame().find_image(T_SHOP_EXIT)
    if exit_btn.ok and exit_btn.value is not None:
        actions.click_source_point(ctx.session, exit_btn.value)
        ctx.invalidate_frame()
        ctx.sleep(0.7)

    prompt = ctx.frame().find_image(T_SHOP_EXIT_PROMPT)
    if prompt.ok:
        confirm = ctx.frame().find_image(T_SHOP_CONFIRM)
        if confirm.ok and confirm.value is not None:
            actions.click_source_point(ctx.session, confirm.value)
            ctx.invalidate_frame()
            ctx.sleep(0.8)

    return ActionResult.success(
        "巴清商店处理完成", action="sequence", bought=bought, count=len(bought)
    )


def choose_rest(ctx: RunContext) -> ActionResult[Any]:
    """休息：三个选项随便点一个，结束回地图。"""
    clicked = actions.click_source_point(ctx.session, REST_OPTION_POINT)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.9)
    return clicked.with_meta(point=(REST_OPTION_POINT.x, REST_OPTION_POINT.y))


def choose_pocket(ctx: RunContext) -> ActionResult[Any]:
    """锦囊三选一：随便点一个。可能还是这屏、可能到确认、也可能直接进战斗。"""
    point = random.choice(POCKET_OPTION_POINTS)
    clicked = actions.click_source_point(ctx.session, point)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.8)
    return clicked.with_meta(point=(point.x, point.y))


def confirm_pocket(ctx: RunContext) -> ActionResult[Any]:
    """锦囊确认页：点「确认」。"""
    return click_image(ctx, T_POCKET_CONFIRM, region=POCKET_CONFIRM_ROI, settle=1.0)


def enter_event(ctx: RunContext) -> ActionResult[Any]:
    """奇遇介绍页：点左边金色按钮（选择事件/选择武将，按边框认，不认文字）。"""
    return click_pattern_confirm(ctx, EVENT_ENTER_REGION, settle=0.8)


def choose_event_option(ctx: RunContext) -> ActionResult[Any]:
    """奇遇选择页：按妃妃优先级选一行；其他事件先选第一行。"""
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


def claim_reward(ctx: RunContext) -> ActionResult[Any]:
    """本局结束 → 点「领取奖励」。"""
    return click_image(ctx, T_CLAIM_REWARD, region=CLAIM_ROI, settle=1.2)


def close_congrats(ctx: RunContext) -> ActionResult[Any]:
    """「恭喜获得」浮层 → Esc 关闭，回到选将界面。"""
    return press(ctx, "esc", settle=1.0)
