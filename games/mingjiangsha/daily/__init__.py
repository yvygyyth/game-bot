"""每日签到领奖 —— 名将杀的一个脚本功能（最简单的例子）。

和"千里单骑"对比着看很有用：那个是**多页面循环**（战斗中要反复点技能），
这个是**一条直线**（打开面板 → 点签到 → 完事就停）。

放在这里除了实用，还演示两件事：

* ``Page(terminal=True)`` —— 进了「已签到」页面流程自动结束，
  所以那个页面**不需要任何节点**，``games check`` 会把它列进
  "没有节点认领的页面（只观察不动作）"；
* 一个功能不需要很多代码 —— 两个页面、两个节点、一条边就够。
"""

from __future__ import annotations

from gamebot.config.schema import AppConfig
from gamebot.flow import EngineOptions, Scenario, UnknownPolicy
from gamebot.state import PageTree

from .. import game as _game
from .graph import build_graph
from .pages import FEATURE_PAGES

SLUG = "daily"
TITLE = "每日签到"
DESCRIPTION = "打开日常面板 → 签到 → 领奖，完事就停"
TEMPLATES_DIR = "games/mingjiangsha/daily/templates"


def build_config() -> AppConfig:
    config = _game.base_config()
    config.name = f"{_game.SLUG}/{SLUG}"
    config.vision.extra_template_dirs = (TEMPLATES_DIR,)
    config.timing.tick_interval = 0.4  # 签到面板不紧张，给宽松点
    return config


def build_tree() -> PageTree:
    tree = _game.new_tree()
    for page, parent in FEATURE_PAGES:
        tree.add(page, parent)
    return tree


def build_scenario() -> Scenario:
    """"已签到"页面标了 ``terminal``，所以不需要写 ``stop_pages``。"""
    return Scenario(
        name=f"{_game.SLUG}/{SLUG}",
        tree=build_tree(),
        graph=build_graph(),
        options=EngineOptions(
            tick_interval=0.4,
            max_runtime=180.0,  # 签到这种活不该超过 3 分钟，超了就是出问题了
            on_unknown=UnknownPolicy.RECOVERY,
            recovery_node="open_panel",  # 认不出来就退回首页重来
            unknown_grace=1.0,
        ),
    )


__all__ = [
    "DESCRIPTION",
    "SLUG",
    "TEMPLATES_DIR",
    "TITLE",
    "build_config",
    "build_graph",
    "build_scenario",
    "build_tree",
]
