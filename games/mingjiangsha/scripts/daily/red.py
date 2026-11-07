"""每日领奖 —— 红色角标检测（**脚本级纯函数**）。

入口有没有红点，不能靠“整张入口图模板”判断：红点会把模板打掉。
这里直接在入口区域数**红色像素**：

* 只依赖 numpy 图 + :class:`~gamebot.types.Region`，不碰 Frame/Session；
* 两个 HSV 红色区间（0~10、170~180）；
* 阈值 ``min_pixels`` 由调用方给，默认 30（一个 20px 的红点约 300 像素）。
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from gamebot.types import Region

__all__ = ["count_red", "has_red"]


def _crop(image: Any, region: Region | None) -> np.ndarray:
    if region is None:
        return image
    height, width = image.shape[:2]
    left = max(0, region.x)
    top = max(0, region.y)
    right = min(width, region.x + region.w)
    bottom = min(height, region.y + region.h)
    if right <= left or bottom <= top:
        return image[0:0, 0:0]
    return image[top:bottom, left:right]


def count_red(
    image: Any,
    region: Region | None = None,
    *,
    sat_min: int = 120,
    val_min: int = 100,
) -> int:
    """数区域里的红色像素个数（BGR 图，纯函数，不改原图）。"""
    if image is None:
        return 0
    crop = _crop(image, region)
    if crop.size == 0:
        return 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    mask = (
        ((hue <= 10) | (hue >= 170))
        & (hsv[:, :, 1] >= sat_min)
        & (hsv[:, :, 2] >= val_min)
    )
    return int(np.count_nonzero(mask))


def has_red(
    image: Any,
    region: Region | None = None,
    *,
    min_pixels: int = 30,
    sat_min: int = 120,
    val_min: int = 100,
) -> bool:
    """区域里红色像素是否达到 ``min_pixels`` —— 即“入口有红点”。"""
    return (
        count_red(image, region, sat_min=sat_min, val_min=val_min) >= min_pixels
    )
