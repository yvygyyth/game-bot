"""竞技场（名将杀）—— 刷竞技场：建队 → 匹配 → 选将 → 投降 → 结算，循环 N 局。

## 这个文件里**没有一行组装代码**

建树、加节点、展开边、校验都是框架按 :data:`SCENARIO` 里的**数据**做的
（见 :class:`gamebot.feature.FeatureSpec` 与
:class:`gamebot.scenario_spec.ScenarioSpec`）。

## 读代码的顺序

| 想改什么 | 读 |
|---|---|
| 脚本叫什么、模板在哪、表单有哪些 | **本文件** |
| 每个状态靠什么认出来（模板 + roi + 阈值） | :mod:`.pages` |
| 状态和流程节点怎么对上 | :mod:`.bindings` |
| 有哪些节点、什么条件换节点、循环在哪 | :mod:`.graph` |
| 每个节点具体做什么 | :mod:`.steps` |
| 要裁哪些模板、每张裁什么 | ``templates/README.md`` |
| 首页那个入口为什么用固定坐标 | :mod:`.steps.enter_jingji` |
| 提示弹窗为什么不进状态树 | :mod:`.pages` 的模块 docstring |

## 流程一句话

首页点「竞技」（熊猫头）→ 创建队伍 → 添加伙伴 → 开始匹配（可能弹提示框）
→ 选将（点一张卡 + 确定）→ 战斗里投降 → 结算 → **回到"开始匹配"再刷一局**，
直到刷满 :data:`~.form.ROUNDS_PARAM` 指定的局数。
"""

from __future__ import annotations

from gamebot.feature import FeatureSpec

from .. import game as _game
from .form import FORM
from .graph import SCENARIO

SLUG = "jingji"
TITLE = "竞技场"
DESCRIPTION = "刷竞技场：建队 → 匹配 → 选将 → 投降 → 结算，循环 N 局"

TEMPLATES_DIR = "games/mingjiangsha/jingji/templates"

#: 这个脚本的**唯一导出**。框架读它，编辑器也看它。
#:
#: 字段全必选：漏一个 ``mypy`` 当场报 ``Missing positional argument``，
#: 名字拼错报 ``did you mean ...?`` —— 所以"结构对不对"在**写的时候**就有反馈，
#: 不需要跑起来，也不需要点一个"检查"按钮。
#:
#: ``base_config`` 是**游戏级**的东西（窗口标题、锁定分辨率）—— 它是"怎么跑"、
#: 而且与环境相关，所以由游戏级提供，本功能不重复声明。
#:
#: **没有 ``base_tree``**：页面不分"游戏级公共"和"功能级"了，
#: 状态树整个在 :mod:`.pages` 里（理由见 :mod:`games.mingjiangsha.game`）。
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
