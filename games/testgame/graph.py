"""沙盒测试游戏的流程（流程对象）。

## 节点和页面一对一，边用两种条件

```
home ──menu 在屏幕上──▶ menu ──list 在屏幕上──▶ list
 │                        ◀── menu 在屏幕上 ────┘
 │
 └──battle 在屏幕上──▶ battle ──skill 在屏幕上──▶ skill
                        │  ◀── battle 在屏幕上 ──┘
                        │
                        ├──result 在屏幕上──▶ result ──root 在屏幕上──▶ home
                        └──动作太多次兜底（fallback）──▶ home
```

``popup_confirm`` 和 ``done`` **没有节点**，这是故意的，也是对的：

* ``popup_confirm`` 是叠加层 —— 它不是一个"能待着的位置"，
  而是"主页面之上多了一层"。所以它不该被任何节点认领；
* ``done`` 是终态页面 —— 进了它就结束，不需要动作。

``Scenario.unclaimed_pages()`` 会把这两类排除掉，所以这份定义
"每个页面都有节点认领"是成立的。真实脚本里如果出现别的未认领页面，
``games check`` 会提示 —— 那通常意味着漏写了流程。
"""

from __future__ import annotations

from gamebot.flow import EdgeKind, Graph, Node
from games import on_page, within_page

from .pages import title_of
from .shortcuts import times_acted
from .steps import NoteStep, PageProbeStep

#: 兜底阈值：动作超过这么多次还没离开，判定为卡住
MAX_ACTIONS = 50


def build_graph() -> Graph:
    graph = Graph(initial="home")

    for node_id, page_id in (
        ("home", "root"),
        ("menu", "root/menu"),
        ("list", "root/menu/list"),
        ("battle", "root/battle"),
        ("skill", "root/battle/skill"),
        ("result", "root/result"),
    ):
        graph.add_node(
            Node(
                node_id,
                page=page_id,
                steps=[PageProbeStep(page_id), _action_for(page_id)],
                cooldown=0.2,
                description=title_of(page_id),
            )
        )

    # ---- 页面之间的转移：条件就是"目标页面出现了" ----
    graph.connect("home", "menu", condition=on_page("root/menu"), priority=20, label="开菜单")
    graph.connect("menu", "list", condition=on_page("root/menu/list"), priority=20, label="进列表")
    graph.connect("list", "menu", condition=on_page("root/menu"), priority=20, label="返回菜单")
    graph.connect("home", "battle", condition=on_page("root/battle"), priority=10, label="进战斗")
    graph.connect("battle", "skill", condition=on_page("root/battle/skill"), priority=30)
    graph.connect("skill", "battle", condition=on_page("root/battle"), priority=30)
    graph.connect(
        "battle", "result", condition=on_page("root/result"), priority=40, label="结算出现"
    )

    # 回首页用**祖先语义**：只要还在 root 这棵子树里，"root 在屏幕上"就成立。
    # 和 on_page 的区别见 games/_spec.py —— 精确问"就是它" vs 问"它的 UI 还在吗"。
    graph.connect(
        "result", "home", condition=within_page("root"), priority=10, label="回到首页子树"
    )

    # ---- 兜底：动作太多次还没走，回首页（FALLBACK 语义：优先级最低，只在别的都不成立时用）
    graph.connect(
        "battle",
        "home",
        condition=lambda ctx: times_acted(ctx) >= MAX_ACTIONS,
        priority=1,
        kind=EdgeKind.FALLBACK,
        label="动作次数超限，判定卡住",
    )

    return graph


def _action_for(page_id: str) -> NoteStep:
    """每页配一个"动作"。真实脚本这里是点击，沙盒里只写黑板。"""
    return NoteStep(f"act@{page_id}")
