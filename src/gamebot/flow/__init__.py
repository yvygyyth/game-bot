"""流程层 —— 回答"接下来做什么、什么条件下换目标"。

## 两代实现（新的是流程图）

* **新的（推荐）**：:class:`Graph` + :class:`Node` + :class:`Edge` +
  :class:`GraphCursor` —— 蓝图（``Graph``）和运行状态（``GraphCursor``）分开，
  边条件优先用可配置的 ``Query``，节点做的事是 ``Step`` 序列（带重试/超时/记账）。
  节点用 ``Node.page`` 声明"我该在哪个页面上"，**实际页面不符就拒绝执行**。
  见 ``flow/graph.py`` 的模块 docstring。
* **旧的**：``FlowDefinition`` + ``FlowNode`` + ``Transition`` + ``FlowMachine`` ——
  同一套概念但蓝图和游标混在一起（``FlowMachine`` 既是图又存计数），
  而且没有和页面树结合的口子。**保留是为了不打断已有代码。**

## 和状态层的边界

* 页面树说**"我在哪"**（空间、结构、怎么认出来）
* 流程图说**"做什么、何时换"**（时间、控制流）

树永远不做决定，图永远不认图。两者唯一的接口是 ``Node.page`` ——
见 ``docs/state-and-flow.md``。

## 引擎

:class:`FlowEngine` 是主循环：定位页面 → 决定下一步 → 执行步骤 → 控制节奏与预算。
它属于两代实现共用的一层（``tick()`` 还没实现）。
"""

from __future__ import annotations

from .definition import FlowDefinition, UnknownPolicy
from .engine import EngineOptions, FlowEngine, RunReport, StopReason
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
from .loader import load_flow, parse_definition
from .machine import FlowMachine, TransitionAttempt
from .node import FlowNode
from .transition import Transition, TransitionKind

__all__ = [
    "Decision",
    "Edge",
    "EdgeAttempt",
    "EdgeKind",
    "EdgeStats",
    "EngineOptions",
    "FlowDefinition",
    "FlowEngine",
    "FlowMachine",
    "FlowNode",
    "Graph",
    "GraphCursor",
    "Node",
    "NodeId",
    "RunReport",
    "StopReason",
    "Transition",
    "TransitionAttempt",
    "TransitionKind",
    "UnknownPolicy",
    "load_flow",
    "parse_definition",
]
