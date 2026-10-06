"""竞技场（名将杀）。

## 这个文件里**没有一行组装代码**

建树、加节点、连边、校验都是框架按 :data:`SCENARIO` 里的**数据**做的
（见 :class:`gamebot.feature.FeatureSpec` 与
:class:`gamebot.scenario_spec.ScenarioSpec`）。

原来这里有三个函数 —— ``build_config()`` / ``build_tree()`` / ``build_scenario()``
—— 而它们对每个脚本都长一个样：``for page, parent in ...: tree.add(...)``、
``graph.add_node(...)``、``graph.connect(...)``。那是把"会不会写错"复制到每个
脚本里（忘了 ``add_node`` 就连边，是运行期事故）。现在只剩声明。

## 读代码的顺序

1. 这个文件 —— 脚本叫什么、模板在哪、表单有哪些；
2. :mod:`.graph` —— 有哪些状态、谁先谁后、什么条件换节点；
3. :mod:`.pages` —— 每个状态靠什么认出来（ROI + 模板）；
4. :mod:`.steps` —— 每个节点具体做什么。
"""

from __future__ import annotations

from gamebot.feature import FeatureSpec

from .. import game as _game
from .form import FORM
from .graph import SCENARIO

SLUG = "jingji"
TITLE = "竞技场"
DESCRIPTION = "首页点竞技 → 创建队伍 → 添加伙伴 → 开始匹配"

TEMPLATES_DIR = "games/mingjiangsha/jingji/templates"

#: 这个脚本的**唯一导出**。框架读它，编辑器也看它。
#:
#: 字段全必选：漏一个 ``mypy`` 当场报 ``Missing positional argument``，
#: 名字拼错报 ``did you mean ...?``。所以"结构对不对"在**写的时候**就有反馈 ——
#: 不需要跑起来，也不需要点一个"检查"按钮。
#:
#: ``base_config`` 收的是**游戏级**的东西（窗口标题、分辨率）—— 那是"怎么跑"、
#: 而且与环境相关，所以由游戏级提供，本功能不重复声明。
#:
#: **没有 ``base_tree``。** 页面不再分"游戏级公共"和"功能级"——
#: 那套分层在只有一个功能时只带来负担（理由见 :mod:`games.mingjiangsha.game`）。
#: 状态树整个在 :mod:`.pages` 里，包括它自己的首页那层。
SPEC = FeatureSpec(
    name=f"{_game.SLUG}/{SLUG}",
    title=TITLE,
    slug=SLUG,
    description=DESCRIPTION,
    templates_dir=TEMPLATES_DIR,
    scenario=SCENARIO,
    base_config=_game.base_config,
    form=FORM,
)
"""``form`` 是可选的：不写就是空表单，界面上不显示那一块。

这里直接传 ``FORM`` —— 万一类型不对，``FeatureSpec.__post_init__`` 会当场报。
不需要在这里再 ``isinstance`` 一次：那种"防御式重复检查"掩盖了本该在声明处
就报的错，而且它自己也永远不会触发（真错了上游先炸）。
"""


__all__ = [
    "DESCRIPTION",
    "SLUG",
    "SPEC",
    "TEMPLATES_DIR",
    "TITLE",
]
