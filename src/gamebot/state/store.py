"""状态层的存储 —— 当前状态、历史、以及流程共享的黑板。

两件东西分开，因为它们的生命周期完全不同：

* ``StateStore``  —— **框架拥有**。当前状态是什么、这轮切换了几次、某状态待了多久。
  所有状态变更都必须经过它，否则日志和统计就对不上。
* ``Blackboard``  —— **业务拥有**。脚本想存什么就存什么（今天刷了几次、上次体力值、
  连败计数）。框架只提供容器，不解释内容。

为什么需要黑板：流程里的步骤之间要传数据（"读取到体力值 30，下一轮决定吃不吃药"），
但步骤是独立对象，互相不认识。用一个共享 dict 是最简单可靠的解 —— 比往步骤里塞
上下文引用清晰得多。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Mapping
from typing import Any

from ..utils.logging import get_logger
from .definition import StateId
from .snapshot import UNKNOWN_STATE, StateChange, StateSnapshot

log = get_logger("state.store")

__all__ = ["Blackboard", "StateStore"]


class Blackboard:
    """流程共享的键值存储。

    刻意不做类型约束、不做 schema 校验 —— 它就是个带日志的 dict。
    需要结构化数据的话，约定 key 前缀（``"battle.retry_count"``）而不是改这个类。
    """

    __slots__ = ("_data",)

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, **values: Any) -> None:
        self._data.update(values)

    def bump(self, key: str, delta: int = 1, *, start: int = 0) -> int:
        """计数器自增，返回新值。统计"刷了多少次"最常用。"""
        current = self._data.get(key, start)
        value = (current if isinstance(current, int) else start) + delta
        self._data[key] = value
        return value

    def pop(self, key: str, default: Any = None) -> Any:
        return self._data.pop(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"Blackboard({self._data!r})"


class StateStore:
    """当前状态 + 变更历史。

    :param history_size: 保留多少条变更记录。缓存上限，别无限涨。
    """

    __slots__ = ("_changes", "_current", "_history", "_history_size", "_tick")

    def __init__(self, history_size: int = 200) -> None:
        self._current: StateSnapshot | None = None
        self._changes: list[StateChange] = []
        self._history_size = history_size
        self._tick = 0
        self._history: deque[StateSnapshot] = deque(maxlen=history_size)

    # ------------------------------------------------------------------ #
    # 当前状态
    # ------------------------------------------------------------------ #
    @property
    def current(self) -> StateSnapshot | None:
        return self._current

    @property
    def current_id(self) -> StateId:
        """当前状态 id；还没识别过时返回 ``UNKNOWN_STATE``。"""
        return self._current.id if self._current is not None else UNKNOWN_STATE

    def is_(self, state_id: StateId) -> bool:
        return self.current_id == state_id

    def set_initial(self, state_id: StateId = UNKNOWN_STATE, *, now: float = 0.0) -> StateSnapshot:
        """设定起点状态，**不产生 StateChange**（初始化不是"切换"）。"""
        snapshot = StateSnapshot(id=state_id, confidence=0.0, observed_at=now, since=now, hits=0)
        self._current = snapshot
        return snapshot

    # ------------------------------------------------------------------ #
    # 更新
    # ------------------------------------------------------------------ #
    def update(
        self,
        snapshot: StateSnapshot,
        *,
        reason: str = "",
        tick: int | None = None,
    ) -> StateChange | None:
        """用新观测更新当前状态。

        :return: 状态**发生了变化**时返回 ``StateChange``；同一状态则返回 None
                 （但内部会刷新 hits / observed_at）。
        """
        raise NotImplementedError(
            "待实现: 同 id -> 更新 current 的 hits/confidence/observed_at 并返回 None; "
            "不同 id -> 生成 StateChange 入 history 与 changes"
        )

    # ------------------------------------------------------------------ #
    # 历史查询
    # ------------------------------------------------------------------ #
    @property
    def changes(self) -> list[StateChange]:
        return list(self._changes)

    @property
    def recent(self) -> list[StateSnapshot]:
        return list(self._history)

    @property
    def tick(self) -> int:
        return self._tick

    def advance_tick(self) -> int:
        self._tick += 1
        return self._tick

    def elapsed_in_state(self, now: float) -> float:
        """当前状态已经持续了多久（秒）。用于超时判断。"""
        if self._current is None:
            return 0.0
        return self._current.duration(now)

    def change_count(self, state_id: StateId | None = None) -> int:
        """发生过多少次切换；给了 ``state_id`` 则只数进入该状态的次数。"""
        if state_id is None:
            return len(self._changes)
        return sum(1 for c in self._changes if c.to_state == state_id)

    def reset(self) -> None:
        self._current = None
        self._changes.clear()
        self._history.clear()
        self._tick = 0

    def __repr__(self) -> str:
        return (
            f"StateStore(current={self.current_id!r}, "
            f"changes={len(self._changes)}, tick={self._tick})"
        )
