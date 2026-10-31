"""局内一局的状态：铜币 + 每个武将拿过哪些赠礼。

和 :class:`gamebot.state.store.Store` 的区别见 ``store/__init__.py``：
这里是**一局内**的黑板状态，不是跨运行仓库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .rewards import RewardKind

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["RUN_STATE_KEY", "BattleState", "get_run_state", "reset_run_state"]

#: 在 ``ctx.blackboard`` 里的键。
RUN_STATE_KEY = "qianlidanqi.run_state"


@dataclass
class BattleState:
    """一局千里单骑跑出来的状态。"""

    copper_coins: int = 0
    general_rewards: dict[str, set[RewardKind]] = field(default_factory=dict)

    def has_general_reward(self, name: str, kind: RewardKind) -> bool:
        return kind in self.general_rewards.get(name, set())

    def mark_general_reward(self, name: str, kind: RewardKind) -> None:
        self.general_rewards.setdefault(name, set()).add(kind)

    def has_reward(self, kind: RewardKind) -> bool:
        return any(kind in kinds for kinds in self.general_rewards.values())

    def mark_reward(self, kind: RewardKind) -> None:
        self.mark_general_reward("", kind)


def get_run_state(ctx: RunContext) -> BattleState:
    """取这一局的状态；没有就新建一份放到黑板里。"""
    state = ctx.blackboard.get(RUN_STATE_KEY)
    if not isinstance(state, BattleState):
        state = BattleState()
        ctx.blackboard[RUN_STATE_KEY] = state
    return state


def reset_run_state(ctx: RunContext) -> BattleState:
    """开新一局：清空铜币和赠礼记录。"""
    state = BattleState()
    ctx.blackboard[RUN_STATE_KEY] = state
    return state
