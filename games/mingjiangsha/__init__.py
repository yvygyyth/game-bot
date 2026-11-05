"""名将杀 —— 游戏包：只导出脚本清单与跨脚本纯函数。

页面、流程、模板都在各脚本目录里。共用动作见 :mod:`.utils`，
跨脚本共用的图见 :mod:`.templates`。
"""

from __future__ import annotations

from .scripts import jingji
from .utils import (
    click_blue_frame,
    click_button,
    click_cyan_glow,
    click_gold_frame,
    click_gold_glow,
    find_buttons,
    go_back,
)

__all__ = [
    "click_blue_frame",
    "click_button",
    "click_cyan_glow",
    "click_gold_frame",
    "click_gold_glow",
    "find_buttons",
    "go_back",
    "jingji",
]
