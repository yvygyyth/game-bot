"""名将杀 —— 游戏级定义与配置（**只有"怎么跑"，没有"页面"**）。

## 这里**不**放页面

原来这里有个 :func:`new_tree` + ``pages.py``（游戏级公共页面），还有一份
``shortcuts.py``（公共识别逻辑）。那两样都删了：翻了一遍发现"游戏级公共"
当时装的**全是竞技功能的东西** —— 竞技卡、竞技入口的 roi、点它的函数。

用某一个功能的资源去定义"游戏级的东西"是反的：别的功能要认首页，就得反过来
引用竞技场的图。所以全都搬到了 :mod:`games.mingjiangsha.jingji`
（:mod:`.pages` 和 :mod:`.shortcuts`）。

## 留下的是什么

只有**与环境相关、且跨功能真的共用**的东西：

* 窗口标题和**锁定分辨率** —— 换分辨率所有模板和坐标全部失效，是游戏级的；
* 游戏级模板根（多个脚本共用的图放这儿；现在目录不存在，因为只有一个脚本）；
* :func:`base_config` —— 造一份基础配置，功能脚本在它上面改自己的部分。

**判断标准**：一条东西要留在游戏级，得能回答"第二个功能会不会原样用它"。
答不上来就放功能级 —— 提到游戏级是**加法**（多一层需要理解的关系），
放功能级是**默认位置**。

## 以后什么时候建游戏级公共模块

等真有第二个功能、而且某一跳确实一模一样时再提。现在就提是过早抽象 ——
只有一个样本时，你没法知道"共用的那一块"到底是哪一块。
"""

from __future__ import annotations

from pathlib import Path

from gamebot.config.schema import AppConfig, BackendKind

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
