"""状态层的识别器 —— 把一帧画面变成"现在是什么状态"。

识别流程（每个 tick 一次）::

    1. 按 priority 从高到低遍历所有 StateDefinition
    2. 对每个定义：
       a. 先求 exclude —— 命中任一则直接否决（先否决，省算力）
       b. 再求 queries —— 默认 AND（全部命中才算）
       c. 命中则算一个 confidence（子结果 score 的均值；纯布尔查询按 1.0）
    3. 取最高 priority 的命中项作为本帧结果
    4. 一个都没有 → UNKNOWN_STATE
    5. 连续命中计数：和上一帧同一状态则 hits+1，否则重置为 1

为什么要 ``min_stable_frames``：游戏里到处是"闪现"—— 过场动画里恰好出现
半个按钮、加载时残留上一帧。要求连续 N 帧命中能过滤掉绝大部分误判，
代价只是多等 N 个 tick。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from ..types import ActionResult
from ..utils.logging import get_logger
from .definition import StateDefinition, StateId
from .snapshot import UNKNOWN_STATE, StateSnapshot

if TYPE_CHECKING:
    from ..atomic.frame import Frame

log = get_logger("state.detector")

__all__ = ["StateDetector", "StateMatch"]


class StateMatch:
    """一个状态定义的匹配结果（内部用，不对外暴露为 API）。"""

    __slots__ = ("confidence", "definition", "message", "values")

    def __init__(
        self,
        definition: StateDefinition,
        confidence: float = 1.0,
        values: dict[str, Any] | None = None,
        message: str = "",
    ) -> None:
        self.definition = definition
        self.confidence = confidence
        self.values = values or {}
        self.message = message

    def __repr__(self) -> str:
        return f"StateMatch({self.definition.id!r}, confidence={self.confidence:.3f})"


class StateDetector:
    """状态识别器。

    :param definitions: 状态定义集合，按 ``priority`` 自动降序排列。
    :param max_candidates: 一帧最多评估多少个状态定义（性能保护，按优先级取前 N）。
    """

    def __init__(
        self,
        definitions: Iterable[StateDefinition],
        *,
        max_candidates: int = 0,
    ) -> None:
        self.definitions = sorted(definitions, key=lambda d: d.priority, reverse=True)
        self.max_candidates = max_candidates
        self._by_id = {d.id: d for d in self.definitions}
        self._last_id: str = ""
        self._hits: int = 0
        self._since: float = 0.0

    # ------------------------------------------------------------------ #
    # 查询接口
    # ------------------------------------------------------------------ #
    def get(self, state_id: str) -> StateDefinition | None:
        return self._by_id.get(state_id)

    @property
    def ids(self) -> list[str]:
        return [d.id for d in self.definitions]

    # ------------------------------------------------------------------ #
    # 识别
    # ------------------------------------------------------------------ #
    def detect(self, frame: Frame, *, now: float | None = None) -> ActionResult[StateSnapshot]:
        """识别当前状态。

        :return: ``success(value=StateSnapshot)``。**即使什么都没认出来也是 success**，
                 value 是 ``UNKNOWN_STATE`` 的快照 —— "未知"是一个有效状态，
                 不是错误。这一点和原子层的 not_found 语义不同，别混。
        """
        raise NotImplementedError(
            "待实现: 遍历候选定义 -> _evaluate -> 取最高优先级 -> _track(连续命中)"
        )

    def detect_all(self, frame: Frame) -> ActionResult[list[StateSnapshot]]:
        """返回**所有**命中的状态，按优先级降序。

        用途：调试"为什么识别成了 A 而不是 B"（两个都命中时看优先级），
        或者需要同时感知多个并存信息（如"战斗中 + 有弹窗"）。
        """
        raise NotImplementedError("待实现：返回全部命中，不覆盖 _last_id 计数")

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _evaluate(self, frame: Frame, definition: StateDefinition) -> StateMatch | None:
        """评估单个状态定义。"""
        raise NotImplementedError(
            "待实现: exclude 命中 -> None; queries 用 find_all_of 全中 -> StateMatch"
        )

    def _confidence_of(self, results: Sequence[ActionResult[Any]]) -> float:
        """子结果置信度取均值。没有 score 的按 1.0 计。"""
        if not results:
            return 1.0
        scores: list[float] = []
        for result in results:
            if not result.ok:
                continue
            raw = result.meta.get("score", result.meta.get("confidence"))
            scores.append(float(raw) if isinstance(raw, (int, float)) else 1.0)
        return sum(scores) / len(scores) if scores else 1.0

    def _track(self, state_id: str, confidence: float, frame: Frame, now: float) -> StateSnapshot:
        """维护"连续命中"计数并生成快照。"""
        raise NotImplementedError(
            "待实现: 同 id -> hits+1; 不同 id -> hits=1, since=now; 再拼 StateSnapshot"
        )

    def reset(self) -> None:
        """清空连续命中状态（流程重启时调用）。"""
        self._last_id = ""
        self._hits = 0
        self._since = 0.0

    def snapshot_of(self, state_id: StateId = UNKNOWN_STATE, *, now: float = 0.0) -> StateSnapshot:
        """直接构造一个快照（初始化时给流程一个起点用）。"""
        return StateSnapshot(id=state_id, confidence=0.0, observed_at=now, since=now, hits=0)
