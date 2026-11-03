"""名将杀 —— 可运行脚本。

每个名字对应一个功能目录里的 ``SPEC``。加脚本时在这里加一行导出。
"""

from __future__ import annotations

from .daily import SPEC as daily
from .jingji import SPEC as jingji
from .qianlidanqi import SPEC as qianlidanqi

__all__ = [
    "daily",
    "jingji",
    "qianlidanqi",
]
