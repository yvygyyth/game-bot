"""每日签到 —— 流程（流程对象）。

一条直线，没有分支：

```
open_panel ──进了日常面板──▶ claim ──签完────────▶ （「已签到」是终态，引擎自己停）
```

``claim`` 故意没有出边：签到那一下可能有动画，让它多待几轮没关系，
反正页面一变（出现「已签到」标记）引擎就结束了。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.step import FunctionStep
from gamebot.flow import Graph, Node
from gamebot.types import ActionResult
from games import on_page

if TYPE_CHECKING:
    from gamebot.context import RunContext

T_DAILY_ENTRY = "daily/entry_button.png"
T_SIGN_IN = "daily/sign_in_button.png"


def open_daily_panel(ctx: RunContext) -> ActionResult[Any]:
    """在首页点开日常面板。"""
    return actions.click_image(ctx.session, T_DAILY_ENTRY, confidence=0.85)


def sign_in(ctx: RunContext) -> ActionResult[Any]:
    """点签到按钮。

    只点一下 —— 签到失败（比如已经签过）会让这一步返回 ``not_found``，
    节点就会原地重试到 ``unknown_grace`` 之后按策略处理。
    这种"什么都不做地等"在流程里是很常见的，
    配合页面的 ``terminal`` 就能自然收尾。
    """
    return actions.click_image(ctx.session, T_SIGN_IN, confidence=0.85)


def build_graph() -> Graph:
    graph = Graph(initial="open_panel")

    graph.add_node(
        Node(
            "open_panel",
            page="home",
            steps=[
                FunctionStep(open_daily_panel, name="打开日常面板", templates=(T_DAILY_ENTRY,))
            ],
            cooldown=0.6,
            description="在首页点开日常",
        )
    )
    graph.add_node(
        Node(
            "claim",
            page="home/daily",
            steps=[FunctionStep(sign_in, name="点签到", templates=(T_SIGN_IN,))],
            cooldown=0.8,
            description="在面板上点签到",
        )
    )

    graph.connect(
        "open_panel", "claim", condition=on_page("home/daily"), priority=10, label="面板开了"
    )

    return graph
