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

本文件同时给出契约与实现：查询方法把活交给 Session 上的 ``Matcher`` / ``TextReader``
（OpenCV 模板匹配、OCR 实现见 ``gamebot.vision``），帧自己只负责裁剪、缓存、
以及把命中坐标换算回源分辨率。

已实现：``find_image`` / ``find_all_images`` / ``find_text`` / ``find_all_texts`` /
``read_text`` / ``read_number`` / ``get_pixel`` / ``compare_region`` /
``is_image_visible`` / ``crop`` / ``to_numpy`` / ``save``。
"""

from __future__ import annotations

import re
from collections.abc import Hashable
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from ..types import ActionResult, ActionStatus, Point, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    import numpy as np

    from .session import Session
    from .vision import Matcher, MatchResult, TextReader

log = get_logger("atomic.frame")

__all__ = ["Frame"]

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _unbound() -> ActionResult[Any]:
    """帧没绑定 Session 时的统一错误。

    业务代码不该手工 new Frame；出现这个错误通常意味着有人绕过了 ``Session.capture``。
    """
    return ActionResult.error("当前帧未绑定 Session，无法查询（请用 session.capture() 创建帧）")


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
        :return: ``success(value=Point, score=0.93, rect=命中矩形)`` /
                 ``not_found("xxx.png 未命中")`` / ``error(...)``。

        同一帧内相同参数的调用会命中缓存，不会重复匹配。
        """
        threshold = self._confidence(confidence)
        return self.cached(
            ("find_image", template, region, threshold, use_pyramid, grayscale),
            lambda: self._find_image(template, region, threshold, use_pyramid, grayscale),
        )

    def _find_image(
        self,
        template: str,
        region: Region | None,
        confidence: float,
        use_pyramid: bool,
        grayscale: bool,
    ) -> ActionResult[Point]:
        matcher = self._matcher()
        if matcher is None:
            return _unbound()

        started = perf_counter()
        search = self._resolve_region(region)
        if search.is_empty:
            return ActionResult.not_found(
                f"搜索区域为空: {region!r}", elapsed=perf_counter() - started, template=template
            )

        try:
            found: MatchResult | None = matcher.match(
                self._image,
                template,
                region=search,
                confidence=confidence,
                use_pyramid=use_pyramid,
                grayscale=grayscale,
            )
        except Exception as exc:
            return ActionResult.error(
                f"找图失败 {template!r}: {exc}", exc=exc, elapsed=perf_counter() - started
            )

        elapsed = perf_counter() - started
        if found is None:
            return ActionResult.not_found(
                f"{template} 未命中（阈值 {confidence:.2f}）",
                elapsed=elapsed,
                template=template,
                region=search,
            )
        return ActionResult.success(
            self._to_source(found.point),
            elapsed=elapsed,
            template=template,
            score=found.score,
            # 命中矩形也换算回源分辨率，可直接用于画框/存档标注
            rect=found.region.offset(self._origin.x, self._origin.y),
        )

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
        :return: ``success(value=[Point, ...], scores=[...])``；一个都没有时 ``not_found``。
        """
        threshold = self._confidence(confidence)
        return self.cached(
            ("find_all_images", template, region, threshold, max_count, min_distance),
            lambda: self._find_all_images(template, region, threshold, max_count, min_distance),
        )

    def _find_all_images(
        self,
        template: str,
        region: Region | None,
        confidence: float,
        max_count: int,
        min_distance: int,
    ) -> ActionResult[list[Point]]:
        matcher = self._matcher()
        if matcher is None:
            return _unbound()

        started = perf_counter()
        search = self._resolve_region(region)
        if search.is_empty:
            return ActionResult.not_found(
                f"搜索区域为空: {region!r}", elapsed=perf_counter() - started, template=template
            )

        try:
            hits = matcher.match_all(
                self._image,
                template,
                region=search,
                confidence=confidence,
                max_count=max_count,
                min_distance=min_distance,
            )
        except Exception as exc:
            return ActionResult.error(
                f"批量找图失败 {template!r}: {exc}", exc=exc, elapsed=perf_counter() - started
            )

        elapsed = perf_counter() - started
        if not hits:
            return ActionResult.not_found(
                f"{template} 未命中（阈值 {confidence:.2f}）",
                elapsed=elapsed,
                template=template,
                region=search,
            )
        return ActionResult.success(
            [self._to_source(hit.point) for hit in hits],
            elapsed=elapsed,
            template=template,
            scores=[hit.score for hit in hits],
            rects=[hit.region.offset(self._origin.x, self._origin.y) for hit in hits],
        )

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
        :return: ``success(value=Point, text="开始游戏", score=...)`` / ``not_found``。
                 未启用 OCR 时返回 ``not_found("未启用 OCR")``，不报错。
        """
        return self.cached(
            ("find_text", text, region, lang, confidence, exact_match),
            lambda: self._find_text(text, region, lang, confidence, exact_match),
        )

    def _find_text(
        self,
        text: str,
        region: Region | None,
        lang: str,
        confidence: float,
        exact_match: bool,
    ) -> ActionResult[Point]:
        reader = self._reader()
        if reader is None:
            return _unbound()

        started = perf_counter()
        search = self._resolve_region(region)
        if search.is_empty:
            return ActionResult.not_found(
                f"搜索区域为空: {region!r}", elapsed=perf_counter() - started
            )

        try:
            boxes = reader.locate(
                self._image,
                text,
                region=search,
                lang=lang,
                confidence=confidence,
                exact_match=exact_match,
            )
        except Exception as exc:
            return ActionResult.error(
                f"文本识别失败 {text!r}: {exc}", exc=exc, elapsed=perf_counter() - started
            )

        elapsed = perf_counter() - started
        if not boxes:
            return ActionResult.not_found(
                f"未识别到文本 {text!r}", elapsed=elapsed, text=text, region=search
            )
        first = boxes[0]
        return ActionResult.success(
            self._to_source(first.point),
            elapsed=elapsed,
            text=first.text,
            score=first.score,
            rect=first.region.offset(self._origin.x, self._origin.y),
        )

    def find_all_texts(
        self,
        text: str,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> ActionResult[list[Point]]:
        """查找所有匹配文本，返回点列表。"""
        return self.cached(
            ("find_all_texts", text, region, lang, confidence),
            lambda: self._find_all_texts(text, region, lang, confidence),
        )

    def _find_all_texts(
        self,
        text: str,
        region: Region | None,
        lang: str,
        confidence: float,
    ) -> ActionResult[list[Point]]:
        reader = self._reader()
        if reader is None:
            return _unbound()

        started = perf_counter()
        search = self._resolve_region(region)
        try:
            boxes = reader.locate(
                self._image, text, region=search, lang=lang, confidence=confidence
            )
        except Exception as exc:
            return ActionResult.error(
                f"文本识别失败 {text!r}: {exc}", exc=exc, elapsed=perf_counter() - started
            )

        elapsed = perf_counter() - started
        if not boxes:
            return ActionResult.not_found(f"未识别到文本 {text!r}", elapsed=elapsed, text=text)
        return ActionResult.success(
            [self._to_source(box.point) for box in boxes],
            elapsed=elapsed,
            text=text,
            texts=[box.text for box in boxes],
            scores=[box.score for box in boxes],
        )

    def read_text(
        self,
        region: Region,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> ActionResult[str]:
        """读取区域内的全部文本。

        :return: ``success(value="体力 120/120")``；区域空白时 ``not_found``。
        """
        return self.cached(
            ("read_text", region, lang, confidence),
            lambda: self._read_text(region, lang, confidence),
        )

    def _read_text(self, region: Region, lang: str, confidence: float) -> ActionResult[str]:
        reader = self._reader()
        if reader is None:
            return _unbound()

        started = perf_counter()
        search = self._resolve_region(region)
        if search.is_empty:
            return ActionResult.not_found(
                f"读取区域为空: {region.to_tuple()}", elapsed=perf_counter() - started
            )

        try:
            raw = reader.read(self._image, region=search, lang=lang, confidence=confidence)
        except Exception as exc:
            return ActionResult.error(
                f"读取文本失败: {exc}", exc=exc, elapsed=perf_counter() - started
            )

        elapsed = perf_counter() - started
        text = (raw or "").strip()
        if not text:
            return ActionResult.not_found(
                f"区域 {region.to_tuple()} 未识别到文本", elapsed=elapsed, region=search
            )
        return ActionResult.success(text, elapsed=elapsed, region=search)

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
                 只有当区域为空、或模板比区域还大导致算不出分数时才是 ``not_found``。
        """
        return self.cached(
            ("compare_region", region, template, confidence),
            lambda: self._compare_region(region, template, confidence),
        )

    def _compare_region(
        self, region: Region, template: str, confidence: float
    ) -> ActionResult[float]:
        matcher = self._matcher()
        if matcher is None:
            return _unbound()

        started = perf_counter()
        search = self._resolve_region(region)
        if search.is_empty:
            return ActionResult.not_found(
                f"比对区域为空: {region.to_tuple()}", elapsed=perf_counter() - started
            )

        try:
            score = matcher.compare(self._image, search, template, confidence)
        except Exception as exc:
            return ActionResult.error(
                f"区域比对失败 {template!r}: {exc}", exc=exc, elapsed=perf_counter() - started
            )

        elapsed = perf_counter() - started
        if score is None:
            return ActionResult.not_found(
                f"模板 {template!r} 比区域 {region.to_tuple()} 还大，无法比对",
                elapsed=elapsed,
                template=template,
                region=search,
            )
        return ActionResult.success(
            float(score), elapsed=elapsed, template=template, region=search
        )

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

                 唯一的例外是底层真出错（模板缺失、Matcher 抛异常），
                 此时原样透传 ``error`` —— 把错误当成"不可见"会掩盖 bug。
        """
        result = self.find_image(template, region=region, confidence=confidence)
        if result.ok:
            return ActionResult.success(True, elapsed=result.elapsed, **result.meta)
        if result.status is ActionStatus.ERROR:
            return ActionResult(result.status, None, result.message, result.elapsed, result.meta)
        return ActionResult.success(
            False,
            message=f"{template} 不可见",
            elapsed=result.elapsed,
            **{k: v for k, v in result.meta.items() if k != "message"},
        )

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

        父目录不存在会自动创建 —— ``cv2.imwrite`` 自己不会建目录，
        直接失败只会得到一句"写入图片失败"，很难看出是路径问题。

        :return: ``success(value=实际写入路径)`` / ``error(...)``。
        """
        try:
            import cv2  # 延迟导入：不做图像处理时不拉 opencv
        except ImportError as exc:  # pragma: no cover
            return ActionResult.error(f"保存截图需要 opencv: {exc}", exc=exc)

        target = Path(path)
        try:
            if target.parent and not target.parent.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
            ok = cv2.imwrite(str(target), self._image)
        except Exception as exc:
            return ActionResult.error(f"保存截图失败 {target}: {exc}", exc=exc)

        if not ok:
            return ActionResult.error(
                f"写入图片失败: {target}"
                "（常见原因：扩展名不被 OpenCV 支持，或目标被其他程序占用）"
            )
        return ActionResult.success(str(target), size=self.size, bytes=target.stat().st_size)

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

    def _matcher(self) -> Matcher | None:
        """取当前 Session 的匹配器。没绑 Session 时返回 None（调用方转成 error）。"""
        return None if self._session is None else self._session.matcher

    def _reader(self) -> TextReader | None:
        """取当前 Session 的 OCR 实现。未启用 OCR 时是 UnavailableTextReader，不是 None。"""
        return None if self._session is None else self._session.reader

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
