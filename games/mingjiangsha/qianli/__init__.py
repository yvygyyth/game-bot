"""千里单骑刷本 —— 名将杀的一个脚本功能。

自动刷"千里单骑"：进副本 → 战斗中循环放技能 → 结算领奖 → 回首页再来一轮。

## 这个包里各文件的分工

| 文件 | 放什么 |
|---|---|
| ``pages.py`` | **状态对象**：这个玩法的页面（挂在游戏级 ``home`` 下面） |
| ``graph.py`` | **流程对象**：在哪个页面做什么、什么条件下换目标 |
| ``steps.py`` | 这个玩法**专用**的步骤（通用的在 ``gamebot.execution.step``） |
| ``shortcuts.py`` | 这个玩法专用的快捷方法（游戏级的在 ``mingjiangsha.shortcuts``） |
| ``templates/`` | 这个玩法的**图片资源**（优先级高于游戏级模板） |
| ``__init__.py`` | 把上面几样装配成 ``AppConfig`` + ``Scenario`` |

## 怎么跑

```bash
python -m games list                     # 确认能被发现
python -m games describe mingjiangsha/qianli   # 看页面树和流程图（不连游戏）
python -m games check mingjiangsha/qianli      # 校验定义 + 查模板文件缺哪些
```

（真正的 ``run`` 要等 ``PageTree.locate()`` / ``FlowEngine.tick()`` 实现完。）
"""

from __future__ import annotations

from gamebot.config.schema import AppConfig
from gamebot.flow import EngineOptions, Scenario, UnknownPolicy
from gamebot.state import PageTree

from .. import game as _game
from .graph import build_graph
from .pages import FEATURE_PAGES

SLUG = "qianli"
TITLE = "千里单骑刷本"
DESCRIPTION = "自动刷千里单骑：进本 → 点技能 → 领奖 → 回首页循环"

#: 这个功能的图片资源根。**排在游戏级模板根前面**，所以同名模板会覆盖公共的。
TEMPLATES_DIR = "games/mingjiangsha/qianli/templates"

#: 一轮刷本最多给它多少秒；超了说明卡住了
MAX_RUNTIME = 3600.0


def build_config() -> AppConfig:
    """这个脚本怎么跑：游戏级配置 + 本功能的模板根与节奏。"""
    config = _game.base_config()
    config.name = f"{_game.SLUG}/{SLUG}"
    # 附加模板根优先搜索 —— 于是 "battle/skill.png" 从本功能目录里找，
    # "common/network_error.png" 自动落到游戏级目录
    config.vision.extra_template_dirs = (TEMPLATES_DIR,)
    config.timing.tick_interval = 0.3
    config.timing.wait_timeout = 120.0
    return config


def build_tree() -> PageTree:
    """游戏级公共页面 + 本功能的页面。"""
    tree = _game.new_tree()
    for page, parent in FEATURE_PAGES:
        tree.add(page, parent)
    return tree


def build_scenario() -> Scenario:
    """这个脚本做什么：页面树 + 流程图 + 运行参数。"""
    return Scenario(
        name=f"{_game.SLUG}/{SLUG}",
        tree=build_tree(),
        graph=build_graph(),
        options=EngineOptions(
            tick_interval=0.3,
            max_runtime=MAX_RUNTIME,
            stop_pages=("disconnected",),
            on_unknown=UnknownPolicy.WAIT,
            # 过场动画本来就会短暂认不出来，给一段宽容期
            unknown_grace=1.5,
            # 页面没连续命中够帧数之前不动作 —— 防止动画中间帧误判就开点
            require_confirmed=True,
        ),
    )


__all__ = [
    "DESCRIPTION",
    "MAX_RUNTIME",
    "SLUG",
    "TEMPLATES_DIR",
    "TITLE",
    "build_config",
    "build_graph",
    "build_scenario",
    "build_tree",
]
