"""名将杀 —— 游戏级公共工具（跨功能共用）。

* :func:`.actions.go_back` —— 返回上一级
* **四种按钮各一个方法**（底层都走 :func:`.buttons.click_button`，只比边框环）：

  - :func:`.buttons.click_shadow_confirm` —— 金色发光确认（创建队伍 / 添加伙伴 / 确定…）
  - :func:`.buttons.click_pattern_confirm` —— 金色花纹大确认（选将确定 / 开始匹配 / 结算确认…）
  - :func:`.buttons.click_shadow_cancel` —— 青色取消
  - :func:`.buttons.click_qj_next` —— 蓝底金框「下一步」

  写脚本时**直接挑对应的方法**，不用记文件夹名；识别也只在那个家族的模板里找。
  底层还有通用的 ``click_button(ctx, folder)``，只给"确实要按名字动态选"的场合用。
"""

from __future__ import annotations

from .actions import go_back
from .buttons import (
    BUTTON_CONFIDENCE,
    BUTTON_RING_INSET,
    BUTTON_RING_WIDTH,
    ButtonHit,
    click_button,
    click_pattern_confirm,
    click_qj_next,
    click_shadow_cancel,
    click_shadow_confirm,
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
    "click_pattern_confirm",
    "click_qj_next",
    "click_shadow_cancel",
    "click_shadow_confirm",
    "find_buttons",
    "folder_templates",
    "go_back",
    "ring_mask",
]
