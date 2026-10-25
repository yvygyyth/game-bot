"""名将杀 —— 游戏包：只导出脚本清单与跨脚本纯函数。

页面、流程、模板都在各脚本目录里。共用动作见 :mod:`.utils`。
"""

from __future__ import annotations

from .scripts import jingji
from .utils import go_back

__all__ = [
    "go_back",
    "jingji",
]
