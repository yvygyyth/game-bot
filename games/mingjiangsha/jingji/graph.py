"""竞技场 —— 本功能的流程。

现在只有一个节点：``home``，在首页点「竞技」。

**没有出边是对的**：点了之后页面会变成竞技场，但竞技场的页面/节点还没定义，
所以游标会停在 ``home`` 上。这时位置守卫会拦住动作（实测页面 ≠ ``home``），
日志里会出现一条"节点期望页面 home，实测是 home/jingji"的警告 ——
这正是"只拦不跳"该有的表现：**不知道去哪就不动**，而不是瞎猜。

等竞技场的页面补上、再加一条 ``home -> jingji`` 的边，这个流程就往下走了。
"""

from __future__ import annotations

from gamebot.flow import Graph, Node

from .steps import EnterJingjiStep


def build_graph() -> Graph:
    """竞技场的流程图。"""
    graph = Graph(initial="home")

    graph.add_node(
        Node(
            "home",
            page="home",
            steps=[EnterJingjiStep()],
            cooldown=0.5,
            description="在首页点竞技入口",
        )
    )

    return graph
