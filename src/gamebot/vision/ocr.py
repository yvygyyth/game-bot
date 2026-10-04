"""OCR 实现 —— 实现 ``TextReader`` 协议。

两个候选，按需要二选一（配置 ``vision.ocr_engine``）：

* ``rapid``      —— RapidOCR（ONNX，离线、中文开箱可用、pip 装完就能跑）
                   适合：中文界面、不想额外装软件。
* ``tesseract``  —— Tesseract（需要单独安装 exe）
                   适合：英文数字为主、已经在用它的场景。

**纯数字识别不要用重量级 OCR**：读血量 / 金币这类固定字体的数字，
先用 ``cv2`` 做二值化 + 模板匹配数字库，比 OCR 快一个数量级也准得多。
OCR 留给"文字内容不确定"的场景（公告、任务名、随机出现的提示）。

坐标约定：``locate`` 返回的 ``Point`` 必须是**源分辨率**坐标，
所以要把 OCR 给的结果框偏移回源坐标 —— 这是最容易错的地方。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..atomic.vision import TextBox
from ..types import Region

if TYPE_CHECKING:
    import numpy as np

__all__ = ["RapidOcrReader", "TesseractReader"]


class RapidOcrReader:
    """RapidOCR 封装。

    :param lang: ``"ch"`` 中英混合 / ``"en"`` 纯英文（更快）。
    :param use_gpu: 是否用 GPU（onnxruntime-gpu 才有意义）。
    :param box_threshold: 文本框置信度阈值。
    """

    def __init__(
        self,
        *,
        lang: str = "ch",
        use_gpu: bool = False,
        box_threshold: float = 0.5,
    ) -> None:
        self.lang = lang
        self.use_gpu = use_gpu
        self.box_threshold = box_threshold
        self._engine: Any = None

    def _load(self) -> Any:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover
            from ..exceptions import BackendUnavailable

            raise BackendUnavailable(
                "未安装 RapidOCR，请执行: uv sync --extra ocr-rapid"
            ) from exc
        if self._engine is None:
            self._engine = RapidOCR()
        return self._engine

    def locate(
        self,
        image: np.ndarray,
        text: str,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
        exact_match: bool = False,
    ) -> list[TextBox]:
        """定位文本。

        注意 OCR 的坐标是相对传入图像的；若传的是裁剪图，
        必须把 ``region`` 的偏移加回去，否则点击会点错位置。
        """
        raise NotImplementedError(
            "待实现: _load().ocr(img) -> [(box, txt, score)] -> 文本比较(包含/相等) -> "
            "box 中心点 + region 偏移 -> TextBox"
        )

    def read(
        self,
        image: np.ndarray,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> str:
        raise NotImplementedError("待实现：ocr 全部文本 -> 按 y 再按 x 排序 -> 空格拼接")

    def warmup(self) -> None:
        """跑一次空图，把模型加载的几百毫秒挪到启动阶段。"""
        raise NotImplementedError("待实现")


class TesseractReader:
    """Tesseract 封装。

    :param tesseract_cmd: tesseract.exe 路径；空串则从 PATH 找。
    :param psm: 页面分割模式。``7``（单行）对游戏 UI 通常最准。
    """

    def __init__(
        self,
        *,
        tesseract_cmd: str = "",
        psm: int = 7,
        lang: str = "eng",
    ) -> None:
        self.tesseract_cmd = tesseract_cmd
        self.psm = psm
        self.lang = lang

    def locate(
        self,
        image: np.ndarray,
        text: str,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
        exact_match: bool = False,
    ) -> list[TextBox]:
        raise NotImplementedError(
            "待实现: pytesseract.image_to_data -> 逐词比较 -> 源坐标 TextBox"
        )

    def read(
        self,
        image: np.ndarray,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> str:
        raise NotImplementedError("待实现：image_to_string -> 清洗换行")
