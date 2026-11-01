"""千里单骑 · **局内**状态仓库。

> 先分清两个"仓库"：
> * :mod:`gamebot.state.store` 的 ``ctx.store(...)`` 是**跨运行**记忆（关掉再开还在）；
> * 这里的 ``store/`` 是**这一次运行内**的局内状态（铜币、每个武将拿过哪些赠礼），
>   挂在 ``ctx.blackboard`` 上，换一局就重置。
>
> 名字沿用"状态仓库"的说法，但生命周期是"一局"。

一个文件一件事：

* :mod:`.run`      —— ``BattleState`` + 从 ``ctx.blackboard`` 取/重置
* :mod:`.rewards`  —— 赠礼类别、武将优先表、选槽/选类别
* :mod:`.bag`      —— 铜币 OCR 区域与解析
"""

from __future__ import annotations

from .bag import COPPER_REGION, parse_copper_text, read_copper_coins, refresh_copper_coins
from .rewards import (
    DEFAULT_KEY_REWARDS,
    FALLBACK_KIND_ORDER,
    PRIORITY,
    TOKEN_PRIORITY,
    GeneralPriority,
    RewardKind,
    is_in_priority,
    parse_general_name,
    pick_reward_kind,
    pick_reward_slot,
    pick_token_slot,
    resolve_general_priority,
)
from .run import RUN_STATE_KEY, BattleState, get_run_state, reset_run_state

__all__ = [
    "COPPER_REGION",
    "DEFAULT_KEY_REWARDS",
    "FALLBACK_KIND_ORDER",
    "PRIORITY",
    "RUN_STATE_KEY",
    "TOKEN_PRIORITY",
    "BattleState",
    "GeneralPriority",
    "RewardKind",
    "get_run_state",
    "is_in_priority",
    "parse_copper_text",
    "parse_general_name",
    "pick_reward_kind",
    "pick_reward_slot",
    "pick_token_slot",
    "read_copper_coins",
    "refresh_copper_coins",
    "reset_run_state",
    "resolve_general_priority",
]
