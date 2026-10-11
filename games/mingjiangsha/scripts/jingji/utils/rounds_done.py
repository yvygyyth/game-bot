"""边条件：已经打够局数了吗？

## 为什么循环次数用"边条件"表达，而不是在步骤里 if

流程层要回答的问题是"**何时换目标**"，而"刷够 N 局"正是这个问题的一种。
写成边条件之后：

* 它是**数据**（可评估、可序列化、能在流程图上看出来），
  而不是藏在某个步骤函数里的控制流；
* 「刷够」和「没刷够」是图上**两条并列的出边**，一眼能看出这里有分支 ——
  写在步骤里的话，从图上完全看不出"它会往回走"。

## 两个数字从哪来

* **已刷完几局** -> 黑板 ``fight.rounds``（跑出来的状态）；
* **要刷几局**   -> 运行参数 ``jingji.rounds``（用户填的输入）。

两个数字都在 ``ctx`` 上，但一个是输入、一个是产物，不能混
（``ctx.reset()`` 清黑板、不动参数）。这边的条件只读，不做任何写入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..form import ROUNDS_PARAM
from ..steps.finish_round import ROUNDS_KEY

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["rounds_done"]


def rounds_done(ctx: RunContext) -> bool:
    """已经打够局数了吗？没填/填 0 = 不设上限，一直刷。"""
    target = int(ctx.param(ROUNDS_PARAM, 0) or 0)
    if target <= 0:
        return False
    done = int(ctx.blackboard.get(ROUNDS_KEY, 0))
    return done >= target
