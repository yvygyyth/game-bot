"""状态层 —— 回答"游戏现在处于什么状态 / 我在哪个页面"。

为什么要有独立的状态层（而不是在流程里到处 if）：

* **if 会爆炸**。`if 找得到A: ... elif 找得到B: ...` 在 10 个状态时就开始失控，
  在 30 个状态时没人敢改。
* **状态是共享事实**。执行层的重试策略、流程层的跳转、日志统计都要知道当前在哪。
  让它成为一个被显式维护的值，比每个地方自己算一遍可靠。
* **它把"识别"和"决策"分开了**。状态层只回答"是什么"（可能认不出来），
  流程层才回答"那该怎么办"。这个边界一旦模糊，脚本就会变成一堆特判。

## 两代实现（新的是页面树）

* **新的（推荐）**：:class:`PageTree` + :class:`Page` —— 页面按模块组成一棵树，
  定位时逐层下探，子页面继承父页面的 ROI。游戏界面本来就是分模块的，
  树既省匹配次数又能消歧。见 ``state/page.py`` 的模块 docstring。
* **旧的（扁平清单）**：``StateDefinition`` + ``StateDetector`` —— 所有页面平铺成
  一张列表，每帧全跑一遍。功能上等价（树是它的超集，深度 1 的树就是扁平清单），
  但在 20 个页面以上时匹配开销是树的 5~10 倍，而且拿不到 ROI 继承。
  **保留是为了不打断已有代码，新脚本请直接用页面树。**

数据流（新版）::

    Frame ──PageTree.locate()──> PageMatch ──跟踪层（StateStore）──> 当前页面 + 叠加层
                                     │                                      │
                                     └── 单帧、纯匹配                        └──> 流程层决策
"""

from __future__ import annotations

from .definition import StateDefinition, StateId
from .detector import StateDetector, StateMatch
from .page import (
    UNKNOWN_PAGE,
    Page,
    PageAttempt,
    PageId,
    PageKind,
    PageMatch,
    PageTree,
)
from .snapshot import UNKNOWN_STATE, StateChange, StateSnapshot
from .store import Blackboard, StateStore

__all__ = [
    "UNKNOWN_PAGE",
    "UNKNOWN_STATE",
    "Blackboard",
    "Page",
    "PageAttempt",
    "PageId",
    "PageKind",
    "PageMatch",
    "PageTree",
    "StateChange",
    "StateDefinition",
    "StateDetector",
    "StateId",
    "StateMatch",
    "StateSnapshot",
    "StateStore",
]
