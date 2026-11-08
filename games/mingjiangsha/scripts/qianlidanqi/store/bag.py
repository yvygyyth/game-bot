"""局内背包读数：铜币区域 OCR → 整数。

OCR 是**可选**的（见 :mod:`gamebot.vision.text`）：没装 OCR 时
:func:`read_copper_coins` 返回 ``None``，调用方按 0 处理，不会炸。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from gamebot.types import Region

from .run import get_run_state

if TYPE_CHECKING:
    from gamebot.context import RunContext

    from .run import BattleState

__all__ = [
    "COPPER_REGION",
    "parse_copper_text",
    "read_copper_coins",
    "refresh_copper_coins",
]

#: 铜币数值区域（源坐标 2560x1369）。
COPPER_REGION = Region(2250, 73, 110, 70)


def parse_copper_text(text: str) -> int | None:
    """从 OCR 文案解析铜币整数；失败返回 None。"""
    raw = (text or "").strip()
    if not raw:
        return None
    cleaned = (
        raw.replace(",", "")
        .replace("，", "")
        .replace(" ", "")
        .replace("O", "0")
        .replace("o", "0")
        .replace("l", "1")
        .replace("I", "1")
    )
    match = re.search(r"\d+", cleaned)
    if not match:
        return None
    return int(match.group(0))


def read_copper_coins(ctx: RunContext) -> int | None:
    """截铜币区域 OCR；没装 OCR / 认不出来返回 None。"""
    result = ctx.frame().read_text(COPPER_REGION)
    if not result.ok or result.value is None:
        return None
    return parse_copper_text(result.value)


def refresh_copper_coins(
    ctx: RunContext, state: BattleState | None = None
) -> int | None:
    """OCR 并写回 ``BattleState.copper_coins``；失败不改原值。"""
    amount = read_copper_coins(ctx)
    if amount is None:
        return None
    target = state if state is not None else get_run_state(ctx)
    target.copper_coins = amount
    return amount
