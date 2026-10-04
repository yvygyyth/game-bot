"""流程层的状态机 —— 决定"下一步去哪个状态"。

.. note::
   **已被 ``Graph`` + ``GraphCursor`` 取代**，而且新的切分更清楚：
   本类把"蓝图"和"运行状态"混在一起（既是图又存计数），于是同一个图
   没法跑两次做对比，也没法序列化。新的做法是 ``Graph`` 只当蓝图、
   ``GraphCursor`` 持有 current / visits / EdgeStats。
   保留是为了不打断已有代码。

职责被刻意收窄到三件事：

1. 记住当前状态（以及每个状态访问了几次）；
2. 给定当前状态和一帧画面，挑出一条可用的转移；
3. 执行转移（改当前状态、记一笔）。

它**不截图、不执行步骤、不 sleep** —— 那些归引擎和上下文。
这样它就能被纯逻辑测试（喂假 Frame，断言挑出了哪条转移），
而流程脚本的 bug 大多就出在转移选择上。

选择算法::

    for t in transitions_from(current) 按 priority 降序:
        if 次数用尽 / 在冷却中: continue
        if t.guard is None: return t
        r = t.guard.run(frame)
        if r.ok: return t
        if r.status == ERROR: 记警告，继续尝试下一条
    return None      # 没有可用转移 -> 由引擎走"原地不动"分支
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..state.definition import StateId
from ..state.snapshot import StateChange, StateSnapshot
from ..types import ActionResult
from ..utils.logging import get_logger
from .definition import FlowDefinition
from .transition import Transition

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from ..state.store import Blackboard

log = get_logger("flow.machine")

__all__ = ["FlowMachine", "TransitionAttempt"]


@dataclass(slots=True)
class TransitionAttempt:
    """一次转移评估的痕迹。调试"为什么没走这条转移"时唯一有用的东西。"""

    transition: Transition
    accepted: bool
    reason: str = ""
    result: ActionResult[Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition": self.transition.display,
            "accepted": self.accepted,
            "reason": self.reason,
        }


@dataclass(slots=True)
class FlowMachine:
    """流程状态机。

    :param definition: 蓝图，运行期不变。
    """

    definition: FlowDefinition
    current: StateId = ""
    visits: dict[StateId, int] = field(default_factory=dict)
    times_fired: dict[int, int] = field(default_factory=dict)
    """转移索引 -> 已触发次数。"""

    last_fired_at: dict[int, float] = field(default_factory=dict)
    """转移索引 -> 上次触发时刻，用于 cooldown。"""

    history: list[StateChange] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.current:
            self.current = self.definition.initial

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """回到起点，清空计数（不产生 StateChange）。"""
        self.current = self.definition.initial
        self.visits.clear()
        self.times_fired.clear()
        self.last_fired_at.clear()
        self.history.clear()

    def visits_of(self, state_id: StateId) -> int:
        return self.visits.get(state_id, 0)

    def candidates(self, state_id: StateId | None = None) -> list[Transition]:
        """当前状态下按优先级排列的候选转移。"""
        return self.definition.transitions_from(state_id or self.current)

    def is_terminal(self, state_id: StateId | None = None) -> bool:
        sid = state_id or self.current
        if sid in self.definition.stop_states:
            return True
        definition = self.definition.state(sid)
        return bool(definition and definition.terminal)

    # ------------------------------------------------------------------ #
    # 选择
    # ------------------------------------------------------------------ #
    def _index_of(self, transition: Transition) -> int:
        """转移在 definition.transitions 中的下标（用于计数与冷却）。"""
        for index, candidate in enumerate(self.definition.transitions):
            if candidate is transition:
                return index
        return -1

    def is_available(self, transition: Transition, *, now: float) -> tuple[bool, str]:
        """次数 / 冷却是否允许这条转移。返回 ``(可用?, 不可用原因)``。"""
        index = self._index_of(transition)
        if transition.max_times and self.times_fired.get(index, 0) >= transition.max_times:
            return False, f"已达最大次数 {transition.max_times}"
        if transition.cooldown:
            last = self.last_fired_at.get(index)
            if last is not None and now - last < transition.cooldown:
                return False, f"冷却中（剩余 {transition.cooldown - (now - last):.2f}s）"
        return True, ""

    def select(
        self,
        snapshot: StateSnapshot,
        frame: Frame,
        *,
        now: float = 0.0,
        blackboard: Blackboard | None = None,
    ) -> ActionResult[Transition]:
        """挑一条可用的转移。

        :return: 挑到 ``success(value=Transition, attempts=[评估痕迹])``；
                 没有可用转移 ``not_found(attempts=[...])``。
                 注意：**"没有转移"不是错误** —— 很多状态下就是要原地重复做事
                 （比如战斗中反复点技能），引擎会据此继续执行当前节点。
        """
        raise NotImplementedError(
            "待实现: for t in candidates(): 检查 is_available -> 求 guard -> 返回首个通过的"
        )

    # ------------------------------------------------------------------ #
    # 执行转移
    # ------------------------------------------------------------------ #
    def apply(
        self,
        transition: Transition,
        *,
        now: float = 0.0,
        reason: str = "",
        confidence: float = 0.0,
        tick: int = 0,
    ) -> StateChange:
        """执行转移：改当前状态、累加计数、记一笔变更。

        :return: 本次变更记录（会同时进 ``self.history``）。
        """
        raise NotImplementedError(
            "待实现: 更新 times_fired / last_fired_at / visits -> 构造 StateChange -> 更新 current"
        )

    def record_change(self, change: StateChange) -> None:
        """直接记一笔变更（引擎在"状态被识别层改变但没走转移"时用）。"""
        self.history.append(change)
        self.visits[change.to_state] = self.visits.get(change.to_state, 0) + 1
        self.current = change.to_state

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "visits": dict(self.visits),
            "changes": [c.to_dict() for c in self.history],
        }

    def __repr__(self) -> str:
        return (
            f"FlowMachine(current={self.current!r}, "
            f"transitions={len(self.definition.transitions)}, changes={len(self.history)})"
        )
