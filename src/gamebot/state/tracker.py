"""状态层的跟踪层 —— 把"单帧定位结果"变成"持续的状态"。

:mod:`gamebot.state.page` 只回答"**这一帧**是哪个页面"，是无状态的纯匹配。
必须跨帧才能回答的三件事在这里：

* **连续几帧才算数**（``Page.min_stable_frames``）—— 过滤过场动画里的"闪现"。
  加载中的一帧恰好长得像主界面，是这类脚本最常见的误判来源。
* **在这个页面待了多久**（``Page.timeout``）—— 发现"卡住不动了"。
* **什么时候切换的**（:class:`PageChange`）—— 给流程层做转移判断和统计。

为什么和页面树分成两层：定位是**纯函数**（可测试、可重放），持续性是**状态机**
（需要历史）。混在一起的话，页面树就没法被多个运行共享，也没法序列化对比了。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..utils.logging import get_logger
from .page import UNKNOWN_PAGE, PageId, PageMatch, PageTree

log = get_logger("state.tracker")

__all__ = ["Blackboard", "PageChange", "PageState", "PageTracker"]


# --------------------------------------------------------------------------- #
# 共享黑板
# --------------------------------------------------------------------------- #
class Blackboard:
    """流程共享的键值存储。

    框架只提供容器，不解释内容 —— 脚本想存什么就存什么
    （今天刷了几次、上次体力值、连败计数）。比往步骤里塞上下文引用清晰得多。

    刻意不做类型约束、不做 schema 校验。需要结构化数据就约定 key 前缀
    （``"battle.retry_count"``），而不是改这个类。
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

    def __len__(self) -> int:
        return len(self._data)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def clear(self) -> None:
        self._data.clear()

    def __repr__(self) -> str:
        return f"Blackboard({self._data!r})"


# --------------------------------------------------------------------------- #
# 持续状态
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class PageState:
    """某个页面的**持续**状态（区别于 :class:`PageMatch` 的单帧观测）。"""

    id: PageId = UNKNOWN_PAGE
    path: tuple[PageId, ...] = ()
    overlays: tuple[PageId, ...] = ()
    confidence: float = 0.0
    hits: int = 1
    """连续命中帧数。"""

    required_hits: int = 1
    """需要连续命中多少帧才算确认进入（来自 ``Page.min_stable_frames``）。"""

    since: float = 0.0
    """**首次**进入该页面的时刻。"""

    observed_at: float = 0.0
    """最近一次看到的时刻。"""

    frame_id: int = -1
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def confirmed(self) -> bool:
        """是否已经"确认进入"（连续命中足够多帧）。"""
        return self.hits >= self.required_hits

    @property
    def is_unknown(self) -> bool:
        return self.id == UNKNOWN_PAGE

    @property
    def has_overlay(self) -> bool:
        return bool(self.overlays)

    def duration(self, now: float) -> float:
        """在该页面已经待了多久。"""
        return max(0.0, now - self.since)

    def is_(self, page_id: PageId) -> bool:
        """当前页面（或任一叠加层）是不是它。"""
        return page_id == self.id or page_id in self.overlays

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": list(self.path),
            "overlays": list(self.overlays),
            "confidence": round(self.confidence, 4),
            "hits": self.hits,
            "required_hits": self.required_hits,
            "confirmed": self.confirmed,
            "since": round(self.since, 4),
            "frame_id": self.frame_id,
            "values": self.values,
        }

    def __repr__(self) -> str:
        marks = []
        if not self.confirmed:
            marks.append(f"{self.hits}/{self.required_hits}")
        if self.overlays:
            marks.append(f"+{list(self.overlays)}")
        suffix = f" [{', '.join(marks)}]" if marks else ""
        return f"PageState({self.id!r}{suffix})"


