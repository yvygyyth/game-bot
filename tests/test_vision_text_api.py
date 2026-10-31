"""图片文字识别的**纯函数**入口（``gamebot.vision.text``）。

这里不测"OCR 准不准"（那要真图 + 真引擎），只钉三件事：

1. 没装 OCR 时**不抛异常**，返回空结果并说明原因；
2. 纯函数能注入自定义 reader（测试/别的引擎），参数原样传下去；
3. 不改传入的图（纯函数的本分）。
"""

from __future__ import annotations

import numpy as np

from gamebot.atomic.vision import TextBox
from gamebot.types import Point, Region
from gamebot.vision.text import (
    clear_cache,
    locate_text,
    ocr_available,
    ocr_backend,
    read_text,
)


class _FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def read(self, image, *, region=None, lang="ch", confidence=0.8):
        self.calls.append(("read", {"region": region, "lang": lang, "confidence": confidence}))
        return "确定"

    def locate(self, image, text, *, region=None, lang="ch", confidence=0.8, exact_match=False):
        self.calls.append(
            ("locate", {"text": text, "region": region, "exact_match": exact_match})
        )
        return [TextBox(point=Point(10, 20), text=text, score=0.9, region=Region(0, 0, 30, 40))]


def test_missing_ocr_degrades_instead_of_raising() -> None:
    clear_cache()
    image = np.zeros((40, 40, 3), np.uint8)

    if not ocr_available():
        assert ocr_backend().startswith("unavailable:")
        assert read_text(image) == ""
        assert locate_text(image, "确定") == []
    else:  # pragma: no cover - 装了 OCR 的机器上
        assert isinstance(read_text(image), str)


def test_read_text_passes_region_and_uses_the_injected_reader() -> None:
    reader = _FakeReader()
    image = np.zeros((40, 40, 3), np.uint8)

    text = read_text(image, Region(1, 2, 3, 4), lang="en", confidence=0.5, reader=reader)

    assert text == "确定"
    assert reader.calls == [
        ("read", {"region": Region(1, 2, 3, 4), "lang": "en", "confidence": 0.5})
    ]


def test_locate_text_returns_boxes_and_passes_text() -> None:
    reader = _FakeReader()
    image = np.zeros((40, 40, 3), np.uint8)

    boxes = locate_text(image, "开始", exact_match=True, reader=reader)

    assert len(boxes) == 1
    assert boxes[0].point == Point(10, 20)
    assert reader.calls[0][1]["text"] == "开始"
    assert reader.calls[0][1]["exact_match"] is True


def test_input_image_is_not_modified() -> None:
    reader = _FakeReader()
    image = np.arange(40 * 40 * 3, dtype=np.uint8).reshape(40, 40, 3)
    before = image.copy()

    read_text(image, reader=reader)
    locate_text(image, "x", reader=reader)

    assert np.array_equal(image, before)
