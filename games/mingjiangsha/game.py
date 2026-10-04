"""名将杀 —— 游戏级定义与配置。

这里的每个常量都是"这个游戏的所有脚本都依赖的事实"。改之前想清楚：
改了窗口标题，所有脚本都跑不起来；改了分辨率，所有模板和坐标都要重录。
"""

from __future__ import annotations

from pathlib import Path

from gamebot.config.schema import AppConfig, BackendKind
from gamebot.state import PageTree

from .pages import COMMON_PAGES

#: 项目根（games/mingjiangsha/game.py -> 上三级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

SLUG = "mingjiangsha"
TITLE = "名将杀"

WINDOW_TITLE = "名将杀"
"""窗口标题关键字。用 ``gamebot windows`` 确认实际标题再填。"""

SOURCE_SIZE = (1280, 720)
"""**锁定分辨率**（客户区）。

模板是按这个尺寸录的，所以脚本只在这个尺寸下有效。
选一个"游戏能精确设成、且你不会去改"的值 —— 具体怎么定见
``docs/architecture.md`` 的"窗口与分辨率"那一节。
"""

TEMPLATES_DIR = "games/mingjiangsha/templates"
"""游戏级公共模板根。功能级的图放在各自目录里（优先级更高）。"""


def base_config() -> AppConfig:
    """游戏级基础配置。功能脚本在它返回的对象上改自己的部分。"""
    config = AppConfig.defaults()
    config.name = SLUG
    config.screen.backend = BackendKind.WINDOWS
    config.screen.window_title = WINDOW_TITLE
    config.screen.source_size = SOURCE_SIZE
    config.screen.client_area_only = True
    config.vision.templates_dir = TEMPLATES_DIR
    config.paths.root = PROJECT_ROOT
    return config


def new_tree() -> PageTree:
    """新建一棵只含**游戏级公共页面**的树。

    功能脚本拿到它之后挂自己的页面，例如::

        tree = mingjiangsha.new_tree()          # home / 各类弹窗
        tree.add(Page("home/qianli", ...), parent="home")
    """
    tree = PageTree()
    for page, parent in COMMON_PAGES:
        tree.add(page, parent)
    return tree
