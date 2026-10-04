"""状态层的"快照"与"变更"对象。

状态层对外只吐这两种值对象，流程层据此决策：

* ``StateSnapshot``  —— 当前（或曾）处于某状态的证据：什么时候开始的、
  连续命中几帧、置信度多少、附加数据。
* ``StateChange``    —— 一次状态切换的事实记录，用于日志、统计、回放。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .definition import StateId

__all__ = ["UNKNOWN_STATE", "StateChange", "StateSnapshot"]

UNKNOWN_STATE: StateId = "unknown"
"""约定俗成的"啥也没认出来"状态。所有流程都应该显式定义它的应对方式，
而不是靠兜底代码 —— 认不出来是最常见的真实情况。"""


@dataclass(slots=True)
class StateSnapshot:
    """某状态的一次观测。"""

    id: StateId
    confidence: float = 0.0
    observed_at: float = 0.0
    """本次观测时间（``perf_counter``）。"""

    since: float = 0.0
    """**首次**进入该状态的时间。持续时长 = now - since。"""

    hits: int = 1
    """连续命中次数。配合 ``min_stable_frames`` 判定是否算"稳定进入"。"""

    frame_id: int = -1
    """产生该观测的帧编号，便于和截图存档对上。"""

    values: dict[str, Any] = field(default_factory=dict)
    """识别过程中顺带读到的数据，如 ``{"stamina": 42, "level": "3-2"}``。"""

    message: str = ""

    @property
    def stable(self) -> bool:
        """是否已连续命中（调用方通常还会再和 definition.min_stable_frames 比）。"""
        return self.hits > 1

    def duration(self, now: float) -> float:
        return max(0.0, now - self.since)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "confidence": round(self.confidence, 4),
            "hits": self.hits,
            "since": round(self.since, 4),
            "frame_id": self.frame_id,
            "values": self.values,
            "message": self.message,
        }

    def __repr__(self) -> str:
        return (
            f"StateSnapshot({self.id!r}, confidence={self.confidence:.3f}, "
            f"hits={self.hits}, values={self.values!r})"
        )


@dataclass(slots=True)
class StateChange:
    """一次状态切换。"""

    from_state: StateId
    to_state: StateId
    at: float
    """切换时刻（``perf_counter``）。"""

    reason: str = ""
    """为什么切：``"检测到结算画面"`` / ``"转移规则 #3"`` / ``"超时兜底"``。"""

    confidence: float = 0.0
    elapsed_in_previous: float = 0.0
    """在旧状态待了多久。用来发现"某个状态卡了很久"这类问题。"""

    tick: int = 0

    @property
    def is_initial(self) -> bool:
        return self.from_state == ""

    @property
    def is_stay(self) -> bool:
        return self.from_state == self.to_state

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_state,
            "to": self.to_state,
            "at": round(self.at, 4),
            "tick": self.tick,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "elapsed_in_previous": round(self.elapsed_in_previous, 3),
        }

    def __repr__(self) -> str:
        arrow = "->" if not self.is_stay else "=="
        return f"StateChange({self.from_state!r} {arrow} {self.to_state!r}, reason={self.reason!r})"
