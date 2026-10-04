"""流程层 —— 回答"接下来做什么、什么条件下换目标"。

两个组成，各管一件事：

* ``scenario.py`` —— **蓝图**：页面树 + 流程图 + 运行参数，一起校验一起加载。
* ``graph.py``    —— **流程图**：``Node``（做什么）/ ``Edge``（何时换）/
  ``Graph``（蓝图）/ ``GraphCursor``（运行游标 + 冷却次数计数）。
* ``engine.py``   —— **主循环**：定位 → 对齐 → 执行 → 转移 → 节奏与预算。

## 和状态层的边界

* 页面树说**"我在哪"**（空间、结构、怎么认出来）
* 流程图说**"做什么、何时换"**（时间、控制流）

树永远不做决定，图永远不认图。两者唯一的接口是 ``Node.page`` ——
节点声明"我该在哪个页面上"，实测不符就**一步动作都不做**。
见 ``docs/state-and-flow.md``。
"""

from __future__ import annotations

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
    "StopReason",
    "UnknownPolicy",
    "load_scenario",
    "parse_scenario",
]
