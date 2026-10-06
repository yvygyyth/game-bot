"""执行层 —— 跑步骤，把结果记下来。

## 一个步骤是什么

**就是一个函数**：`(ctx: RunContext) -> ActionResult`。没有基类、没有 `self`。
要带参数就用 `functools.partial`。见 :mod:gamebot.execution.step。

## 这层负责什么

* 按顺序调步骤（:class:Executor）；
* 把每一步的结果记成 :class:StepOutcome（journal + 报告的依据）；
* 失败的步骤存一张当帧（可选）。

## 这层**不**负责什么

* **不重试** —— 失败意味着前提没成立，上层拿实测状态去**重定位**；
* 不做状态判断、不跳流程、不识别游戏；
* 不做 `skip_if` / `precondition` —— 要判断条件就在函数里写 `if`。
"""

from __future__ import annotations

from .builtins import (
    click_image,
    click_point,
    click_text,
    press,
    run_all,
    sequence,
    shoot,
    sleep,
    wait_for,
    wait_gone,
)
from .executor import Executor, ExecutorHooks, StepOutcome
from .journal import Journal, JsonlJournal, NullJournal
from .step import StepFunc, describe_step, step_name

__all__ = [
    "Executor",
    "ExecutorHooks",
    "Journal",
    "JsonlJournal",
    "NullJournal",
    "StepFunc",
    "StepOutcome",
    "click_image",
    "click_point",
    "click_text",
    "describe_step",
    "press",
    "run_all",
    "sequence",
    "shoot",
    "sleep",
    "step_name",
    "wait_for",
    "wait_gone",
]
