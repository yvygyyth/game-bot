"""名将杀 —— 游戏级定义。

所有名将杀的脚本都从这里拿公共部分：窗口配置、公共页面树、公共快捷方法。

**改游戏级的东西会影响所有脚本**，所以这里只放真正共用的：

* 窗口标题与**锁定分辨率**（见 ``docs/architecture.md``：模板是按固定分辨率录的，
  换了分辨率所有坐标和模板全部失效）
* 公共页面：首页、各类全局弹窗、断线重连
* 公共模板根 ``games/mingjiangsha/templates/``
* 公共快捷方法（:mod:`games.mingjiangsha.shortcuts`）

具体玩法（千里单骑、日常……）各自在子目录里，互不干扰。
"""

from __future__ import annotations

from . import shortcuts
from .game import (
    SLUG,
    SOURCE_SIZE,
    TEMPLATES_DIR,
    TITLE,
    WINDOW_TITLE,
    base_config,
    new_tree,
)

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
