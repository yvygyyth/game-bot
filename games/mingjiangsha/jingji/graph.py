"""竞技场 —— 本功能的流程。

```
home  ──竞技场标题出现──▶  jingji
（首页，点竞技入口）        （竞技场，按顺序推进：创建队伍 → 添加伙伴 → 开始匹配）
```

## 两个节点各管一件事

* ``home`` 管"从首页进竞技场"：步骤是点竞技入口；
* ``jingji`` 管"在竞技场里把队伍流程走完"：步骤是**一个**按顺序探测的成员步骤
  （为什么不是三个节点 —— 见 :mod:`.steps` 的说明）。

## 没有通往"匹配中"的边，这是有意的

点完「开始匹配」之后游戏会进入匹配队列，那一页我还没有截图、也就没有页面定义。
所以流程到这里停住：``jingji`` 节点原地重复，而位置守卫会在页面真的变了之后
把动作拦下来（"节点期望 home/jingji，实测是别的"），日志里留一条警告。

**这比瞎猜下一个节点要好** —— 不知道去哪就不动，是这套设计一直在守的规矩。

补上匹配页的截图之后，这里加一个 ``Page``、一个 ``Node``、一条 ``on_page`` 边，
流程就自然接下去了。
"""

from __future__ import annotations

from gamebot.flow import Graph, Node
from games import on_page

from .steps import AdvanceTeamStep, EnterJingjiStep


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
    graph.add_node(
        Node(
            "jingji",
            page="home/jingji",
            steps=[AdvanceTeamStep()],
            # 冷却给大一点：这一步会连点三个按钮，界面每次都有个过渡，
            # 太密容易在同一个状态上点两下。
            cooldown=0.8,
            description="创建队伍 → 添加伙伴 → 开始匹配",
        )
    )

    graph.connect(
        "home",
        "jingji",
        condition=on_page("home/jingji"),
        priority=10,
        label="竞技场标题出现",
    )

    return graph
