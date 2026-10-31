"""局内：地图选节点 → 战斗 → 赠礼 → 回地图 / 本局结束。

战斗是**全程托管**：和竞技场一样先点「取消」关掉换牌弹窗，再点「托管」，
然后等「点击空白区域到下一步」。不做出牌/取消等战斗操作。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.atomic.query import ImageQuery
from gamebot.execution.builtins import click_image, press, wait_for
from gamebot.types import ActionResult, Point, Region

from ..pages import CLAIM_ROI, NODE_REGION, START_BATTLE_ROI
from ..store import (
    RewardKind,
    get_run_state,
    parse_general_name,
    pick_reward_kind,
    pick_reward_slot,
    resolve_general_priority,
)
from ..templates import (
    T_CLAIM_REWARD,
    T_FIGHT_AUTO,
    T_FIGHT_CANCEL,
    T_FIGHT_END,
    T_FIGHT_NEXT,
    T_NODE_BATTLE,
    T_REWARD_BUFF,
    T_REWARD_CARD,
    T_REWARD_HELP,
    T_REWARD_JOINT,
    T_REWARD_TOKEN,
    T_START_BATTLE,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "BATTLE_END_TIMEOUT",
    "PENDING_GENERAL_KEY",
    "choose_node",
    "claim_reward",
    "close_congrats",
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
    Region(390, 1075, 330, 55),
    Region(1060, 1075, 340, 55),
    Region(1780, 1075, 340, 55),
)

#: 三个标题的中心（OCR 不可用时默认点第一个）。
REWARD_SLOT_POINTS = (Point(555, 1105), Point(1230, 1105), Point(1950, 1105))

#: 地图上节点的匹配阈值。
NODE_CONFIDENCE = 0.9

#: 战斗最长等多久（秒）。自动战斗一局可能几分钟。
BATTLE_END_TIMEOUT = 1200.0


def choose_node(ctx: RunContext) -> ActionResult[Any]:
    """地图上找一个战斗节点（剑）并点它。"""
    found = ctx.frame().find_all_images(
        T_NODE_BATTLE,
        region=NODE_REGION,
        confidence=NODE_CONFIDENCE,
        max_count=10,
        min_distance=80,
    )
    if not found.ok or not found.value:
        return ActionResult.not_found(
            "地图上没有可点的战斗节点（商店/事件节点后续再支持）",
            template=T_NODE_BATTLE,
        )
    point = min(found.value, key=lambda p: p.y)
    clicked = actions.click_source_point(ctx.session, point)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(0.8)
    return clicked.with_meta(point=(point.x, point.y), count=len(found.value))


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

    # ---- 2. 点「托管」----
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


def claim_reward(ctx: RunContext) -> ActionResult[Any]:
    """本局结束 → 点「领取奖励」。"""
    return click_image(ctx, T_CLAIM_REWARD, region=CLAIM_ROI, settle=1.2)


def close_congrats(ctx: RunContext) -> ActionResult[Any]:
    """「恭喜获得」浮层 → Esc 关闭，回到选将界面。"""
    return press(ctx, "esc", settle=1.0)
