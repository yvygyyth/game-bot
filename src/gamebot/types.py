"""L0 类型层 —— 整个框架的公共语言。

设计约束（重要）：

1. **零第三方依赖**。任何层都可以安全导入，不会拉起 numpy / opencv / mss。
2. 只放"值对象"和"结果对象"，不放策略、不放 IO、不放外部状态。
3. 所有坐标默认使用 **源分辨率**（即截图出来的真实像素坐标系）。
   逻辑分辨率（游戏内坐标 / 设计分辨率）与源分辨率之间的换算由 L1 的
   ``CoordinateMapper`` 负责，本层不掺和。

对应设计文档《零、基础设施》。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Generic, TypeVar

__all__ = [
    "ActionResult",
    "ActionStatus",
    "Point",
    "Region",
]

T = TypeVar("T")
U = TypeVar("U")


# --------------------------------------------------------------------------- #
# ActionStatus —— 原子方法的四种终态
# --------------------------------------------------------------------------- #
class ActionStatus(StrEnum):
    """原子方法的结果状态。

    只有四种。任何"看起来更细"的语义都应该通过 ``message`` / ``meta`` 表达，
    而不是新增枚举值 —— 因为上层（执行层 / 流程层）只对这四种做分支。

    用 ``StrEnum``：日志里、JSON 里、比较时都直接是 ``success`` / ``not_found``，
    不需要到处写 ``.value``。
    """

    SUCCESS = "success"
    """达到目的。value 一定有意义。"""

    NOT_FOUND = "not_found"
    """没找到 / 条件不满足。属于"正常但没命中"，通常意味着该重试或换策略。"""

    TIMEOUT = "timeout"
    """在给定时间内没等到。等待类方法的专属终态。"""

    ERROR = "error"
    """异常：后端崩了、模板文件缺失、参数非法……需要人介入。"""

    @property
    def ok(self) -> bool:
        return self is ActionStatus.SUCCESS

    def __str__(self) -> str:  # 日志里好看一点
        return self.value


# --------------------------------------------------------------------------- #
# ActionResult —— 所有原子方法的统一返回
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ActionResult(Generic[T]):
    """统一返回信封。

    四种典型构造方式::

        ActionResult.success(value=Point(100, 200), confidence=0.93)
        ActionResult.not_found("attack.png 未命中")
        ActionResult.timeout("等待 victory.png 超时", waited=60.0)
        ActionResult.error("adb 连接断开", exc=exc)

    约定：

    * ``value``  —— 主返回值。成功时必有意义，失败时通常为 None。
    * ``message`` —— 给人看的说明。失败时必填。
    * ``elapsed`` —— 该原子方法自身耗时（秒），由方法内部计时填入。
    * ``meta``   —— 任意附加信息（confidence / rect / attempts / 所有子结果……）。
    """

    status: ActionStatus = ActionStatus.SUCCESS
    value: T | None = None
    message: str = ""
    elapsed: float = 0.0
    meta: Mapping[str, Any] = field(default_factory=dict)

    # -- 判定 -----------------------------------------------------------------
    @property
    def ok(self) -> bool:
        """是否成功。上层分支一律用它，别去比 status。"""
        return self.status is ActionStatus.SUCCESS

    @property
    def failed(self) -> bool:
        return not self.ok

    # -- 变换 -----------------------------------------------------------------
    def map(self, fn: Callable[[T], U]) -> ActionResult[U]:
        """成功时变换 value；失败时原样透传（状态、message、meta 都保留）。"""
        if not self.ok or self.value is None:
            return ActionResult(self.status, None, self.message, self.elapsed, self.meta)
        return ActionResult(self.status, fn(self.value), self.message, self.elapsed, self.meta)

    def unwrap(self, default: T | None = None) -> T | None:
        """取 value，失败时返回 default。不想写 if 的时候用。"""
        return self.value if self.ok else default

    def with_elapsed(self, elapsed: float) -> ActionResult[T]:
        return replace(self, elapsed=elapsed)

    def with_meta(self, **meta: Any) -> ActionResult[T]:
        merged = dict(self.meta)
        merged.update(meta)
        return replace(self, meta=merged)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "value": _jsonable(self.value),
            "message": self.message,
            "elapsed": round(self.elapsed, 6),
            "meta": {k: _jsonable(v) for k, v in self.meta.items()},
        }

    def __repr__(self) -> str:
        parts = [f"status={self.status.value}"]
        if self.value is not None:
            parts.append(f"value={self.value!r}")
        if self.message:
            parts.append(f"message={self.message!r}")
        if self.elapsed:
            parts.append(f"elapsed={self.elapsed:.3f}s")
        if self.meta:
            parts.append(f"meta={dict(self.meta)!r}")
        return f"ActionResult({', '.join(parts)})"

    # -- 构造快捷方式 ---------------------------------------------------------
    @classmethod
    def success(
        cls,
        value: T | None = None,
        *,
        message: str = "",
        elapsed: float = 0.0,
        **meta: Any,
    ) -> ActionResult[T]:
        return cls(ActionStatus.SUCCESS, value, message, elapsed, dict(meta))

    @classmethod
    def not_found(
        cls,
        message: str = "",
        *,
        value: Any = None,
        elapsed: float = 0.0,
        **meta: Any,
    ) -> ActionResult[Any]:
        return cls(ActionStatus.NOT_FOUND, value, message, elapsed, dict(meta))

    @classmethod
    def timeout(
        cls,
        message: str = "",
        *,
        value: Any = None,
        elapsed: float = 0.0,
        **meta: Any,
    ) -> ActionResult[Any]:
        return cls(ActionStatus.TIMEOUT, value, message, elapsed, dict(meta))

    @classmethod
    def error(
        cls,
        message: str = "",
        *,
        exc: BaseException | None = None,
        value: Any = None,
        elapsed: float = 0.0,
        **meta: Any,
    ) -> ActionResult[Any]:
        if exc is not None:
            meta.setdefault("exc_type", type(exc).__name__)
            meta.setdefault("exc", str(exc))
        return cls(ActionStatus.ERROR, value, message, elapsed, dict(meta))


def _jsonable(value: Any) -> Any:
    """把常见值对象转成可 JSON 化的形式（日志 / 剧本落盘用）。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (Point, Region)):
        return value.to_dict()
    if isinstance(value, ActionResult):
        return value.to_dict()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return repr(value)


