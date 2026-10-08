"""L3 Query 层 —— 把"查什么"变成可序列化的数据。

为什么要从 Frame 上再抽一层：

* **可序列化**：Query 是纯数据，能写进 YAML / JSON，配置驱动流程（见
  ``config/flows/*.yaml``），改策略不用改代码。
* **可组合**：``AndQuery`` / ``OrQuery`` / ``NotQuery`` 能表达"同时看到 A 和 B"
  这种真实需求，不必在业务代码里写一串 if。
* **可复用**：同一个 Query 对象能在状态识别、流程守卫、步骤前置条件里反复用。
* **不依赖 Frame 实现**：Query 只依赖 Frame 的**方法签名**，所以可以做假 Frame 测试。

与组合子层（L4）的分工：

* L3（本文件）是**对象**，描述"一个查询"，可存盘、可嵌套；
* L4 是**函数**，描述"多个查询之间怎么协作"（全中 / 任一 / 顺序 / 计数 / 跨帧等待）。

注意：``ExactTextQuery`` 之类如果需要，直接加 dataclass，不要给已有类堆开关。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, runtime_checkable

from ..types import ActionResult, Point, Region

if TYPE_CHECKING:
    from .frame import Frame

__all__ = [
    "AllImagesQuery",
    "AllTextsQuery",
    "AndQuery",
    "CompareQuery",
    "ImageQuery",
    "NotQuery",
    "NumberQuery",
    "OrQuery",
    "PixelQuery",
    "Query",
    "QueryLike",
    "TextQuery",
    "VisibleQuery",
    "query_from_dict",
]


@runtime_checkable
class Query(Protocol):
    """查询描述符契约。实现只需一个 ``run``。"""

    def run(self, frame: Frame) -> ActionResult[Any]:
        """在给定帧上执行查询。

        实现约定：
        * 不要自己截图 —— 帧由调用方提供，保证同一次判断看的是同一张图；
        * 不要重试、不要 sleep、不要改全局状态 —— 那是执行层的职责。
        """
        ...


# --------------------------------------------------------------------------- #
# 基础查询
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ImageQuery:
    """查找单张模板图。"""

    template: str
    region: Region | None = None
    confidence: float = 0.85
    use_pyramid: bool = True
    grayscale: bool = True

    def run(self, frame: Frame) -> ActionResult[Point]:
        return frame.find_image(
            self.template,
            region=self.region,
            confidence=self.confidence,
            use_pyramid=self.use_pyramid,
            grayscale=self.grayscale,
        )


@dataclass(frozen=True, slots=True)
class AllImagesQuery:
    """查找所有同名图标的实例。"""

    template: str
    region: Region | None = None
    confidence: float = 0.9
    max_count: int = 0
    min_distance: int = 10

    def run(self, frame: Frame) -> ActionResult[list[Point]]:
        return frame.find_all_images(
            self.template,
            region=self.region,
            confidence=self.confidence,
            max_count=self.max_count,
            min_distance=self.min_distance,
        )


@dataclass(frozen=True, slots=True)
class TextQuery:
    """查找文本。"""

    text: str
    region: Region | None = None
    lang: str = "ch"
    confidence: float = 0.8
    exact_match: bool = False

    def run(self, frame: Frame) -> ActionResult[Point]:
        return frame.find_text(
            self.text,
            region=self.region,
            lang=self.lang,
            confidence=self.confidence,
            exact_match=self.exact_match,
        )


@dataclass(frozen=True, slots=True)
class AllTextsQuery:
    """查找文本的所有出现位置。"""

    text: str
    region: Region | None = None
    lang: str = "ch"
    confidence: float = 0.8

    def run(self, frame: Frame) -> ActionResult[list[Point]]:
        return frame.find_all_texts(
            self.text, region=self.region, lang=self.lang, confidence=self.confidence
        )


@dataclass(frozen=True, slots=True)
class NumberQuery:
    """读取数字，可选带阈值判断。

    例：判断体力是否足够::

        NumberQuery(region=HP, comparator=lambda v: v >= 30)
    """

    region: Region
    lang: str = "en"
    confidence: float = 0.7
    comparator: Callable[[float], bool] | None = None

    def run(self, frame: Frame) -> ActionResult[int | float]:
        result = frame.read_number(self.region, lang=self.lang, confidence=self.confidence)
        if not result.ok or self.comparator is None:
            return result
        value = result.value
        if value is None or not self.comparator(float(value)):
            return ActionResult.not_found(
                f"数字 {value!r} 未通过阈值判断",
                elapsed=result.elapsed,
                value=value,
                raw=result.meta.get("raw"),
            )
        return result


@dataclass(frozen=True, slots=True)
class PixelQuery:
    """像素颜色比对。最轻量的"状态探针"，比找图快一个数量级。"""

    point: Point
    expected_color: tuple[int, int, int] | None = None
    tolerance: int = 10

    def run(self, frame: Frame) -> ActionResult[tuple[int, int, int]]:
        result = frame.get_pixel(self.point)
        if not result.ok or self.expected_color is None:
            return result
        actual = result.value
        assert actual is not None
        if not _color_close(actual, self.expected_color, self.tolerance):
            return ActionResult.not_found(
                f"颜色不匹配: 实际{actual} 期望{self.expected_color} ±{self.tolerance}",
                value=actual,
            )
        return result


@dataclass(frozen=True, slots=True)
class CompareQuery:
    """区域相似度比对。

    :param comparator: 对相似度分数的判断；None 表示只要 >0 就算通过。
    """

    region: Region
    template: str
    confidence: float = 0.9
    comparator: Callable[[float], bool] | None = None

    def run(self, frame: Frame) -> ActionResult[float]:
        result = frame.compare_region(self.region, self.template, self.confidence)
        if not result.ok:
            return result
        score = float(result.value or 0.0)
        predicate = self.comparator or (lambda s: s >= self.confidence)
        if not predicate(score):
            return ActionResult.not_found(
                f"相似度 {score:.4f} 未通过阈值",
                elapsed=result.elapsed,
                score=score,
            )
        return result


@dataclass(frozen=True, slots=True)
class VisibleQuery:
    """可见性查询。

    和 ``ImageQuery`` 的区别：图像不在时 ``ImageQuery`` 返回 ``not_found``（算失败），
    而 ``VisibleQuery`` 返回 ``success(False)``（算"有效答案"）。
    流程守卫里判断"某按钮不在"时用它，语义更顺。
    """

    template: str
    region: Region | None = None
    confidence: float = 0.9

    def run(self, frame: Frame) -> ActionResult[bool]:
        return frame.is_image_visible(self.template, self.region, self.confidence)


# --------------------------------------------------------------------------- #
# 组合查询（对象形式；函数形式见 L4 combinators）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AndQuery:
    """全部命中才算成功。"""

    queries: tuple[Query, ...] = ()

    def run(self, frame: Frame) -> ActionResult[list[ActionResult[Any]]]:
        from .combinators import find_all_of

        return find_all_of(frame, list(self.queries))


@dataclass(frozen=True, slots=True)
class OrQuery:
    """任一命中即成功。"""

    queries: tuple[Query, ...] = ()
    short_circuit: bool = True

    def run(self, frame: Frame) -> ActionResult[Any]:
        from .combinators import find_any_of

        return find_any_of(frame, list(self.queries), short_circuit=self.short_circuit)


@dataclass(frozen=True, slots=True)
class NotQuery:
    """取反：内部查询失败才算成功。"""

    query: Query
    message: str = ""

    def run(self, frame: Frame) -> ActionResult[bool]:
        from .combinators import find_none_of

        result = find_none_of(frame, [self.query])
        if not result.ok:
            return ActionResult.not_found(self.message or "NotQuery 失败: 内部查询命中了")
        return ActionResult.success(True, message=self.message)


# --------------------------------------------------------------------------- #
# 类型别名 & 反序列化
# --------------------------------------------------------------------------- #
QueryLike: TypeAlias = Query | Callable[["Frame"], ActionResult[Any]]
"""Query 或任意等价的可调用对象。流程配置里允许写 lambda 做临时守卫。"""


_REGISTRY: dict[str, type] = {
    "ImageQuery": ImageQuery,
    "AllImagesQuery": AllImagesQuery,
    "TextQuery": TextQuery,
    "AllTextsQuery": AllTextsQuery,
    "NumberQuery": NumberQuery,
    "PixelQuery": PixelQuery,
    "CompareQuery": CompareQuery,
    "VisibleQuery": VisibleQuery,
    "AndQuery": AndQuery,
    "OrQuery": OrQuery,
    "NotQuery": NotQuery,
}


def query_registry() -> dict[str, type]:
    """可用的查询类型名 -> 类。配置反序列化（``flow.loader``）靠它。

    新增一种 Query 时，除了写类，还要在 ``_REGISTRY`` 里登记一行 ——
    否则 YAML 里就写不出来，只能写 Python。
    """
    return dict(_REGISTRY)


def query_from_dict(data: Any) -> Query:
    """把配置里的字典还原成 Query 对象。

    支持的形式（YAML 里两种写法都行）::

        {type: ImageQuery, template: a.png, confidence: 0.9}
        ImageQuery(template=a.png)

    :raises ValueError: type 缺失 / 未注册 / 字段拼错 / 嵌套结构不对。
        **拼错一个键就报错，不静默忽略** —— 静默忽略的表现是
        "这个条件永远成立或永远不成立"，属于最难查的一类配置 bug。

    放在**原子层**（而不是 ``flow.loader``）是有原因的：查询注册表本来就在
    这里，而且 `PageTree` 的使用者（业务层手写状态树时）也要用它 ——
    状态层不许 import 流程层（``tests/test_structure.py`` 用 AST 盯着）。
    """
    if isinstance(data, str):
        # 简写：直接给模板名，等价于 ImageQuery(template=...)。
        # 只对"看图"这一种最常见的条件开这个口子，别的类型一律要写全。
        return ImageQuery(template=data)
    if not isinstance(data, dict):
        raise ValueError(f"查询定义必须是映射(mapping)或模板名字符串，收到: {data!r}")

    payload = dict(data)
    type_name = str(payload.pop("type", "")).strip()
    if not type_name:
        raise ValueError(f"查询定义缺少 type: {data!r}")

    cls = _REGISTRY.get(type_name)
    if cls is None:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"未登记的查询类型 {type_name!r}。可用的有: {known}")

    nested = payload.get("queries")
    if isinstance(nested, (list, tuple)):
        payload["queries"] = tuple(query_from_dict(item) for item in nested)
    if "query" in payload and isinstance(payload["query"], (dict, str)):
        payload["query"] = query_from_dict(payload["query"])

    if payload.get("region") is not None:
        payload["region"] = _region_from_config(payload["region"])
    if "point" in payload and not isinstance(payload["point"], Point):
        payload["point"] = _point_from_config(payload["point"])

    allowed = {f.name for f in fields(cls)}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(
            f"{type_name} 有未知字段: {', '.join(unknown)}（可用: {sorted(allowed)}）"
        )
    return cls(**payload)


def _region_from_config(value: Any) -> Region:
    """``region`` 三种写法都收：``[x,y,w,h]`` / ``{x,y,w,h}`` / ``Region``。"""
    if isinstance(value, Region):
        return value
    if isinstance(value, dict):
        return Region.from_dict(value)
    if isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise ValueError(f"region 需要 4 个数字 [x,y,w,h]，收到: {value!r}")
        return Region.from_tuple(tuple(int(v) for v in value))  # type: ignore[arg-type]
    raise ValueError(f"region 的写法不认识: {value!r}（用 [x,y,w,h] 或 {{x,y,w,h}}）")


def _point_from_config(value: Any) -> Point:
    """``point`` 三种写法：``[x,y]`` / ``{x,y}`` / ``Point``。"""
    if isinstance(value, Point):
        return value
    if isinstance(value, dict):
        return Point.from_dict(value)
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(f"point 需要 2 个数字 [x,y]，收到: {value!r}")
        return Point.from_tuple(tuple(int(v) for v in value))  # type: ignore[arg-type]
    raise ValueError(f"point 的写法不认识: {value!r}（用 [x,y] 或 {{x,y}}）")


def _color_close(
    actual: tuple[int, int, int],
    expected: tuple[int, int, int],
    tolerance: int,
) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected, strict=False))
