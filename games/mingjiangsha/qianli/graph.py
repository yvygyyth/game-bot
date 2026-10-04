"""千里单骑 —— 这个玩法的流程（流程对象）。

## 节点和页面是一对一的

| 节点 | ``page`` | 做什么 |
|---|---|---|
| ``enter`` | ``home`` | 在首页点「千里单骑」入口 |
| ``ready`` | ``home/qianli`` | 清弹窗、检查体力，准备开打 |
| ``fight`` | ``home/qianli/battle`` | 循环放技能（没有出边 = 原地重复，这是对的） |
| ``claim`` | ``home/qianli/battle/result`` | 领奖，然后游戏自己回千里单骑页面 |

``fight`` 节点**故意没有出边**：战斗结束前就该一直待在那里点技能。
``next_node`` 返回 ``None`` 表示"原地不动"，**这不是失败**，是最常见的分支。

## 关于下面这些"看起来多余"的边

引擎每轮会做位置对齐：实测页面和当前节点声明的 ``page`` 不一致时，
自动跳到认领该页面的节点。所以 ``enter -> ready`` 这类边**在运行期等价于
对齐机制**，写出来是为了两件事：

1. 让流程图本身能完整读懂（不依赖引擎的隐式行为）；
2. 万一以后把自动对齐关掉（改成"必须显式写边"），这份图照样能跑。

真正**只能**用边表达的是"同一页面上的多段行为"和"提前离开"，
见文件末尾注释掉的那个例子。
"""

from __future__ import annotations

from typing import Any

from gamebot.execution.step import FunctionStep
from gamebot.flow import Decision, EdgeKind, Graph, Node
from games import on_page

from ..shortcuts import T_POPUP_CLOSE, T_RETRY, T_REWARD_CLAIM, dismiss_popups
from .steps import CastSkillStep, ClaimRewardStep, EnterQianliStep, HasStaminaStep

#: 一次刷本里最多放几次技能，防止在战斗页面无限循环（兜底用）
MAX_CASTS = 120


def _count_casts(ctx: Any) -> None:
    """每轮记一次，配合 :data:`MAX_CASTS` 做兜底。"""
    ctx.blackboard.bump("qianli.casts")


def build_graph() -> Graph:
    """千里单骑的流程图。"""
    graph = Graph(initial="enter")

    graph.add_node(
        Node(
            "enter",
            page="home",
            steps=[EnterQianliStep()],
            cooldown=0.5,
            description="在首页点进千里单骑",
        )
    )
    graph.add_node(
        Node(
            "ready",
            page="home/qianli",
            on_enter=[
                # 包的是普通函数，它用了哪些模板没法自动推断 —— 所以显式声明，
                # 这样 `games check` 才能查出"这几张图还没截"
                FunctionStep(
                    dismiss_popups,
                    name="清掉弹窗",
                    templates=(T_RETRY, T_REWARD_CLAIM, T_POPUP_CLOSE),
                )
            ],
            steps=[HasStaminaStep(minimum=6)],
            cooldown=0.5,
            description="进本前清弹窗、看体力",
        )
    )
    graph.add_node(
        Node(
            "fight",
            page="home/qianli/battle",
            steps=[
                FunctionStep(_count_casts, name="计数"),
                CastSkillStep(cooldown=1.2),
            ],
            description="战斗中循环放技能",
        )
    )
    graph.add_node(
        Node(
            "claim",
            page="home/qianli/battle/result",
            steps=[ClaimRewardStep()],
            cooldown=0.5,
            description="结算领奖",
        )
    )

    # ---- 页面之间的转移（与自动对齐等价，显式写出来）----
    graph.connect(
        "enter", "ready", condition=on_page("home/qianli"), priority=10, label="进本成功"
    )
    graph.connect(
        "ready", "fight", condition=on_page("home/qianli/battle"), priority=10, label="开打"
    )
    graph.connect(
        "fight",
        "claim",
        condition=on_page("home/qianli/battle/result"),
        priority=30,
        label="战斗结束",
    )
    graph.connect(
        "claim",
        "ready",
        condition=on_page("home/qianli"),
        priority=20,
        cooldown=1.0,  # 防抖：结算动画期间别来回跳
        label="领完自动回本页，再来一轮",
    )

    # ---- 兜底：放了太多次技能还没结束，说明卡住了 ----
    graph.connect(
        "fight",
        "ready",
        condition=lambda ctx: bool(ctx.blackboard.get("qianli.casts", 0) >= MAX_CASTS),
        priority=1,
        kind=EdgeKind.FALLBACK,
        label="技能放太多次，判定为卡住，回本页重来",
    )

    return graph


def explain(decision: Decision) -> str:
    """把一次决策写成人能读的一行（调日志格式时改这里）。

    ``Decision`` 里带着**每一条边**的评估痕迹，包括没走成的那些 ——
    "为什么它不动"是靠这个回答的，不是靠加 print。
    """
    if decision.stayed:
        return f"{decision.current} 原地不动"
    return decision.explain()
