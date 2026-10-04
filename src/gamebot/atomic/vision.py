"""视觉算法协议 —— 把"找图 / 找字"的能力和 Frame 解耦。

为什么要单独抽一层协议：

* Frame（L2）负责编排，不该关心 OpenCV 具体怎么算；
* 换匹配算法（模板匹配 / 特征点 / 模板金字塔）不该动 Frame；
* 测试时可以塞一个 ``FakeMatcher``，不依赖任何图片；
* OCR 是可选的（有人用 RapidOCR，有人用 Tesseract），没装就退化，
  而不是让整个框架 import 失败。

实现放在 ``gamebot.atomic.backends`` 之外的独立模块，例如将来的
``gamebot.vision.opencv_matcher`` / ``gamebot.vision.rapid_ocr``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..types import Point, Region

if TYPE_CHECKING:  # 只为类型检查拉起 numpy，运行期不依赖
    import numpy as np

    ImageArray = np.ndarray
else:  # pragma: no cover - 运行期走这里
    ImageArray = Any

__all__ = [
    "MatchResult",
    "Matcher",
    "TextBox",
    "TextReader",
    "UnavailableTextReader",
]


# --------------------------------------------------------------------------- #
# 返回值
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class MatchResult:
    """一次模板匹配的命中。

    **坐标是相对于传进去的那张图**（``Matcher.match(image, ...)`` 里的 ``image``），
    不是屏幕坐标 —— 匹配器看不到屏幕，只知道别人给它的数组。

    换算成源分辨率是 ``Frame`` 的职责：它知道自己的 ``origin``，加回偏移即可。
    """

    point: Point
    """命中中心点（点击就用它）。相对传入的图像。"""

    score: float
    """相似度 0.0 ~ 1.0。"""

    region: Region
    """命中矩形。相对传入的图像，比 point 更适合做可视化标注。"""


@dataclass(frozen=True, slots=True)
class TextBox:
    """一次文本定位的命中。坐标同样相对于传入的图像。"""

    point: Point
    text: str
    score: float
    region: Region


# --------------------------------------------------------------------------- #
# 协议
# --------------------------------------------------------------------------- #
@runtime_checkable
class Matcher(Protocol):
    """模板匹配能力。所有实现必须线程安全（Frame 内可能并发查询）。"""

    def match(
        self,
        image: ImageArray,
        template: str,
        *,
        region: Region | None = None,
        confidence: float = 0.9,
        use_pyramid: bool = True,
        grayscale: bool = True,
    ) -> MatchResult | None:
        """在 ``image``（已是局部图）的 ``region`` 内找 ``template`` 的最佳命中。

        :param template: 模板标识。可以是文件名（相对 templates_dir）或绝对路径。
        :param region: 相对 ``image`` 左上角的搜索范围；None 表示全图。
        :return: 最佳命中，未达 ``confidence`` 阈值时返回 None。
        """
        ...

    def match_all(
        self,
        image: ImageArray,
        template: str,
        *,
        region: Region | None = None,
        confidence: float = 0.9,
        max_count: int = 0,
        min_distance: int = 10,
        grayscale: bool = True,
    ) -> list[MatchResult]:
        """找出所有命中点。

        :param max_count: 最多返回几个；``0`` 表示不限。
        :param min_distance: 非极大值抑制的最小间距（像素），防止同一个图标被算成多个。
        """
        ...

    def compare(
        self,
        image: ImageArray,
        region: Region,
        template: str,
        confidence: float = 0.9,
    ) -> float | None:
        """返回区域与模板的相似度分数（不做阈值判断，交给调用方）。"""
        ...


@runtime_checkable
class TextReader(Protocol):
    """文本识别能力（OCR）。"""

    def locate(
        self,
        image: ImageArray,
        text: str,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
        exact_match: bool = False,
    ) -> list[TextBox]:
        """定位文本。``exact_match=False`` 时按"包含"匹配。"""
        ...

    def read(
        self,
        image: ImageArray,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> str:
        """读出区域内的全部文本，用空格拼接。"""
        ...


# --------------------------------------------------------------------------- #
# 退化实现：没装 OCR 时用它，让上层照常拿到 NOT_FOUND 而不是 ImportError
# --------------------------------------------------------------------------- #
class UnavailableTextReader:
    """占位 TextReader：任何调用都返回空结果，并说明为什么。

    ``Session`` 在没配置 OCR 时会装这个，于是 ``find_text`` 得到
    ``ActionResult.not_found("未启用 OCR")``，而不是抛异常。
    """

    def __init__(self, reason: str = "未安装 / 未启用 OCR 后端") -> None:
        self.reason = reason

    def locate(
        self,
        image: ImageArray,
        text: str,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
        exact_match: bool = False,
    ) -> list[TextBox]:
        return []

    def read(
        self,
        image: ImageArray,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> str:
        return ""

    def __repr__(self) -> str:
        return f"UnavailableTextReader({self.reason!r})"
