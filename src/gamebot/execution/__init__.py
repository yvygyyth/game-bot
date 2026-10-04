"""执行层 —— 把"意图"变成"可靠的一次尝试"。

上游（流程层）说"现在该去点开始按钮了"，执行层负责：

* 检查前提条件（按钮出现了吗）
* 重试（没点到再点一次）
* 计时（这次花了多久，超预算了吗）
* 记账（成功 / 失败 / 重试几次，落盘）
* 决定失败的代价（抛异常 / 跳过 / 停下）

下游（原子层）只负责"点一下"这一件事，不管对错。

本层不判断游戏状态 —— 那是状态层的事；也不决定下一步做什么 —— 那是流程层的事。
"""

from __future__ import annotations

from .executor import Executor, ExecutorHooks, StepOutcome
from .journal import Journal, JournalEntry, JsonlJournal, MemoryJournal, NullJournal
from .policy import NO_RETRY, ErrorMode, RetryPolicy, StepPolicy
from .step import (
    CaptureStep,
    ClickImageStep,
    ClickStep,
    ClickTextStep,
    CompositeStep,
    ConditionalStep,
    FunctionStep,
    KeyStep,
    QueryStep,
    Step,
    WaitStep,
)

__all__ = [
    "NO_RETRY",
    "CaptureStep",
    "ClickImageStep",
    "ClickStep",
    "ClickTextStep",
    "CompositeStep",
    "ConditionalStep",
    "ErrorMode",
    "Executor",
    "ExecutorHooks",
    "FunctionStep",
    "Journal",
    "JournalEntry",
    "JsonlJournal",
    "KeyStep",
    "MemoryJournal",
    "NullJournal",
    "QueryStep",
    "RetryPolicy",
    "Step",
    "StepOutcome",
    "StepPolicy",
    "WaitStep",
]
