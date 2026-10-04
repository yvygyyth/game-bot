"""流程层 —— 回答"接下来做什么"。

四个组成：

* ``FlowDefinition`` —— 蓝图（状态 + 节点 + 转移 + 运行参数），可由 YAML 加载
* ``FlowNode``       —— 处于某状态时要执行的步骤序列
* ``Transition``     —— 状态之间的跳转规则（含守卫与优先级）
* ``FlowMachine``    —— 记住当前位置、挑转移、执行转移
* ``FlowEngine``     —— 主循环：识别 -> 决策 -> 执行 -> 节奏控制

与状态层的边界：状态层说"现在在战斗中"，流程层说"那就在战斗中反复点技能，
直到出现结算画面才切走"。状态层永远不做决定，流程层永远不认图。
"""

from __future__ import annotations

from .definition import FlowDefinition, UnknownPolicy
from .engine import EngineOptions, FlowEngine, RunReport, StopReason
from .loader import load_flow, parse_definition
from .machine import FlowMachine, TransitionAttempt
from .node import FlowNode
from .transition import Transition, TransitionKind

__all__ = [
    "EngineOptions",
    "FlowDefinition",
    "FlowEngine",
    "FlowMachine",
    "FlowNode",
    "RunReport",
    "StopReason",
    "Transition",
    "TransitionAttempt",
    "TransitionKind",
    "UnknownPolicy",
    "load_flow",
    "parse_definition",
]
