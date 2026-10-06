"""名将杀 —— 游戏级定义（**只有"怎么跑"**）。

所有名将杀的脚本都从这里拿公共部分：窗口配置、分辨率、基础配置。

**这里没有页面，也没有识别逻辑。** 原来有（``pages.py`` 的游戏级公共页面 +
``shortcuts.py`` 的公共识别方法），翻了一遍发现"游戏级公共"当时装的全是竞技
功能的东西。现在那些都在 :mod:`games.mingjiangsha.jingji` 里。
理由和判断标准见 :mod:`games.mingjiangsha.game`。

**坐标基准是客户区**（``client_area_only: true``），原点在客户区左上角，
不含标题栏和边框。分辨率按实测定死 —— 模板是按这个尺寸录的，
换分辨率所有模板和坐标全部失效。
"""

from __future__ import annotations

from .game import SLUG, SOURCE_SIZE, TEMPLATES_DIR, TITLE, WINDOW_TITLE, base_config

__all__ = [
    "SLUG",
    "SOURCE_SIZE",
    "TEMPLATES_DIR",
    "TITLE",
    "WINDOW_TITLE",
    "base_config",
]
