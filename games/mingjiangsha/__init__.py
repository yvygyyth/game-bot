"""名将杀 —— 游戏级定义。

所有名将杀的脚本都从这里拿公共部分：窗口配置、公共页面、公共快捷方法。

**坐标基准是客户区**（``client_area_only: true``），原点在客户区左上角，
不含标题栏和边框。分辨率按实测定死 —— 模板是按这个尺寸录的，
换分辨率所有模板和坐标全部失效。
"""

from __future__ import annotations

from . import shortcuts
from .game import SLUG, SOURCE_SIZE, TEMPLATES_DIR, TITLE, WINDOW_TITLE, base_config, new_tree

__all__ = [
    "SLUG",
    "SOURCE_SIZE",
    "TEMPLATES_DIR",
    "TITLE",
    "WINDOW_TITLE",
    "base_config",
    "new_tree",
    "shortcuts",
]
