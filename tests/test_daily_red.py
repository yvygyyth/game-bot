"""每日领奖 —— 红色角标纯函数测试。"""

from __future__ import annotations

import numpy as np

from gamebot.types import Region
from games.mingjiangsha.scripts.daily.red import count_red, has_red


def _image(color: tuple[int, int, int] = (0, 0, 0)) -> np.ndarray:
    image = np.zeros((100, 200, 3), np.uint8)
    image[:, :] = color
    return image


class TestCountRed:
    def test_counts_red_square(self) -> None:
        image = _image()
        image[20:40, 30:50] = (0, 0, 255)  # BGR 红
        assert count_red(image, Region(0, 0, 200, 100)) == 400

    def test_ignores_blue_and_green(self) -> None:
        image = _image((255, 0, 0))  # 蓝
        image[0:20, 0:20] = (0, 255, 0)  # 绿
        assert count_red(image, Region(0, 0, 50, 50)) == 0

    def test_region_outside_image(self) -> None:
        image = _image()
        image[10:30, 10:30] = (0, 0, 255)
        assert count_red(image, Region(500, 500, 10, 10)) == 0

    def test_does_not_modify_image(self) -> None:
        image = _image()
        image[10:30, 10:30] = (0, 0, 255)
        before = image.copy()
        count_red(image, Region(0, 0, 50, 50))
        assert np.array_equal(image, before)


class TestHasRed:
    def test_threshold(self) -> None:
        image = _image()
        image[10:15, 10:15] = (0, 0, 255)  # 25 像素
        assert has_red(image, Region(0, 0, 50, 50), min_pixels=20) is True
        assert has_red(image, Region(0, 0, 50, 50), min_pixels=30) is False

    def test_empty_image(self) -> None:
        assert has_red(None, Region(0, 0, 10, 10)) is False