@dataclass(slots=True)
class PageChange:
    """一次状态变更。

    两种形态，用 :attr:`is_stay` 区分：

    * **换页面**（``from_id != to_id``）—— 常规切换；
    * **原地变叠加层**（``from_id == to_id``，只有 ``overlays`` 变了）——
      "战斗页面突然弹出网络错误"，主页面没变但可用动作完全变了。

    第二种如果被忽略，脚本会在弹窗上继续点技能。
    """

    from_id: PageId
    to_id: PageId
    at: float
    tick: int = 0
    reason: str = ""
    from_path: tuple[PageId, ...] = ()
    to_path: tuple[PageId, ...] = ()
    from_overlays: tuple[PageId, ...] = ()
    to_overlays: tuple[PageId, ...] = ()
    confidence: float = 0.0
    elapsed_in_previous: float = 0.0
    """在旧页面待了多久。用来发现"某个页面卡了很久"。"""

    @property
    def is_stay(self) -> bool:
        return self.from_id == self.to_id

    @property
    def overlay_changed(self) -> bool:
        return self.from_overlays != self.to_overlays

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_id,
            "to": self.to_id,
            "from_overlays": list(self.from_overlays),
            "to_overlays": list(self.to_overlays),
            "at": round(self.at, 4),
            "tick": self.tick,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "elapsed_in_previous": round(self.elapsed_in_previous, 3),
        }

    def __repr__(self) -> str:
        arrow = "==" if self.is_stay else "->"
        extra = (
            f" overlay {list(self.from_overlays)} -> {list(self.to_overlays)}"
            if self.overlay_changed
            else ""
        )
        return f"PageChange({self.from_id!r} {arrow} {self.to_id!r}{extra})"


