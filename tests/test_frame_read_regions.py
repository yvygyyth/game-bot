"""Frame.read_regions：多区域拼画布一次 OCR 的坐标还原。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from gamebot.atomic.frame import Frame
from gamebot.atomic.vision import TextBox
from gamebot.types import Point, Region


class _BoxReader:
    """不跑 OCR，按画布坐标返回三个框。"""

    def read_boxes(self, image, *, region=None, lang="ch", confidence=0.8):
        assert image.shape[1] == 40 + 10 + 50 + 10 + 60  # 三段 + 两个 gap
        return [
            TextBox(Point(5, 5), "A", 1.0, Region(0, 0, 20, 10)),
            TextBox(Point(55, 5), "B", 1.0, Region(50, 0, 20, 10)),
            TextBox(Point(115, 5), "C", 1.0, Region(110, 0, 20, 10)),
        ]


def _frame() -> Frame:
    image = np.zeros((200, 300, 3), np.uint8)
    session = SimpleNamespace(reader=_BoxReader(), matcher=None, default_confidence=0.8)
    return Frame(image, Region(0, 0, 300, 200), session=session)


def test_regions_are_grouped_and_offset_back_to_source() -> None:
    regions = [
        Region(10, 20, 40, 20),
        Region(100, 30, 50, 20),
        Region(200, 40, 60, 20),
    ]
    result = _frame().read_regions(regions, gap=10)

    assert result.ok
    groups = result.value
    assert [len(group) for group in groups] == [1, 1, 1]
    assert [group[0].text for group in groups] == ["A", "B", "C"]
    assert [group[0].point for group in groups] == [
        Point(15, 25),
        Point(105, 35),
        Point(205, 45),
    ]
    assert groups[0][0].region == Region(10, 20, 20, 10)
    assert groups[2][0].region == Region(200, 40, 20, 10)


def test_empty_region_returns_empty_group() -> None:
    result = _frame().read_regions([Region(500, 500, 40, 20)])
    assert result.ok
    assert result.value == [[]]
