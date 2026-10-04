"""OCR 实现 —— 实现 ``TextReader`` 协议。

两个候选，按需要二选一（配置 ``vision.ocr_engine``）：

* ``rapid``      —— RapidOCR（ONNX，离线、中文开箱可用、pip 装完就能跑）
                   适合：中文界面、不想额外装软件。
* ``tesseract``  —— Tesseract（需要单独安装 exe）
                   适合：英文数字为主、已经在用它的场景。

**纯数字识别不要用重量级 OCR**：读血量 / 金币这类固定字体的数字，
先用 ``cv2`` 做二值化 + 模板匹配数字库，比 OCR 快一个数量级也准得多。
OCR 留给"文字内容不确定"的场景（公告、任务名、随机出现的提示）。

## 坐标约定（最容易错的地方）

``locate`` / ``read`` 收到的 ``region`` 是**相对传入图像**的搜索范围。
返回值里的 ``Point`` / ``Region`` 也必须相对**同一张图像** ——
把 OCR 的框加回 ``region`` 偏移是这层的核心工作，加错就会点偏。

换算成源分辨率是 ``Frame`` 的职责，本层不碰。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..atomic.vision import TextBox
from ..exceptions import BackendUnavailable
from ..types import Point, Region

if TYPE_CHECKING:
    import numpy as np

__all__ = ["RapidOcrReader", "TesseractReader"]


def _normalize_region(region: Region | None, shape: tuple[int, ...]) -> Region:
    """把 region 收敛成图像内的有效矩形；None 表示整图。"""
    height, width = shape[0], shape[1]
    if region is None:
        return Region(0, 0, width, height)
    return Region(region.x, region.y, region.w, region.h).clamp(Region(0, 0, width, height))


def _crop(image: np.ndarray, region: Region) -> np.ndarray:
    return image[region.y : region.bottom, region.x : region.right]


class RapidOcrReader:
    """RapidOCR 封装。

    :param lang: ``"ch"`` 中英混合 / ``"en"`` 纯英文（更快）。
        注意 RapidOCR 的模型是固定的中英混合，``lang`` 只用来影响匹配策略，
        不会切换模型 —— 想换模型要换 ``rapidocr`` 的安装包。
    :param use_gpu: 是否用 GPU（需要 onnxruntime-gpu，且装的是对应版本）。
    :param box_threshold: 文本框置信度下限，低于它的框直接丢。
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

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _load(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise BackendUnavailable(
                "未安装 RapidOCR，请执行: uv sync --extra ocr-rapid"
            ) from exc

        params: dict[str, Any] = {}
        if self.use_gpu:
            params["use_cuda"] = True
        try:
            self._engine = RapidOCR(**params) if params else RapidOCR()
        except Exception as exc:
            raise BackendUnavailable(f"RapidOCR 初始化失败: {exc}") from exc
        return self._engine

    def warmup(self) -> None:
        """跑一次空图，把模型加载的几百毫秒挪到启动阶段。

        第一次 OCR 调用会慢到几秒（加载 onnx 模型），放在流程里跑会误判超时。
        """
        import numpy as np

        self._load()(np.zeros((32, 32, 3), dtype=np.uint8))

    def _run(self, image: np.ndarray) -> list[tuple[Any, str, float]]:
        """跑一次 OCR，返回 ``[(四点框, 文本, 置信度), ...]``。

        RapidOCR 的返回形状随版本变化（``(result, elapse)`` 或直接 ``result``），
        这里统一兜住。
        """
        engine = self._load()
        output = engine(image)
        if isinstance(output, tuple) and len(output) == 2:
            output = output[0]
        if not output:
            return []

        items: list[tuple[Any, str, float]] = []
        for entry in output:
            if len(entry) < 3:
                continue
            box, text, score = entry[0], entry[1], entry[2]
            if not text:
                continue
            items.append((box, str(text), float(score)))
        return items

    @staticmethod
    def _box_region(box: Any) -> tuple[Region, Point]:
        """把四点框转成 (外接矩形, 中心点)。"""
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        left, right = int(min(xs)), int(max(xs))
        top, bottom = int(min(ys)), int(max(ys))
        rect = Region(left, top, max(1, right - left), max(1, bottom - top))
        return rect, rect.center

    # ------------------------------------------------------------------ #
    # TextReader 协议
    # ------------------------------------------------------------------ #
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
        search = _normalize_region(region, image.shape)
        if search.is_empty:
            return []

        boxes: list[TextBox] = []
        for box, recognized, score in self._run(_crop(image, search)):
            if score < confidence or score < self.box_threshold:
                continue
            hit = recognized == text if exact_match else text in recognized
            if not hit:
                continue
            rect, center = self._box_region(box)
            boxes.append(
                TextBox(
                    # 加回 region 偏移，坐标重新相对整张传入图像
                    point=center.offset(search.x, search.y),
                    text=recognized,
                    score=score,
                    region=rect.offset(search.x, search.y),
                )
            )
        return boxes

    def read(
        self,
        image: np.ndarray,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> str:
        search = _normalize_region(region, image.shape)
        if search.is_empty:
            return ""

        entries = []
        for box, recognized, score in self._run(_crop(image, search)):
            if score < confidence or score < self.box_threshold:
                continue
            rect, _ = self._box_region(box)
            entries.append((rect, recognized))

        if not entries:
            return ""
        # 按阅读顺序拼接：先上后下，同一行内先左后右。
        # 用"行高的一半"做行聚类阈值，比固定像素更适应不同字号。
        average_height = sum(rect.h for rect, _ in entries) / len(entries)
        row_tolerance = max(1, int(average_height * 0.6))
        entries.sort(key=lambda item: (item[0].y // row_tolerance, item[0].x))
        return " ".join(text for _, text in entries)

    def __repr__(self) -> str:
        return f"RapidOcrReader(lang={self.lang!r}, gpu={self.use_gpu})"


class TesseractReader:
    """Tesseract 封装。

    :param tesseract_cmd: ``tesseract.exe`` 路径；空串则从 PATH 找。
    :param psm: 页面分割模式。``7``（单行）/ ``6``（单块）对游戏 UI 通常最准。
    :param lang: tesseract 语言包，如 ``"eng"`` / ``"eng+chi_sim"``。
    """

    def __init__(
        self,
        *,
        tesseract_cmd: str = "",
        psm: int = 7,
        lang: str = "eng",
        preprocess: bool = True,
    ) -> None:
        self.tesseract_cmd = tesseract_cmd
        self.psm = psm
        self.lang = lang
        self.preprocess = preprocess
        self._pytesseract: Any = None

    def _load(self) -> Any:
        if self._pytesseract is not None:
            return self._pytesseract
        try:
            import pytesseract
        except ImportError as exc:
            raise BackendUnavailable(
                "未安装 pytesseract，请执行: uv sync --extra ocr-tesseract"
            ) from exc
        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
        self._pytesseract = pytesseract
        return pytesseract

    def _prepare(self, image: np.ndarray) -> np.ndarray:
        """灰度高对比预处理。游戏 UI 文字通常是浅色描边 + 深色底，二值化后识别率明显更高。"""
        import cv2

        if not self.preprocess:
            return image
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Otsu 自动阈值：不用为每个界面调参数
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    def _config(self) -> str:
        return f"--psm {self.psm}"

    def _data(self, image: np.ndarray) -> list[dict[str, Any]]:
        """``image_to_data`` 的结果，逐词带上位置与置信度。"""
        pytesseract = self._load()
        prepared = self._prepare(image)
        data = pytesseract.image_to_data(
            prepared, lang=self.lang, config=self._config(), output_type=pytesseract.Output.DICT
        )
        rows: list[dict[str, Any]] = []
        count = len(data.get("text", []))
        for index in range(count):
            word = (data["text"][index] or "").strip()
            if not word:
                continue
            try:
                score = float(data["conf"][index]) / 100.0
            except (TypeError, ValueError):
                score = 0.0
            rows.append(
                {
                    "text": word,
                    "score": score,
                    "x": int(data["left"][index]),
                    "y": int(data["top"][index]),
                    "w": int(data["width"][index]),
                    "h": int(data["height"][index]),
                }
            )
        return rows

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
        search = _normalize_region(region, image.shape)
        if search.is_empty:
            return []

        boxes: list[TextBox] = []
        for row in self._data(_crop(image, search)):
            if row["score"] < confidence:
                continue
            hit = row["text"] == text if exact_match else text in row["text"]
            if not hit:
                continue
            rect = Region(row["x"], row["y"], row["w"], row["h"]).offset(search.x, search.y)
            boxes.append(
                TextBox(point=rect.center, text=row["text"], score=row["score"], region=rect)
            )
        return boxes

    def read(
        self,
        image: np.ndarray,
        *,
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
    ) -> str:
        search = _normalize_region(region, image.shape)
        if search.is_empty:
            return ""
        rows = [row for row in self._data(_crop(image, search)) if row["score"] >= confidence]
        if not rows:
            return ""
        average_height = sum(row["h"] for row in rows) / len(rows)
        tolerance = max(1, int(average_height * 0.6))
        rows.sort(key=lambda row: (row["y"] // tolerance, row["x"]))
        return " ".join(row["text"] for row in rows)

    def __repr__(self) -> str:
        return f"TesseractReader(lang={self.lang!r}, psm={self.psm})"
