"""OpenCV 模板匹配实现。

**坐标系约定**（很容易搞错，先说清楚）：

* ``image`` 是调用方给的图（通常是 Frame 自己那块裁剪图）。
* ``region`` 是**相对这张图**的搜索范围。
* 返回的 ``MatchResult`` 坐标也是**相对这张图**的 ——
  换算成屏幕坐标是 ``Frame`` 的职责（它知道自己的 origin）。

命中的坑与对策：

1. **模板缓存**。模板图只读盘一次，之后按 ``(模板名, 缩放, 是否灰度)`` 缓存
   预处理结果。否则每秒几百次 ``imread`` 纯浪费。
2. **多尺度（金字塔）**。只缩放**模板**、不缩放画面，所以命中坐标天然落在画面
   坐标系里，不用做逆变换。代价是慢 N 倍，分辨率固定时应该关掉。
3. **灰度优先**。``TM_CCOEFF_NORMED`` + 灰度比彩色快约 3 倍且更鲁棒；
   只有"同形状不同颜色"的图标才需要彩色。
4. **NaN 兜底**。模板或区域是纯色时，``TM_CCOEFF_NORMED`` 会返回 NaN，
   直接比较会得到 False 且看不出原因，所以统一压到 -1。
5. **模板比画面大** 时 ``matchTemplate`` 会抛异常，必须先判断再调用。
6. **NMS**。``match_all`` 必须做非极大值抑制，否则一个图标会返回几十个相邻点；
   用切比雪夫距离（比欧氏距离便宜，效果等价）。
7. **带 alpha 的 PNG** 直接丢 alpha 通道（``BGRA2BGR``）。需要"只比一部分像素"
   （例如只比按钮边框、忽略文字）时，用 ``mask=`` 显式传遮罩 —— 见
   :meth:`OpenCvMatcher._masked_matrix`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..atomic.vision import MatchResult
from ..exceptions import BackendError, TemplateNotFoundError
from ..types import Point, Region

__all__ = ["OpenCvMatcher"]

#: 纯色区域的 matchTemplate 结果是 NaN，统一压到这个分数（必然低于任何阈值）
_NAN_FLOOR = -1.0


def _scaled_mask(mask: np.ndarray | None, prepared: np.ndarray) -> np.ndarray | None:
    """把遮罩缩放到模板**当前**尺寸。

    金字塔会缩放模板，遮罩必须跟着缩放，否则尺寸对不上（直接抛异常）。
    用最近邻：遮罩只有 0/1，插值出 0.5 没有意义。
    """
    if mask is None:
        return None
    height, width = prepared.shape[:2]
    if mask.shape[:2] == (height, width):
        return mask
    return cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)

#: match_all 的候选上限。画面全白 + 低阈值时候选可能有几十万个，
#: 取前 N 个高分候选已经足够（NMS 之后通常只剩几个）。
_MAX_CANDIDATES = 5000

#: 认作图片的模板后缀
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


class OpenCvMatcher:
    """基于 ``cv2.matchTemplate`` 的模板匹配器（实现 ``Matcher`` 协议）。

    :param templates_dir: 主模板根。相对模板名都从这里解析。
    :param extra_dirs: **附加模板根，优先于主根搜索**。顺序即优先级，靠前的先搜。
        用途：每个脚本功能把自己的图片放在自己目录里
        （``games/<游戏>/scripts/<功能>/templates/``），并且可以覆盖游戏级公共模板。
    :param fallback_dirs: **兜底模板根，在主根之后搜索**。优先级最低，只在前面的根
        都找不到时才用。用途：游戏级公共模板（``games/<游戏>/templates/``）——
        业务层写的名字仍然相对**功能级**根，公共图则自然回落到游戏级。
    :param scales: 金字塔缩放系数。把 1.0 放最前面，最常见的情况先算。
    :param preload: 启动时预加载整个模板目录。会明显缩短第一次查询的延迟。
    """

    def __init__(
        self,
        templates_dir: Any,
        *,
        extra_dirs: tuple[Any, ...] = (),
        fallback_dirs: tuple[Any, ...] = (),
        grayscale: bool = True,
        use_pyramid: bool = True,
        scales: tuple[float, ...] = (1.0, 0.9, 1.1, 0.8, 1.25),
        preload: bool = True,
    ) -> None:
        self.templates_dir = Path(templates_dir)
        #: 搜索顺序：附加根（更具体）> 主根 > 兜底根（游戏级公共）
        self.roots: tuple[Path, ...] = (
            *(Path(d) for d in extra_dirs),
            self.templates_dir,
            *(Path(d) for d in fallback_dirs),
        )
        self.grayscale = grayscale
        self.use_pyramid = use_pyramid
        self.scales = tuple(scales)
        self._raw: dict[str, np.ndarray] = {}
        self._prepared: dict[tuple[str, float, bool], np.ndarray] = {}
        self.preloaded = 0
        if preload:
            self.preloaded = self.preload()

    # ------------------------------------------------------------------ #
    # 模板加载与缓存
    # ------------------------------------------------------------------ #
    def load_template(self, template: str) -> np.ndarray:
        """读取模板原图（BGR，已丢弃 alpha）并缓存。

        :raises TemplateNotFoundError: 文件不存在。
        :raises BackendError: 文件存在但不是有效图片，或通道数不支持。
        """
        return self._load_raw(template)

    def preload(self) -> int:
        """预加载**所有模板根**下的图片，返回加载数量。

        按 ``roots`` 顺序遍历，所以同一个相对名在两个根里都有时，
        先到的（更具体的那个根）赢 —— 和 :meth:`_resolve_path` 的顺序一致。
        """
        count = 0
        for root in self.roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
                    continue
                self._load_raw(path.relative_to(root).as_posix())
                count += 1
        return count

    def clear_cache(self) -> None:
        self._raw.clear()
        self._prepared.clear()

    @property
    def cached_templates(self) -> list[str]:
        """已缓存的模板名，方便启动日志里打一行。"""
        return sorted(self._raw)

    def _resolve_path(self, template: str) -> Path:
        """把模板名解析成实际文件路径。

        按 ``roots`` 顺序找第一个存在的；都不存在时返回**主根**下的路径 ——
        报错信息里要指向"业务层写模板名的那一层"，给个合理的猜测比返回 None 好排查。
        """
        path = Path(template)
        if path.is_absolute():
            return path
        for root in self.roots:
            candidate = root / path
            if candidate.is_file():
                return candidate
        return self.templates_dir / path

    def _cache_key(self, template: str) -> str:
        # 文件系统不区分大小写，缓存键也统一，避免同一个文件被缓存两次
        return str(template).replace("\\", "/").lower()

    def _load_raw(self, template: str) -> np.ndarray:
        key = self._cache_key(template)
        cached = self._raw.get(key)
        if cached is not None:
            return cached

        path = self._resolve_path(template)
        if not path.is_file():
            raise TemplateNotFoundError(f"模板图不存在: {path}")
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise BackendError(f"模板图无法解码（文件损坏或不是图片）: {path}")
        image = self._strip_alpha(image)
        self._raw[key] = image
        return image

    @staticmethod
    def _strip_alpha(image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        channels = image.shape[2]
        if channels == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        if channels == 3:
            return image
        raise BackendError(f"模板图通道数不支持: {image.shape}")

    def _prepare(self, template: str, *, scale: float, grayscale: bool) -> np.ndarray:
        """按 (模板, 缩放, 灰度) 预处理并缓存。"""
        key = (self._cache_key(template), round(scale, 4), grayscale)
        cached = self._prepared.get(key)
        if cached is not None:
            return cached

        image = self._load_raw(template)
        if scale != 1.0:
            width = max(1, round(image.shape[1] * scale))
            height = max(1, round(image.shape[0] * scale))
            # 缩小用 INTER_AREA（抗锯齿），放大用 INTER_LINEAR
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            image = cv2.resize(image, (width, height), interpolation=interpolation)
        if grayscale:
            image = self._to_gray(image)

        self._prepared[key] = image
        return image

    # ------------------------------------------------------------------ #
    # 底层工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray:
        return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _crop(image: np.ndarray, region: Region | None) -> tuple[np.ndarray | None, Point]:
        """裁出搜索区域。

        :return: ``(裁剪图, 裁剪左上角在 image 中的位置)``。区域越界会被裁到边界，
                 返回的偏移量保证后续坐标换算仍然正确。空区域返回 ``(None, ...)``。
        """
        if region is None:
            return image, Point(0, 0)
        height, width = image.shape[:2]
        x1 = max(0, region.x)
        y1 = max(0, region.y)
        x2 = min(width, region.right)
        y2 = min(height, region.bottom)
        if x2 <= x1 or y2 <= y1:
            return None, Point(0, 0)
        return image[y1:y2, x1:x2], Point(x1, y1)

    @staticmethod
    def _masked_matrix(
        search: np.ndarray,
        template: np.ndarray,
        mask: np.ndarray,
    ) -> np.ndarray:
        """**遮罩内的减均值相关** —— 只比较 mask 覆盖的像素。

        为什么不用 ``cv2.matchTemplate(..., TM_CCORR_NORMED, mask=...)``：那个不减均值，
        结果被亮度主导 —— 任何一块亮的区域都能到 0.98。实测拿它做"只比边框"，
        整屏到处是 0.98 的误命中。

        这里用 NCC（减均值、除以标准差），只是把每一项都乘上 mask：
        ``sum((T-meanT)*(I-meanI)*M) / sqrt(sum((T-meanT)^2 * M) * sum((I-meanI)^2 * M))``。
        全部用 ``TM_CCORR`` 卷积算，O(像素) 而不是逐窗口循环。

        :param search: 搜索区域的灰度图。
        :param template: 模板（与 mask 同尺寸）。
        :param mask: 0/1 遮罩。
        :return: 与 ``search`` 对应的分数矩阵（NaN 已兜底）。
        """
        image = search.astype(np.float32)
        tpl = template.astype(np.float32)
        cover = (mask > 0).astype(np.float32)
        count = float(cover.sum())
        if count <= 0 or tpl.shape != cover.shape:
            raise BackendError("遮罩为空或与模板尺寸不一致")

        mean = float((tpl * cover).sum() / count)
        centered = (tpl - mean) * cover
        var_template = float((centered * centered).sum())

        numerator = cv2.matchTemplate(image, centered, cv2.TM_CCORR)
        sum_image = cv2.matchTemplate(image, cover, cv2.TM_CCORR)
        sum_square = cv2.matchTemplate(image * image, cover, cv2.TM_CCORR)
        var_image = np.maximum(sum_square - (sum_image * sum_image) / count, 0.0)

        denominator = np.sqrt(var_template * var_image)
        matrix = np.zeros_like(numerator)
        np.divide(numerator, denominator, out=matrix, where=denominator > 1e-6)
        matrix = np.nan_to_num(matrix, nan=_NAN_FLOOR, posinf=_NAN_FLOOR, neginf=_NAN_FLOOR)
        return matrix

    def _raw_result(
        self,
        search: np.ndarray,
        template: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> tuple[np.ndarray, tuple[int, int]] | None:
        """跑一次 matchTemplate（可选遮罩）。

        :return: ``(分数矩阵, (模板宽, 模板高))``；模板比画面大时返回 None。
        """
        th, tw = template.shape[:2]
        if th > search.shape[0] or tw > search.shape[1]:
            return None
        if mask is None:
            matrix = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        else:
            matrix = self._masked_matrix(search, template, mask)
        matrix = np.nan_to_num(matrix, nan=_NAN_FLOOR, posinf=_NAN_FLOOR, neginf=_NAN_FLOOR)
        return matrix, (tw, th)

    def _scales(self, use_pyramid: bool) -> tuple[float, ...]:
        return self.scales if (use_pyramid and self.use_pyramid) else (1.0,)

    @staticmethod
    def _distance(a: Point, b: Point) -> int:
        """切比雪夫距离。NMS 只需要"够近就算同一个"，不需要精确欧氏距离。"""
        return max(abs(a.x - b.x), abs(a.y - b.y))

    # ------------------------------------------------------------------ #
    # Matcher 协议
    # ------------------------------------------------------------------ #
    def match(
        self,
        image: np.ndarray,
        template: str,
        *,
        region: Region | None = None,
        confidence: float = 0.9,
        use_pyramid: bool = True,
        grayscale: bool = True,
        mask: np.ndarray | None = None,
    ) -> MatchResult | None:
        search, offset = self._crop(image, region)
        if search is None:
            return None

        gray = grayscale and self.grayscale
        probe = self._to_gray(search) if gray else search
        best: MatchResult | None = None

        for scale in self._scales(use_pyramid):
            prepared = self._prepare(template, scale=scale, grayscale=gray)
            scaled_mask = _scaled_mask(mask, prepared)
            found = self._raw_result(probe, prepared, scaled_mask)
            if found is None:
                continue
            matrix, (tw, th) = found
            _, max_val, _, max_loc = cv2.minMaxLoc(matrix)
            score = float(max_val)
            if score < confidence:
                continue
            top_left = Point(offset.x + int(max_loc[0]), offset.y + int(max_loc[1]))
            candidate = MatchResult(
                point=Point(top_left.x + tw // 2, top_left.y + th // 2),
                score=score,
                region=Region(top_left.x, top_left.y, tw, th),
            )
            if best is None or candidate.score > best.score:
                best = candidate

        return best

    def match_all(
        self,
        image: np.ndarray,
        template: str,
        *,
        region: Region | None = None,
        confidence: float = 0.9,
        max_count: int = 0,
        min_distance: int = 10,
        grayscale: bool = True,
        mask: np.ndarray | None = None,
    ) -> list[MatchResult]:
        """找出所有命中点。

        只做单尺度匹配（协议里没有 ``use_pyramid``）—— 多尺度 + 多实例的
        去重逻辑很难解释清楚，需要时应该按固定分辨率重新采集模板。

        ``mask`` 给了就只比较遮罩内的像素（见 :meth:`_masked_matrix`）——
        用来"只比按钮边框、忽略中间文字"。
        """
        search, offset = self._crop(image, region)
        if search is None:
            return []

        gray = grayscale and self.grayscale
        probe = self._to_gray(search) if gray else search
        prepared = self._prepare(template, scale=1.0, grayscale=gray)
        found = self._raw_result(probe, prepared, _scaled_mask(mask, prepared))
        if found is None:
            return []
        matrix, (tw, th) = found

        ys, xs = np.where(matrix >= confidence)
        if xs.size == 0:
            return []

        scores = matrix[ys, xs]
        order = np.argsort(-scores)
        if order.size > _MAX_CANDIDATES:
            order = order[:_MAX_CANDIDATES]

        results: list[MatchResult] = []
        for index in order:
            top_left = Point(offset.x + int(xs[index]), offset.y + int(ys[index]))
            center = Point(top_left.x + tw // 2, top_left.y + th // 2)
            if any(self._distance(center, hit.point) < min_distance for hit in results):
                continue
            results.append(
                MatchResult(
                    point=center,
                    score=float(scores[index]),
                    region=Region(top_left.x, top_left.y, tw, th),
                )
            )
            if max_count and len(results) >= max_count:
                break

        return results

    def compare(
        self,
        image: np.ndarray,
        region: Region,
        template: str,
        confidence: float = 0.9,
    ) -> float | None:
        """返回区域与模板的最高相似度，**不判阈值**。

        ``confidence`` 只是协议对齐用的占位参数，本方法不用它 ——
        调用方通常想知道"具体差多少"（做进度条、血条判断），
        在这里过滤掉分数反而会把信息丢掉。

        :return: 相似度；区域为空或模板比区域大时返回 None。
        """
        search, _ = self._crop(image, region)
        if search is None:
            return None

        gray = self.grayscale
        probe = self._to_gray(search) if gray else search
        best: float | None = None

        for scale in self._scales(True):
            prepared = self._prepare(template, scale=scale, grayscale=gray)
            found = self._raw_result(probe, prepared)
            if found is None:
                continue
            matrix, _ = found
            score = float(matrix.max())
            best = score if best is None else max(best, score)

        return best

    def __repr__(self) -> str:
        return (
            f"OpenCvMatcher(dir={str(self.templates_dir)!r}, "
            f"templates={len(self._raw)}, grayscale={self.grayscale}, "
            f"pyramid={self.use_pyramid})"
        )
