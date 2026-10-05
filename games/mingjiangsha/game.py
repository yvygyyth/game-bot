"""名将杀 —— 游戏级定义与配置。"""

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
"""窗口标题关键字。改游戏窗口标题前先 ``gamebot windows``。"""

SOURCE_SIZE = (1918, 1080)
"""**锁定分辨率（客户区）** —— 实测值。

``gamebot capture`` 确认过：窗口在屏幕 (21,49)，客户区 1918x1080，
标题栏和边框都被 ``client_area_only`` 排除掉了。
"""

#: 游戏级模板根（**多个脚本共用**的图放这儿）。
#:
#: 现在这个目录不存在 —— 名将杀只有一个脚本，公共图还没出现。留着它是有意的：
#: 它是"主根"，功能脚本用 ``extra_template_dirs`` 加自己的根、**优先级更高**，
#: 所以主根空着完全能用。等第二个脚本出现、真有共用图了再往里放。
#: （不要为了"目录存在"建一个空目录 —— 那会让人以为里面有东西。）
TEMPLATES_DIR = "games/mingjiangsha/templates"


def base_config() -> AppConfig:
    """游戏级基础配置。功能脚本在它返回的对象上改自己的部分。"""
    config = AppConfig.defaults()
    config.name = SLUG
    config.screen.backend = BackendKind.WINDOWS
    config.screen.window_title = WINDOW_TITLE
    config.screen.source_size = SOURCE_SIZE
    config.screen.client_area_only = True
    config.vision.templates_dir = TEMPLATES_DIR
    # 游戏画面一直在动（待机光效、飘落花瓣），但模板匹配对这类的容忍度很高：
    # 实测同一模板在 2.8 秒内的 5 帧上分数是 0.985~1.000，所以阈值可以给硬一点。
    config.vision.grayscale = True
    config.vision.use_pyramid = True
    config.paths.root = PROJECT_ROOT
    return config


def new_tree() -> PageTree:
    """新建一棵只含**游戏级公共页面**的树。"""
    tree = PageTree()
    for page, parent in COMMON_PAGES:
        tree.add(page, parent)
    return tree
