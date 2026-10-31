"""名将杀 —— 游戏级公共工具（跨功能共用）。

* :func:`.actions.go_back` —— 返回上一级
* :func:`.buttons.click_button` / :func:`.buttons.find_buttons` ——
  **按按钮家族**找并点击；只比边框环（``BUTTON_RING_INSET`` / ``BUTTON_RING_WIDTH``），
  所以换文字不用改代码
"""

from __future__ import annotations

from .actions import go_back
from .buttons import (
    BUTTON_CONFIDENCE,
    BUTTON_RING_INSET,
    BUTTON_RING_WIDTH,
    ButtonHit,
    click_button,
    find_buttons,
    folder_templates,
    ring_mask,
)

__all__ = [
    "BUTTON_CONFIDENCE",
    "BUTTON_RING_INSET",
    "BUTTON_RING_WIDTH",
    "ButtonHit",
    "click_button",
    "find_buttons",
    "folder_templates",
    "go_back",
    "ring_mask",
]
