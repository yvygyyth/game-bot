"""L2 Frame 层 —— 一次截图的快照 + 全部查询能力。

设计要点：

1. **一次截图，多次查询**。帧内所有查询共享同一张图，避免"查一次截一次"
   导致的时序错乱（判断了 A 之后画面已经变了，再去判断 B 就没意义了）。
2. **同一帧内缓存相同查询**。``find_image("a.png")`` 调两遍只算一次。
   缓存键由查询参数组成；``crop()`` 出的子帧独立缓存。
3. **坐标系恒为源分辨率**。Frame 记住自己的 ``origin``，所以子区域的匹配结果
   会自动加回偏移，调用方拿到的 Point 永远可以直接点击。
4. **不持有策略**。置信度默认值可以来自 Session，但重试 / 等待 / 状态迁移
   都是上层（L4 / 执行层 / 流程层）的事。

本文件目前只给出契约与骨架，算法实现待补（见各方法 docstring 的返回约定）。
其中 ``crop`` / ``to_numpy`` / ``get_pixel`` / ``save`` / ``read_number`` 已实现，
其余依赖 ``Matcher`` / ``TextReader``。
"""

from __future__ import annotations

import re
from collections.abc import Hashable
from typing import TYPE_CHECKING, Any

from ..types import ActionResult, Point, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    import numpy as np

    from .session import Session

log = get_logger("atomic.frame")

