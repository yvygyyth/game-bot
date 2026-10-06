"""流程层 —— 回答"接下来做什么、什么条件下换目标"。

四个组成，各管一件事：

* ``scenario.py`` —— **蓝图**：状态树 + 流程图 + 运行参数，一起校验一起加载。
  :meth:`~gamebot.flow.scenario.Scenario.validate` 会把"有状态但没有任何节点
  认领"直接判成 ``ConfigError``（重定位到它就无处可去）；
* ``graph.py``    —— **流程图**：``Node``（做什么）/ ``Edge``（何时换）/
  ``Graph``（蓝图）/ ``GraphCursor``（运行游标 + 冷却次数计数）。
  ``Node.page`` 可以不写（不写 = 这个节点不校验状态），``Node.priority``
  决定同一状态被多个节点认领时谁是主节点；
* ``binding.py``  —— **状态 ↔ 节点的关联（关联表）**：两个层之间唯一的桥，
  动前校验 / 重定位去向 / 动后预期三件事全靠它；
* ``engine.py``   —— **主循环**：定位 → 校验 → 执行 → 转移 → 节奏与预算。
  状态对不上时**不是原地拦住，而是重定位**：慢路径找回真实状态 → 关联表查出
  该去哪个节点 → 游标落过去（本轮不执行、下一轮执行），并记一条 ``Recovery``。

## 和状态层的边界（这层最重要的纪律）

* 状态树说**"我在哪"**（空间、结构、怎么认出来）；
* 流程图说**"做什么、何时换"**（时间、控制流）；
* **两者互不认识**：流程层不许出现 ``if ctx.page.id == "..."`` 这种判断，
  状态层不许知道"节点 / 边 / 去哪"。

唯一把它们放在一起的代码是 :mod:`gamebot.flow.binding`，而它只是启动期
算出来的纯数据。三件事都靠它：

1. 重定位之后去哪个节点（状态 → 节点）；
2. 动手之前校验是不是真到了（节点 → 状态）；
3. 节点跑完后当前"预期状态"变成什么（跟游标走）。

见 ``docs/state-and-flow.md``。
"""

from __future__ import annotations

from .binding import StateBinding
from .bindings import Binding, NodeBindings
from .engine import FlowEngine, RunReport, StopReason
from .graph import (
    Decision,
    Edge,
    EdgeAttempt,
    EdgeKind,
    EdgeStats,
    Graph,
    GraphCursor,
    Node,
    NodeId,
    Transition,
)
from .loader import load_scenario, parse_scenario
from .scenario import EngineOptions, Scenario, UnknownPolicy

__all__ = [
    "Binding",
    "Decision",
    "Edge",
    "EdgeAttempt",
    "EdgeKind",
    "EdgeStats",
    "EngineOptions",
    "FlowEngine",
    "Graph",
    "GraphCursor",
    "Node",
    "NodeBindings",
    "NodeId",
    "RunReport",
    "Scenario",
    "StateBinding",
    "StopReason",
    "Transition",
    "UnknownPolicy",
    "load_scenario",
    "parse_scenario",
]
