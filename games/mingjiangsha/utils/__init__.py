"""名将杀 —— 游戏级公共工具（跨功能共用）。

* :func:`.actions.go_back` —— 返回上一级
* **每种按钮花纹一个方法**（底层都走 :func:`.buttons.click_button`，只比边框环）：

  - :func:`.buttons.click_gold_glow` —— 金色发光（创建队伍 / 添加伙伴 / 确定…）
  - :func:`.buttons.click_gold_frame` —— 金色花纹大边框（选将确定 / 开始匹配 / 开始对局…）
  - :func:`.buttons.click_cyan_glow` —— 青色发光（取消）

  写脚本时**直接挑对应的方法**，不用关心按钮位置、尺寸、具体文字；
  同一种花纹的不同文字/尺寸版本都放在同一个文件夹里，方法会挨个试。
"""

from __future__ import annotations

from .actions import go_back
from .buttons import (
    BUTTON_CONFIDENCE,
    BUTTON_RING_INSET,
    BUTTON_RING_WIDTH,
    ButtonHit,
    click_button,
    click_cyan_glow,
    click_gold_frame,
    click_gold_glow,
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
    "click_cyan_glow",
    "click_gold_frame",
    "click_gold_glow",
    "find_buttons",
    "folder_templates",
    "go_back",
    "ring_mask",
]