__all__ = ["Frame"]

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class Frame:
    """一张截图 + 它的查询接口。

    构造由 ``Session`` 负责，业务代码不要自己 new。
    """

    __slots__ = ("_cache", "_cached", "_frame_id", "_image", "_origin", "_session", "_timestamp")

    _next_id = 0

    def __init__(
        self,
        image: np.ndarray,
        origin: Region,
        *,
        session: Session | None = None,
        cache: bool = True,
        timestamp: float | None = None,
    ) -> None:
        self._image = image
        self._origin = origin
        self._session = session
        self._cache: dict[Hashable, ActionResult[Any]] = {}
        self._cached = cache
        self._frame_id = Frame._next_id
        Frame._next_id += 1
        self._timestamp = timestamp

    # ------------------------------------------------------------------ #
    # 元信息
    # ------------------------------------------------------------------ #
    @property
    def image(self) -> np.ndarray:
        """底层 BGR 数组 ``(H, W, 3)``。只读用途，别就地改。"""
        return self._image

    @property
    def origin(self) -> Region:
        """本帧在源分辨率中的位置。全屏帧为 ``Region.full(w, h)``。"""
        return self._origin

    @property
    def region(self) -> Region:
        """``origin`` 的别名，语义上更贴合"这块图对应屏幕上的哪个区域"。"""
        return self._origin

    @property
    def size(self) -> tuple[int, int]:
        """``(width, height)``，指本帧自身尺寸（子帧会小于全屏）。"""
        return (self._origin.w, self._origin.h)

    @property
    def frame_id(self) -> int:
        """进程内自增编号。日志里用它区分"哪一帧"。"""
        return self._frame_id

    @property
    def timestamp(self) -> float | None:
        """抓帧时刻（``time.perf_counter()``）。跨帧判断新鲜度时用。"""
        return self._timestamp

    @property
    def session(self) -> Session | None:
        return self._session

    # ------------------------------------------------------------------ #
    # 查询类
    # ------------------------------------------------------------------ #
    def find_image(
        self,
        template: str,
        region: Region | None = None,
        confidence: float | None = None,
        use_pyramid: bool = True,
        grayscale: bool = True,
    ) -> ActionResult[Point]:
        """查找单张图像，返回最佳命中中心点。

        :param template: 模板名（相对 ``vision.templates_dir``）或绝对路径。
        :param region: 源分辨率下的搜索范围；None = 整帧。
        :param confidence: 相似度阈值；None 时取 Session 的 ``default_confidence``。
        :return: ``success(value=Point, score=0.93)`` /
                 ``not_found("xxx.png 未命中")`` / ``error(...)``。
        """
        raise NotImplementedError("待实现：裁剪 region -> 调 Matcher.match -> 偏移回源坐标")

    def find_all_images(
        self,
        template: str,
        region: Region | None = None,
        confidence: float | None = None,
        max_count: int = 0,
        min_distance: int = 10,
    ) -> ActionResult[list[Point]]:
        """查找所有匹配，返回点列表。

        :param max_count: ``0`` 表示不限。
        :param min_distance: 非极大值抑制间距，防止同一图标重复计数。
        :return: ``success(value=[Point, ...])``；一个都没有时 ``not_found``。
        """
        raise NotImplementedError("待实现：Matcher.match_all + 坐标偏移")

    def find_text(
        self,
        text: str,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
        exact_match: bool = False,
    ) -> ActionResult[Point]:
        """查找文本，返回首个命中的中心点。

        :param exact_match: False 时按"包含"匹配（OCR 结果常有噪声，默认宽松）。
        :return: ``success(value=Point, text="开始游戏")`` / ``not_found``。
        """
        raise NotImplementedError("待实现：TextReader.locate -> 取第一个")

    def find_all_texts(
        self,
        text: str,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> ActionResult[list[Point]]:
        """查找所有匹配文本，返回点列表。"""
        raise NotImplementedError("待实现：TextReader.locate -> 全部点")

    def read_text(
        self,
        region: Region,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> ActionResult[str]:
        """读取区域内的全部文本。

        :return: ``success(value="体力 120/120")``；区域空白时 ``not_found``。
        """
        raise NotImplementedError("待实现：TextReader.read -> strip -> 空串转 not_found")

    def read_number(
        self,
        region: Region,
        lang: str = "en",
        confidence: float = 0.7,
    ) -> ActionResult[int | float]:
        """读取区域内的数字。

        已实现：复用 ``read_text`` + 正则提取。``"12.5"`` 返回 float，``"120"`` 返回 int。
        OCR 不可用时会把 not_found / error 原样透传。
        """
        result = self.read_text(region, lang=lang, confidence=confidence)
        if not result.ok:
            return ActionResult(result.status, None, result.message, result.elapsed, result.meta)
        match = _NUMBER_RE.search(str(result.value or ""))
        if match is None:
            return ActionResult.not_found(
                f"区域 {region.to_tuple()} 未识别到数字: {result.value!r}",
                elapsed=result.elapsed,
                raw=result.value,
            )
        token = match.group(0)
        value: int | float = float(token) if "." in token else int(token)
        return ActionResult.success(value, elapsed=result.elapsed, raw=result.value)

    def get_pixel(self, point: Point) -> ActionResult[tuple[int, int, int]]:
        """获取某个源分辨率点的 BGR 颜色。

        :return: ``success(value=(r, g, b))``（注意返回顺序是 RGB，方便和配置里写的颜色对比）；
                 点不在本帧内时 ``error``。
        """
        if not self._origin.contains(point):
            return ActionResult.error(
                f"点 {point.as_tuple()} 不在本帧范围内 {self._origin.to_tuple()}"
            )
        offset = self._to_local(point)
        b, g, r = self._image[offset.y, offset.x][:3]
        return ActionResult.success((int(r), int(g), int(b)))

    def compare_region(
        self,
        region: Region,
        template: str,
        confidence: float = 0.9,
    ) -> ActionResult[float]:
        """区域与模板的相似度比对。

        :return: ``success(value=0.97)`` —— 无论是否达阈值都成功，
                 因为调用方常常想要"具体差多少"（比如做进度条判断）。
        """
        raise NotImplementedError("待实现：Matcher.compare")

    def is_image_visible(
        self,
        template: str,
        region: Region | None = None,
        confidence: float | None = None,
    ) -> ActionResult[bool]:
        """可见性判断：找得到就是 True。

        :return: ``success(value=True/False)``。**注意**：找不到时返回的是
                 ``success(False)`` 而不是 ``not_found`` —— 因为"不可见"是一个
                 有效答案，不是失败。这是它和 ``find_image`` 的关键区别。
        """
        raise NotImplementedError("待实现：内部调 find_image 再转成 bool")

    # ------------------------------------------------------------------ #
    # 变换 / 导出
    # ------------------------------------------------------------------ #
    def crop(self, region: Region) -> Frame:
        """截取子区域，返回新 Frame。

        已实现。子帧保留坐标系：``origin`` 变成传入的 ``region``（源分辨率），
        因此子帧上查出来的点仍然是源分辨率坐标，可以直接点击。
        """
        local = Region(0, 0, self._origin.w, self._origin.h).intersect(
            Region(region.x - self._origin.x, region.y - self._origin.y, region.w, region.h)
        )
        if local is None:
            raise ValueError(f"区域 {region.to_tuple()} 与当前帧 {self._origin.to_tuple()} 无交集")
        image = self._image[local.y : local.bottom, local.x : local.right]
        absolute = Region(
            self._origin.x + local.x, self._origin.y + local.y, local.w, local.h
        )
        return Frame(image, absolute, session=self._session, cache=self._cached)

    def to_numpy(self) -> np.ndarray:
        """导出原始图像数组（底层同一个对象，不做拷贝）。"""
        return self._image

    def save(self, path: str) -> ActionResult[str]:
        """把当前帧存成图片文件。

        :return: ``success(value=实际写入路径)`` / ``error(...)``。
        """
        try:
            import cv2  # 延迟导入：不做图像处理时不拉 opencv

            ok = cv2.imwrite(str(path), self._image)
            if not ok:
                return ActionResult.error(f"写入图片失败: {path}")
            return ActionResult.success(str(path))
        except Exception as exc:
            return ActionResult.error(f"保存截图失败: {exc}", exc=exc)

    # ------------------------------------------------------------------ #
    # 缓存与内部工具
    # ------------------------------------------------------------------ #
    def cached(self, key: Hashable, producer: Any) -> ActionResult[Any]:
        """帧内查询缓存的统一入口。

        ``producer`` 是一个零参可调用对象。缓存命中（含失败结果）就直接返回 ——
        同一帧里重复找同一张图没有意义，失败也不必重算。
        """
        if not self._cached:
            return producer()
        if key in self._cache:
            return self._cache[key]
        result = producer()
        self._cache[key] = result
        return result

    def clear_cache(self) -> None:
        self._cache.clear()

    def _to_local(self, point: Point) -> Point:
        """源点 -> 本帧内的局部下标。"""
        return Point(point.x - self._origin.x, point.y - self._origin.y)

    def _to_source(self, point: Point) -> Point:
        """本帧局部点 -> 源点。"""
        return Point(point.x + self._origin.x, point.y + self._origin.y)

    def _resolve_region(self, region: Region | None) -> Region:
        """把调用方给的源分辨率 region 转成本帧内的局部 region。"""
        if region is None:
            return Region(0, 0, self._origin.w, self._origin.h)
        local = Region(
            region.x - self._origin.x, region.y - self._origin.y, region.w, region.h
        ).clamp(Region(0, 0, self._origin.w, self._origin.h))
        return local

    def _confidence(self, confidence: float | None) -> float:
        if confidence is not None:
            return confidence
        if self._session is not None:
            return self._session.default_confidence
        return 0.9

    def __repr__(self) -> str:
        return (
            f"Frame(id={self._frame_id}, size={self.size}, "
            f"origin={self._origin.to_tuple()}, cached={len(self._cache)})"
        )
