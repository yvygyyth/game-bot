"""沙盒测试游戏 —— 游戏级定义。

这个游戏没有"跨脚本共享的公共页面"，所以**不提供 ``new_tree()``** ——
它所有的页面都属于 :mod:`games.testgame.sandbox` 那一个脚本。
（真实游戏像名将杀那样有公共首页/弹窗的，才需要 ``new_tree()``：
见 :func:`games.mingjiangsha.game.new_tree`。）

游戏级只放**这个游戏的所有脚本都会用到**的东西：窗口与分辨率、配置、
以及 :mod:`games.testgame.scene` 那块合成屏幕。
"""

from __future__ import annotations

from pathlib import Path

from gamebot.config.schema import AppConfig, BackendKind

from . import scene

#: 项目根（games/testgame/game.py -> 上三级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

SLUG = "testgame"
TITLE = "沙盒测试游戏"

WINDOW_TITLE = "沙盒（不需要真实窗口）"
"""假游戏没有窗口 —— 后端是 ``fake``，不会碰真实屏幕，也不会碰真实鼠标。"""

SOURCE_SIZE = (scene.SCREEN_WIDTH, scene.SCREEN_HEIGHT)
"""**锁定分辨率**：合成屏幕的尺寸。模板就是照它生成的。"""

TEMPLATES_DIR = "games/testgame/templates"
"""游戏级模板根。合成模板由 ``scene.generate_templates()`` 生成，不入库。"""


def base_config() -> AppConfig:
    """游戏级基础配置。功能脚本在它返回的对象上改自己的部分。"""
    config = AppConfig.defaults()
    config.name = SLUG
    # 假后端：没有任何真实输入通道。跑了最坏也只是写日志。
    config.screen.backend = BackendKind.FAKE
    config.screen.window_title = WINDOW_TITLE
    config.screen.source_size = SOURCE_SIZE
    config.vision.templates_dir = TEMPLATES_DIR
    config.paths.root = PROJECT_ROOT
    return config
