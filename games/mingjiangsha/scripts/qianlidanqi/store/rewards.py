"""赠礼类别、武将优先表、选槽/选类别。

全部是**纯函数 + 数据**，不碰画面、不碰 ctx —— 选哪一个由这里的表决定，
步骤只负责"把 OCR 到的标题/可用图标交给它"。

## 选法（和老脚本一致）

1. 先按 :data:`PRIORITY` 表：本屏有该武将，且它的关键奖励还没拿全 → 选它；
2. 否则在"仍有未拿关键奖励"的槽位里按 :data:`FALLBACK_KIND_ORDER` 回退；
3. 都拿完了就靠左选第一个（避免卡在选将界面）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

__all__ = [
    "DEFAULT_KEY_REWARDS",
    "FALLBACK_KIND_ORDER",
    "PRIORITY",
    "TOKEN_PRIORITY",
    "GeneralPriority",
    "RewardKind",
    "is_in_priority",
    "parse_general_name",
    "pick_reward_kind",
    "pick_reward_slot",
    "pick_token_slot",
    "rank_token_slots",
    "resolve_general_priority",
]


class RewardKind(StrEnum):
    """赠礼内可选奖励类别。"""

    TOKEN = "信物"
    JOINT = "共同作战"
    HELP = "资助"
    BUFF = "驰援"
    CARD = "武将牌"


@dataclass(frozen=True)
class GeneralPriority:
    """优先表一行：武将名 + 关键奖励（越靠前越优先）。"""

    name: str
    key_rewards: tuple[RewardKind, ...]


#: 武将优先表（越靠前越优先；按需改表即可）。
PRIORITY: list[GeneralPriority] = [
    GeneralPriority("王异", (RewardKind.TOKEN,)),
    GeneralPriority("荀彧", (RewardKind.TOKEN,)),
    GeneralPriority("甘宁", (RewardKind.TOKEN, RewardKind.BUFF)),
    GeneralPriority("刘表", (RewardKind.TOKEN, RewardKind.BUFF)),
    GeneralPriority("萧何", (RewardKind.TOKEN,)),
    GeneralPriority("曹操", (RewardKind.TOKEN,)),
    GeneralPriority("韩信", (RewardKind.TOKEN,)),
    GeneralPriority("吕布", (RewardKind.TOKEN,)),
    GeneralPriority("马超", (RewardKind.BUFF,)),
    GeneralPriority("吕雉", (RewardKind.TOKEN,)),
    GeneralPriority("关羽", (RewardKind.TOKEN,)),
    GeneralPriority("左慈", (RewardKind.TOKEN,)),
    GeneralPriority("周勃", (RewardKind.TOKEN,)),
    GeneralPriority("鲁肃", (RewardKind.HELP, RewardKind.BUFF)),
    GeneralPriority("庞统", (RewardKind.TOKEN,)),
    GeneralPriority("华佗", (RewardKind.TOKEN,)),
]

#: 优先表里没有的武将：默认关键奖励序（也用作全局类别回退）。
DEFAULT_KEY_REWARDS: tuple[RewardKind, ...] = (
    RewardKind.BUFF,
    RewardKind.HELP,
    RewardKind.CARD,
    RewardKind.JOINT,
    RewardKind.TOKEN,
)

#: 主路径都不满足时按类别回退（与表外武将默认一致）。
FALLBACK_KIND_ORDER: tuple[RewardKind, ...] = DEFAULT_KEY_REWARDS

#: 巴清商店关键信物（越靠前越优先；店里有才会出现）。
TOKEN_PRIORITY: list[str] = [
    "麻衣",
    "熏炉",
    "行囊",
    "铃铛",
    "典籍",
    "典论",
    "《孟德新书》",
    "象棋",
    "《九章律》",
    "鸠杯",
    "飞将翎",
    "纱锦囊",
    "皇后之玺",
    "薄曲",
    "青囊书",
    "美人草",
    "凤毛",
    "将印",
]


class _RewardBag(Protocol):
    def has_general_reward(self, name: str, kind: RewardKind) -> bool: ...
    def has_reward(self, kind: RewardKind) -> bool: ...


def parse_general_name(ocr_text: str) -> str:
    """从 OCR 文案取出武将名（去掉「赠礼」等后缀）。"""
    text = (ocr_text or "").strip()
    if not text or text == "(空)":
        return ""
    for suffix in ("赠礼", "贈禮"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def _token_match(text: str, name: str) -> bool:
    """OCR 经常只读出半截（飞仙髻→飞、白狼之魔→白狼）。"""
    if not text or not name:
        return False
    if name in text:
        return True
    return len(text) >= 2 and text in name


def rank_token_slots(
    titles: list[str] | tuple[str, ...],
    priority: list[str] | None = None,
) -> list[tuple[int, str]]:
    """按 :data:`TOKEN_PRIORITY` 排序本屏可买的信物：``[(槽位, 命中名), ...]``。

    只返回在优先表里的；OCR 半截也算（行囊 / 白狼 这种）。
    """
    table = priority if priority is not None else TOKEN_PRIORITY
    ranked: list[tuple[int, int, str]] = []
    for slot, raw in enumerate(titles):
        text = (raw or "").strip()
        if not text:
            continue
        for order, name in enumerate(table):
            if _token_match(text, name):
                ranked.append((order, slot, name))
                break
    ranked.sort()
    return [(slot, name) for _, slot, name in ranked]


def pick_token_slot(
    titles: list[str] | tuple[str, ...],
    priority: list[str] | None = None,
) -> int | None:
    """按 :data:`TOKEN_PRIORITY` 找本屏第一个命中的信物槽位；都没有返回 None。"""
    ranked = rank_token_slots(titles, priority)
    return ranked[0][0] if ranked else None


def _entry_by_name(name: str) -> GeneralPriority | None:
    if not name:
        return None
    for entry in PRIORITY:
        if entry.name == name:
            return entry
    return None


def is_in_priority(name: str) -> bool:
    """是否在 :data:`PRIORITY` 配置表内。"""
    return _entry_by_name(name) is not None


def resolve_general_priority(name: str) -> GeneralPriority:
    """查优先表；不在表内则用 :data:`DEFAULT_KEY_REWARDS`。"""
    entry = _entry_by_name(name)
    if entry is not None:
        return entry
    return GeneralPriority(name=name or "未知", key_rewards=DEFAULT_KEY_REWARDS)


def _needed_key_rewards(entry: GeneralPriority, state: _RewardBag) -> list[RewardKind]:
    return [
        kind for kind in entry.key_rewards if not state.has_general_reward(entry.name, kind)
    ]


def _kind_already_have(
    state: _RewardBag,
    entry: GeneralPriority | None,
    kind: RewardKind,
) -> bool:
    """按武将分别判断该类奖励是否已拿。"""
    if entry is None or not entry.name:
        return False
    return state.has_general_reward(entry.name, kind)


def _fallback_kind_rank(entry: GeneralPriority | None) -> int:
    """回退用：关键奖励里最靠前的类别秩；无关键奖励最差。"""
    order = FALLBACK_KIND_ORDER
    if entry is None or not entry.key_rewards:
        return len(order)
    best = len(order)
    for kind in entry.key_rewards:
        try:
            best = min(best, order.index(kind))
        except ValueError:
            continue
    return best


def pick_reward_slot(
    titles: list[str] | tuple[str, ...],
    state: _RewardBag,
) -> int:
    """根据 OCR 标题与局内状态选出要点的槽位下标（0-based）。

    1. 按 :data:`PRIORITY` 表顺序：本屏有该武将，且关键奖励尚未全部拿完 → 选他；
    2. 否则在「仍有未拿关键奖励」的槽位里按 :data:`FALLBACK_KIND_ORDER` 回退；
       都拿完则靠左。
    """
    names = [parse_general_name(t) for t in titles]
    if not names:
        return 0

    for entry in PRIORITY:
        if entry.name not in names:
            continue
        if _needed_key_rewards(entry, state):
            return names.index(entry.name)

    best_slot = 0
    best_key = (1, _fallback_kind_rank(None), 0)  # (已拿完?, 类别秩, 槽位)
    for slot, name in enumerate(names):
        entry = resolve_general_priority(name) if name else None
        needed = _needed_key_rewards(entry, state) if entry is not None else []
        exhausted = 0 if needed else 1
        key = (exhausted, _fallback_kind_rank(entry), slot)
        if key < best_key:
            best_key = key
            best_slot = slot
    return best_slot


def pick_reward_kind(
    available: set[RewardKind] | list[RewardKind] | tuple[RewardKind, ...],
    entry: GeneralPriority | None,
    state: _RewardBag,
) -> RewardKind | None:
    """在本屏可选项里选出要拿的奖励类别。

    顺序：当前武将 ``key_rewards``（优先未拿到的）→ :data:`FALLBACK_KIND_ORDER`。
    """
    avail = set(available)
    if not avail:
        return None

    order: list[RewardKind] = []
    if entry is not None:
        order.extend(entry.key_rewards)
    for kind in FALLBACK_KIND_ORDER:
        if kind not in order:
            order.append(kind)

    for kind in order:
        if kind in avail and not _kind_already_have(state, entry, kind):
            return kind
    for kind in order:
        if kind in avail:
            return kind
    return None