# --------------------------------------------------------------------------- #
# Point —— 源分辨率下的整数点
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Point:
    """源分辨率下的一个点。"""

    x: int
    y: int

    def __iter__(self) -> Iterator[int]:  # 支持 x, y = point
        yield self.x
        yield self.y

    def as_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)

    def offset(self, dx: int = 0, dy: int = 0) -> Point:
        """相对偏移，返回新点（仍是源分辨率）。"""
        return Point(self.x + dx, self.y + dy)

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Point:
        return cls(int(data["x"]), int(data["y"]))

    @classmethod
    def from_tuple(cls, data: tuple[int, int]) -> Point:
        return cls(int(data[0]), int(data[1]))


# --------------------------------------------------------------------------- #
# Region —— 源分辨率下的矩形区域
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Region:
    """源分辨率下的矩形区域。

    采用 ``(x, y, w, h)``：``(x, y)`` 是左上角，``w / h`` 是宽高。
    区间语义为 **半开区间** ``[x, x + w)``，避免相邻区域重复计数。
    """

    x: int
    y: int
    w: int
    h: int

    # -- 边界 ---------------------------------------------------------------
    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        """开区间右界（不含）。"""
        return self.x + self.w

    @property
    def bottom(self) -> int:
        """开区间下界（不含）。"""
        return self.y + self.h

    @property
    def size(self) -> tuple[int, int]:
        return (self.w, self.h)

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def center(self) -> Point:
        """几何中心点。点击区域时最常用。"""
        return Point(self.x + self.w // 2, self.y + self.h // 2)

    @property
    def is_empty(self) -> bool:
        return self.w <= 0 or self.h <= 0

    # -- 关系 ---------------------------------------------------------------
    def contains(self, point: Point) -> bool:
        """点是否落在区域内（半开区间）。"""
        return self.x <= point.x < self.right and self.y <= point.y < self.bottom

    def contains_region(self, other: Region) -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def intersect(self, other: Region) -> Region | None:
        """求交；无交集返回 None。"""
        x1, y1 = max(self.x, other.x), max(self.y, other.y)
        x2, y2 = min(self.right, other.right), min(self.bottom, other.bottom)
        if x2 <= x1 or y2 <= y1:
            return None
        return Region(x1, y1, x2 - x1, y2 - y1)

    def union(self, other: Region) -> Region:
        x1, y1 = min(self.x, other.x), min(self.y, other.y)
        x2, y2 = max(self.right, other.right), max(self.bottom, other.bottom)
        return Region(x1, y1, x2 - x1, y2 - y1)

    # -- 变换 ---------------------------------------------------------------
    def offset(self, dx: int = 0, dy: int = 0) -> Region:
        return Region(self.x + dx, self.y + dy, self.w, self.h)

    def expand(self, pad: int) -> Region:
        """向外扩张 pad 像素（负数则收缩）。不做边界裁剪。"""
        return Region(self.x - pad, self.y - pad, self.w + 2 * pad, self.h + 2 * pad)

    def clamp(self, bounds: Region) -> Region:
        """限制在 bounds 内。"""
        x1 = max(self.x, bounds.x)
        y1 = max(self.y, bounds.y)
        x2 = min(self.right, bounds.right)
        y2 = min(self.bottom, bounds.bottom)
        return Region(x1, y1, max(0, x2 - x1), max(0, y2 - y1))

    # -- 序列化 -------------------------------------------------------------
    def to_tuple(self) -> tuple[int, int, int, int]:
        """``(x, y, w, h)``。"""
        return (self.x, self.y, self.w, self.h)

    def to_mss(self) -> dict[str, int]:
        """转成 mss 的 ``grab()`` 参数格式。"""
        return {"left": self.x, "top": self.y, "width": self.w, "height": self.h}

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Region:
        return cls(int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"]))

    @classmethod
    def from_tuple(cls, data: tuple[int, int, int, int]) -> Region:
        x, y, w, h = data
        return cls(int(x), int(y), int(w), int(h))

    @classmethod
    def from_corners(cls, x1: int, y1: int, x2: int, y2: int) -> Region:
        """用左上 / 右下两个角构造（右下为开区间）。"""
        return cls(int(x1), int(y1), int(x2) - int(x1), int(y2) - int(y1))

    @classmethod
    def full(cls, width: int, height: int) -> Region:
        """整屏区域。"""
        return cls(0, 0, int(width), int(height))