# --------------------------------------------------------------------------- #
# 跟踪器
# --------------------------------------------------------------------------- #
class PageTracker:
    """把连续的单帧定位结果维护成"当前页面 + 历史"。

    :param tree: 页面树。用来查 ``min_stable_frames``（"连续几帧才算数"）。
    :param history_size: 保留多少帧观测。缓存上限，别无限涨。
    """

    __slots__ = ("_changes", "_current", "_history", "_history_size", "_tick", "_tree")

    def __init__(self, tree: PageTree | None = None, *, history_size: int = 200) -> None:
        self._tree = tree
        self._current: PageState | None = None
        self._history: deque[PageState] = deque(maxlen=history_size)
        self._changes: list[PageChange] = []
        self._history_size = history_size
        self._tick = 0

    # ------------------------------------------------------------------ #
    # 当前状态
    # ------------------------------------------------------------------ #
    @property
    def current(self) -> PageState | None:
        return self._current

    @property
    def current_id(self) -> PageId:
        """当前页面 id；还没定位过时返回 ``UNKNOWN_PAGE``。"""
        return self._current.id if self._current is not None else UNKNOWN_PAGE

    @property
    def overlays(self) -> tuple[PageId, ...]:
        return self._current.overlays if self._current is not None else ()

    @property
    def confirmed(self) -> bool:
        """当前页面是否已"确认进入"。**流程层应该等它为真再动作。**"""
        return self._current.confirmed if self._current is not None else False

    def is_(self, page_id: PageId) -> bool:
        """当前页面（或任一叠加层）是不是它 —— 判断"弹窗在不在"用这个。

        还没定位过时，只有 ``UNKNOWN_PAGE`` 返回 True（和 :attr:`current_id` 一致）。
        """
        return self.current_id == page_id or page_id in self.overlays

    def is_current_exactly(self, page_id: PageId) -> bool:
        """只看主页面，不管叠加层。"""
        return self.current_id == page_id

    def set_initial(self, page_id: PageId = UNKNOWN_PAGE, *, now: float = 0.0) -> PageState:
        """设定起点，**不产生 PageChange**（初始化不是"切换"）。"""
        state = PageState(id=page_id, since=now, observed_at=now, hits=0, required_hits=1)
        self._current = state
        return state

    # ------------------------------------------------------------------ #
    # 更新
    # ------------------------------------------------------------------ #
    def update(
        self,
        match: PageMatch,
        *,
        now: float = 0.0,
        reason: str = "",
    ) -> PageChange | None:
        """用一帧的定位结果更新状态。

        :return: 换页面或叠加层变了时返回 :class:`PageChange`；
                 **第一次观测**（还没有前一个状态）和完全没变化时返回 None。

                 第一次不算"变化"：``PageChange`` 回答的是"从什么变成了什么"，
                 而上电时没有"从"。起点看 :attr:`current` 就好。
        """
        previous = self._current
        required = self._required_hits(match.id)

        if previous is not None and previous.id == match.id:
            overlays_before = previous.overlays
            previous.hits += 1
            previous.observed_at = now
            previous.confidence = match.confidence
            previous.frame_id = match.frame_id
            previous.values = dict(match.values)
            previous.overlays = match.overlays
            self._history.append(previous)

            if overlays_before == match.overlays:
                return None
            # 主页面没变但弹窗变了 —— 可用动作完全变了，必须让上层知道
            return self._record_change(
                from_id=previous.id,
                to_id=previous.id,
                from_path=previous.path,
                to_path=previous.path,
                from_overlays=overlays_before,
                to_overlays=match.overlays,
                confidence=match.confidence,
                now=now,
                reason=reason or "叠加层变化",
                elapsed=previous.duration(now),
            )

        state = PageState(
            id=match.id,
            path=match.path,
            overlays=match.overlays,
            confidence=match.confidence,
            hits=1,
            required_hits=required,
            since=now,
            observed_at=now,
            frame_id=match.frame_id,
            values=dict(match.values),
        )
        self._current = state
        self._history.append(state)

        if previous is None:
            return None  # 第一次观测：这是基准，不是"切换"

        return self._record_change(
            from_id=previous.id,
            to_id=state.id,
            from_path=previous.path,
            to_path=state.path,
            from_overlays=previous.overlays,
            to_overlays=state.overlays,
            confidence=state.confidence,
            now=now,
            reason=reason,
            elapsed=previous.duration(now),
        )

    def _required_hits(self, page_id: PageId) -> int:
        if self._tree is None:
            return 1
        page = self._tree.get(page_id)
        return max(1, page.min_stable_frames) if page is not None else 1

    def _record_change(
        self,
        *,
        from_id: PageId,
        to_id: PageId,
        from_path: tuple[PageId, ...],
        to_path: tuple[PageId, ...],
        from_overlays: tuple[PageId, ...],
        to_overlays: tuple[PageId, ...],
        confidence: float,
        now: float,
        reason: str,
        elapsed: float,
    ) -> PageChange:
        """记录一次变更。

        刻意用**显式参数**而不是传两个 ``PageState``：同页面只换叠加层时
        两个状态是同一个对象，传引用会让 ``overlay_changed`` 永远比出 False
        （之前就是这么写错的）。
        """
        change = PageChange(
            from_id=from_id,
            to_id=to_id,
            at=now,
            tick=self._tick,
            reason=reason,
            from_path=from_path,
            to_path=to_path,
            from_overlays=from_overlays,
            to_overlays=to_overlays,
            confidence=confidence,
            elapsed_in_previous=elapsed,
        )
        self._changes.append(change)
        return change

    # ------------------------------------------------------------------ #
    # 历史与统计
    # ------------------------------------------------------------------ #
    @property
    def changes(self) -> list[PageChange]:
        return list(self._changes)

    @property
    def recent(self) -> list[PageState]:
        return list(self._history)

    @property
    def tick(self) -> int:
        return self._tick

    def advance_tick(self) -> int:
        self._tick += 1
        return self._tick

    def elapsed(self, now: float) -> float:
        """当前页面已经持续了多久（秒）。用于超时判断。"""
        return self._current.duration(now) if self._current is not None else 0.0

    def delayed(self, now: float) -> bool:
        """当前页面是否已超过它自己声明的 ``timeout``。

        页面没声明 ``timeout`` 时永远返回 False。
        """
        if self._current is None or self._tree is None:
            return False
        page = self._tree.get(self._current.id)
        if page is None or page.timeout is None:
            return False
        return self._current.duration(now) >= page.timeout

    def change_count(self, page_id: PageId | None = None) -> int:
        """发生过多少次切换；给了 ``page_id`` 则只数进入该页面的次数。"""
        if page_id is None:
            return len(self._changes)
        return sum(1 for c in self._changes if c.to_id == page_id)

    def reset(self) -> None:
        """清空全部状态（新一轮运行前调用）。"""
        self._current = None
        self._history.clear()
        self._changes.clear()
        self._tick = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self._current.to_dict() if self._current else None,
            "tick": self._tick,
            "changes": [c.to_dict() for c in self._changes],
        }

    def __repr__(self) -> str:
        return (
            f"PageTracker(current={self.current_id!r}, "
            f"changes={len(self._changes)}, tick={self._tick})"
        )
