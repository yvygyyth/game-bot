"""竞技场（名将杀）—— 刷竞技场：建队 → 匹配 → 选将 → 投降 → 结算，循环 N 局。

## 这个文件里**没有一行组装代码**

建树、加节点、展开边、校验都是框架按 :data:`SCENARIO` 里的**数据**做的
（见 :class:`gamebot.feature.FeatureSpec` 与
:class:`gamebot.scenario_spec.ScenarioSpec`）。

## 读代码的顺序

| 想改什么 | 读 |
|---|---|
| 脚本叫什么、表单有哪些 | **本文件** |
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

from ... import game as _game
from .form import FORM
from .graph import SCENARIO

#: 这个脚本的**唯一导出**。``scripts/__init__.py`` 再按功能名转出去。
SPEC = FeatureSpec(
    name=f"{_game.SLUG}/jingji",
    title="竞技场",
    slug="jingji",
    description="刷竞技场：建队 → 匹配 → 选将 → 投降 → 结算，循环 N 局",
    scenario=SCENARIO,
    base_config=_game.base_config,
    form=FORM,
)

__all__ = ["SPEC"]
