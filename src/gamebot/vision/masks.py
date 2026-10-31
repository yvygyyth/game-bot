"""遮罩（mask）工具 —— 给"只比一部分像素"的匹配生成 0/1 权重。

为什么需要：模板里常常混着**会变的东西**（半透明底下的卡牌、按钮中间的文字、
背景的插画）。整块比会把那些变化算进分数，导致"同一张图在不同局面下分数乱跳"。
遮罩就是告诉匹配器"只看这些像素"。

现在提供两种：

* :func:`gold_mask` —— 金色/橙色笔画（游戏里最常见的"提示文字"颜色）；
* :func:`ring_mask` —— 按钮的边框环（四边一圈，忽略中间文字）。

两者都是**纯函数**：输入 BGR 图，返回同尺寸 ``uint8``（0/1）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

__all__ = ["gold_mask", "ring_mask"]


def gold_mask(
    image: np.ndarray,
    *,
    hsv_low: tuple[int, int, int] = (10, 80, 120),
    hsv_high: tuple[int, int, int] = (40, 255, 255),
    dilate: int = 1,
) -> np.ndarray:
    """按颜色取"金色笔画"的遮罩。

    游戏里的提示字（"点击空白区域到下一步"）是金色描边、半透明底 ——
    底色随画面变，笔画本身不透明且颜色稳定，所以只保留金色像素。

    :param image: BGR 图（模板或画面）。
    :param hsv_low: HSV 下限（默认覆盖金黄~橙）。
    :param hsv_high: HSV 上限。
    :param dilate: 膨胀像素（盖住抗锯齿/描边）；0 表示不膨胀。
    :return: 同尺寸 ``uint8`` 数组，笔画处 1、其余 0。
    """
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, hsv_low, hsv_high)
    if dilate > 0:
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=dilate)
    return (mask > 0).astype(np.uint8)


def ring_mask(
    shape: tuple[int, int],
    *,
    inset: int = 4,
    width: int = 12,
) -> np.ndarray:
    """按钮的"边框环"遮罩：保留四周 ``width`` 像素、从外沿内缩 ``inset``。

    和 ``games/mingjiangsha/utils/buttons.py`` 里那个是同一套几何 ——
    放在这里是为了以后别的游戏也能直接复用（不依赖名将杀）。

    :param shape: 模板的 ``(高, 宽)``。
    :param inset: 从外沿往里缩多少像素（跳过裁图带进来的背景）。
    :param width: 环的宽度。
    """
    import numpy as np

    height, width_px = shape[:2]
    mask = np.zeros((height, width_px), np.uint8)
    top, bottom = inset, height - inset
    left, right = inset, width_px - inset
    if bottom - top <= 0 or right - left <= 0:
        raise ValueError(f"模板太小（{width_px}x{height}），放不下 inset={inset} 的环")
    if width <= 0 or width > min(bottom - top, right - left):
        raise ValueError(
            f"环宽 {width} 放不进 {width_px}x{height}（inset={inset}）"
        )
    mask[top:bottom, left : left + width] = 1
    mask[top:bottom, right - width : right] = 1
    mask[top : top + width, left:right] = 1
    mask[bottom - width : bottom, left:right] = 1
    return mask
