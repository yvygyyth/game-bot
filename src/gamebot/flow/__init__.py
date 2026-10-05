"""流程层 —— 回答"接下来做什么、什么条件下换目标"。

三个组成，各管一件事：

* ``scenario.py`` —— **蓝图**：页面树 + 流程图 + 运行参数，一起校验一起加载。
* ``graph.py``    —— **流程图**：``Node``（做什么）/ ``Edge``（何时换）/
  ``Graph``（蓝图）/ ``GraphCursor``（运行游标 + 冷却次数计数）。
* ``binding.py``  —— **状态 ↔ 节点的关联**：两个层之间唯一的桥。
* ``engine.py``   —— **主循环**：定位 → 校验 → 执行 → 转移 → 节奏与预算。

## 和状态层的边界（这层最重要的纪律）

* 页面树说**"我在哪"**（空间、结构、怎么认出来）；
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
)
from .loader import load_scenario, parse_scenario
from .scenario import EngineOptions, Scenario, UnknownPolicy

__all__ = [
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
    "NodeId",
    "RunReport",
    "Scenario",
    "StateBinding",
    "StopReason",
    "UnknownPolicy",
    "load_scenario",
    "parse_scenario",
]
