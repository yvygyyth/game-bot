"""状态层里的共享黑板 —— 脚本自己存东西的地方。

框架只提供容器，不解释内容。这里**刻意**没有 schema、没有类型约束：
脚本想存"今天刷了几次""上次读到的体力值""连败计数"，随手塞就行。
需要结构化数据就约定 key 前缀（``"battle.retry_count"``），而不是改这个类。

和跟踪层的区别：``PageTracker`` 里的东西是**框架拥有**的（当前页面、变更历史），
所有状态变更都必须经过它；黑板是**业务拥有**的，框架只负责让步骤之间能传数据。

真正需要 :class:`Blackboard` 的地方比想象中少 —— 大多数"要在步骤之间传的东西"
要么是页面状态（跟踪层管），要么是配置（只读）。它主要服务于
"统计跨越多轮的计数"这类需求。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

__all__ = ["Blackboard"]


class Blackboard:
    """流程共享的键值存储。"""

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
