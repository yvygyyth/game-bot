"""图片文字识别（OCR）—— **纯函数**入口，不依赖 Frame / Session。

写脚本时经常只想"从这张图里读出文字"，不需要整个运行期上下文。
这个模块就是那几个公共方法：

```python
from gamebot.vision.text import read_text, locate_text, ocr_available

text  = read_text(image)                        # 整图
text  = read_text(image, Region(10, 10, 200, 40))   # 只读一块
hits  = locate_text(image, "确定")               # 找文字，返回 TextBox 列表
if ocr_available():
    ...
```

**纯函数的意思**：输入一张 numpy 图（BGR），输出结果；不读写运行期状态、
不改传入的图。OCR 引擎是**懒加载**的（第一次调用才初始化），
测试/特殊场景可以用 ``reader=`` 直接注入一个实现了 ``TextReader`` 的对象。

没装 OCR 时**不抛异常**：:func:`read_text` 返回空串、:func:`locate_text`
返回空列表、:func:`ocr_available` 返回 False；:func:`ocr_backend` 说明原因。
这样"没装 OCR"和"画面上没有那行字"在调用方看来是两件事 —— 后者会先
``ocr_available()`` 判一下。

## 引擎从哪来

和 :func:`gamebot.bootstrap.build_reader` 同一套选择逻辑（``auto`` 下
RapidOCR 优先、其次 Tesseract）。区别只是这里不带 recorder —— 纯函数
不需要把识别记录写进界面。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..atomic.vision import TextBox, UnavailableTextReader

if TYPE_CHECKING:
    import numpy as np

    from ..atomic.vision import TextReader
    from ..types import Region

__all__ = [
    "clear_cache",
    "locate_text",
    "ocr_available",
    "ocr_backend",
    "read_text",
]

#: 按引擎缓存 reader：OCR 初始化很贵，纯函数也不该每次 new 一个。
_READERS: dict[str, TextReader] = {}


def _reader(engine: str = "auto") -> TextReader:
    """拿一个 reader（懒加载 + 按引擎缓存）。"""
    cached = _READERS.get(engine)
    if cached is not None:
        return cached
    # 放在函数里 import：``bootstrap`` 会 import ``vision``，模块级 import 会成环。
    from ..bootstrap import build_reader

    reader = build_reader(engine=engine)
    _READERS[engine] = reader
    return reader


def clear_cache() -> None:
    """清掉缓存的 reader —— 测试用（例如换了 OCR 引擎或想验证懒加载）。"""
    _READERS.clear()


def ocr_available(engine: str = "auto") -> bool:
    """这台机器上 OCR 到底能不能用（没装 → False，不抛异常）。"""
    return not isinstance(_reader(engine), UnavailableTextReader)


def ocr_backend(engine: str = "auto") -> str:
    """当前会用的 OCR 后端名；不可用时返回原因（给人看）。"""
    reader = _reader(engine)
    if isinstance(reader, UnavailableTextReader):
        return f"unavailable: {reader.reason}"
    return type(reader).__name__


def read_text(
    image: np.ndarray,
    region: Region | None = None,
    *,
    lang: str = "ch",
    confidence: float = 0.8,
    engine: str = "auto",
    reader: TextReader | None = None,
) -> str:
    """读出图（或其中一块）里的全部文字，用空格拼接。

    :param image: BGR 图（和 ``Frame.to_numpy()`` 一样）。
    :param region: 相对这张图的搜索范围；None = 整图。
    :param reader: 注入一个 ``TextReader``（测试/自定义引擎用）。
    :return: 识别到的文字；没装 OCR 或没识别到都是 ``""``。
    """
    target = reader or _reader(engine)
    return target.read(image, region=region, lang=lang, confidence=confidence)


def locate_text(
    image: np.ndarray,
    text: str,
    region: Region | None = None,
    *,
    lang: str = "ch",
    confidence: float = 0.8,
    exact_match: bool = False,
    engine: str = "auto",
    reader: TextReader | None = None,
) -> list[TextBox]:
    """找出文字在图上的位置。

    :param exact_match: False（默认）按"包含"匹配；True 要求整段相等。
    :return: 命中列表（``TextBox.point`` 是文字框中心，相对传入的图）；
        没装 OCR 或没找到就是空列表。
    """
    target = reader or _reader(engine)
    return list(
        target.locate(
            image,
            text,
            region=region,
            lang=lang,
            confidence=confidence,
            exact_match=exact_match,
        )
    )
