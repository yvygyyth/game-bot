"""沙盒测试游戏 —— 游戏级定义。

和名将杀对照着看：那边有 ``pages.py``（公共首页和各类弹窗）和 ``shortcuts.py``
（关弹窗、回主界面），因为它的多个脚本共用这些东西。

沙盒**没有**任何跨脚本共享的东西 —— 它只有一个脚本（:mod:`~games.testgame.sandbox`），
所有页面、步骤、快捷方法都属于那一个脚本。所以游戏级只剩：

* :mod:`~games.testgame.game` —— 窗口、分辨率、配置
* :mod:`~games.testgame.scene` —— 那块用代码画出来的假屏幕（这个游戏的"事实来源"）
* ``templates/`` —— 由 scene 生成的合成模板

**不要为了"看起来对称"硬造一个公共页面出来。** 是否需要一个游戏级 ``pages.py``，
取决于这个游戏是不是真的有多个脚本要共用同一批页面 —— 不是取决于格式好不好看。
"""

from __future__ import annotations

from .game import (
    PROJECT_ROOT,
    SLUG,
    SOURCE_SIZE,
    TEMPLATES_DIR,
    TITLE,
    WINDOW_TITLE,
    base_config,
)

__all__ = [
    "PROJECT_ROOT",
    "SLUG",
    "SOURCE_SIZE",
    "TEMPLATES_DIR",
    "TITLE",
    "WINDOW_TITLE",
    "base_config",
]
