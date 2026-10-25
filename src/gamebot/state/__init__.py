"""状态层 —— 回答"游戏现在处于哪个状态"。

类名仍叫 ``Page`` / ``PageTree`` / ``PageId``（历史命名，配置里也一样），
但这一层在文档和注释里一律叫**状态**："页面"是早期叫法，容易和"网页 / UI 页面"
混淆，而它管的是"游戏现在处于哪个状态"。

分成三个文件，各管一件事：

* ``page.py`` —— **状态树**。状态按模块组成一棵树，定位时逐层下探，
  子状态继承父节点的 ROI。只做**单帧**的纯匹配，不持有任何状态。

  树上只有末梢状态节点写 ``queries``；父节点一律是**分类节点**
  （``kind: group``）—— 它自己不记录信息，也就不参与匹配，只提供 ROI 继承
  和组织结构，定位时直接下探它的子节点。
* ``tracker.py`` —— **跟踪层**。把单帧结果维护成"当前状态 + 连续几帧 + 从何时起"，
  以及状态变更历史。跨帧才能回答的问题都在这里。
* ``blackboard.py`` —— **共享黑板**。脚本在**这一次运行**里存东西的地方，开跑清空。
* ``store.py`` —— **状态仓库**。脚本**跨运行**的记忆（背包、体力、累计局数），
  一个仓库一个 JSON 落盘。和黑板的唯一区别就是寿命：仓库活过这次运行。

定位有两条路径，别混用：快路径 :meth:`~gamebot.state.page.PageTree.locate`
（正常一轮，只探流程层预期的那一页，``expected=``）和慢路径
:meth:`~gamebot.state.page.PageTree.recover`（只在意外时跑，末梢优先 + 逐步扩散）。
每轮都跑慢路径等于每帧探测全树 —— 那和树存在的意义（剪枝）正好相反。

**"重定位到哪个流程节点"不属于这一层。** 这一层只报出锚点字符串，
查表在流程层的 ``flow/binding.py``（关联表）里 —— 状态层不认识"节点 / 边 / 去哪"。

为什么要有独立的状态层（而不是在流程里到处 if）：

* **if 会爆炸**。`if 找得到A: ... elif 找得到B: ...` 在 10 个状态时就开始失控，
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

from .blackboard import Blackboard
from .page import (
    UNKNOWN_PAGE,
    Page,
    PageAttempt,
    PageGroup,
    PageId,
    PageKind,
    PageLeaf,
    PageMatch,
    PageNode,
    PageTree,
)
from .store import Store, StoreChange, StoreManager, StoreSpec, define_store
from .tracker import PageChange, PageState, PageTracker

__all__ = [
    "UNKNOWN_PAGE",
    "Blackboard",
    "Page",
    "PageAttempt",
    "PageChange",
    "PageGroup",
    "PageId",
    "PageKind",
    "PageLeaf",
    "PageMatch",
    "PageNode",
    "PageState",
    "PageTracker",
    "PageTree",
    "Store",
    "StoreChange",
    "StoreManager",
    "StoreSpec",
    "define_store",
]
