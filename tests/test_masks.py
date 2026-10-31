"""遮罩工具（``gamebot.vision.masks``）的单元测试。

它们是纯函数：输入 BGR 图 / 尺寸，输出 0/1 数组。这里只钉"几何/颜色对不对"，
真正的匹配效果由 ``test_button_families`` / 状态测试覆盖。
"""

from __future__ import annotations

import numpy as np

from gamebot.vision.masks import gold_mask, ring_mask


class TestGoldMask:
    def test_keeps_gold_pixels_and_drops_background(self) -> None:
        image = np.zeros((40, 60, 3), np.uint8)
        # 背景：深蓝（不是金色）
        image[:, :] = (120, 40, 20)
        # 中间画一块金色（BGR 金色 ≈ (0, 180, 255)）
        image[15:25, 20:40] = (0, 180, 255)

        mask = gold_mask(image, dilate=0)

        assert mask.shape == (40, 60)
        assert set(np.unique(mask)) <= {0, 1}
        # 金色块内部必须是 1，四角背景必须是 0
        assert mask[20, 30] == 1
        assert mask[0, 0] == 0

    def test_dilate_grows_the_mask(self) -> None:
        image = np.zeros((20, 20, 3), np.uint8)
        image[9:11, 9:11] = (0, 180, 255)

        plain = gold_mask(image, dilate=0)
        grown = gold_mask(image, dilate=2)

        assert grown.sum() > plain.sum()


class TestRingMask:
    def test_ring_has_border_on_and_center_off(self) -> None:
        mask = ring_mask((100, 200), inset=4, width=12)

        assert mask.shape == (100, 200)
        assert mask[10, 10] == 1  # 左上角在环上
        assert mask[50, 100] == 0  # 正中间被遮掉
        assert mask[0, 0] == 0  # 外沿 inset 以内也不算

    def test_too_small_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            ring_mask((10, 10), inset=4, width=12)
