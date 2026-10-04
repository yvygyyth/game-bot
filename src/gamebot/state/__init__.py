"""状态层 —— 回答"游戏现在处于什么状态"。

为什么要有独立的状态层（而不是在流程里到处 if）：

* **if 会爆炸**。`if 找得到A: ... elif 找得到B: ...` 在 10 个状态时就开始失控，
  在 30 个状态时没人敢改。
* **状态是共享事实**。执行层的重试策略、流程层的跳转、日志统计都要知道当前状态。
  让它成为一个被显式维护的值，比每个地方自己算一遍可靠。
* **它把"识别"和"决策"分开了**。状态层只回答"是什么"（可能认不出来），
  流程层才回答"那该怎么办"。这个边界一旦模糊，脚本就会变成一堆特判。

数据流::

    Frame ──StateDetector.detect()──> StateSnapshot ──StateStore.update()──> StateChange
                                                              │
                                                              └──> 流程层决策
"""

from __future__ import annotations

from .definition import StateDefinition, StateId
from .detector import StateDetector, StateMatch
from .snapshot import UNKNOWN_STATE, StateChange, StateSnapshot
from .store import Blackboard, StateStore

__all__ = [
    "UNKNOWN_STATE",
    "Blackboard",
    "StateChange",
    "StateDefinition",
    "StateDetector",
    "StateId",
    "StateMatch",
    "StateSnapshot",
    "StateStore",
]
