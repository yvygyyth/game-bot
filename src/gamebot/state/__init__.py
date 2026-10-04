"""状态层 —— 回答"游戏现在处于哪个页面"。

分成三个文件，各管一件事：

* ``page.py`` —— **页面树**。页面按模块组成一棵树，定位时逐层下探，
  子页面继承父页面的 ROI。只做**单帧**的纯匹配，不持有任何状态。
* ``tracker.py`` —— **跟踪层**。把单帧结果维护成"当前页面 + 连续几帧 + 从何时起"，
  以及状态变更历史。跨帧才能回答的问题都在这里。
* ``store.py`` —— **共享黑板**。脚本自己存东西的地方，框架不解释内容。

为什么要有独立的状态层（而不是在流程里到处 if）：

* **if 会爆炸**。`if 找得到A: ... elif 找得到B: ...` 在 10 个页面时就开始失控，
  30 个时没人敢改。
* **状态是共享事实**。执行层的重试策略、流程层的跳转、日志统计都要知道当前在哪。
* **它把"识别"和"决策"分开了**。状态层只回答"是什么"（可能认不出来），
  流程层才回答"那该怎么办"。这个边界一旦模糊，脚本就会变成一堆特判。

数据流::

    Frame ──PageTree.locate()──> PageMatch ──PageTracker.update()──> PageState
                  │                              │
                  └─ 单帧、纯匹配、无状态          └─ 跨帧、有历史
                                                 │
                                                 └──> PageChange ──> 流程层决策
"""

from __future__ import annotations

from .page import (
    UNKNOWN_PAGE,
    Page,
    PageAttempt,
    PageId,
    PageKind,
    PageMatch,
    PageTree,
)
from .store import Blackboard
from .tracker import PageChange, PageState, PageTracker

__all__ = [
    "UNKNOWN_PAGE",
    "Blackboard",
    "Page",
    "PageAttempt",
    "PageChange",
    "PageId",
    "PageKind",
    "PageMatch",
    "PageState",
    "PageTracker",
    "PageTree",
]
