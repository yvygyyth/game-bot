"""千里单骑 —— 流程图（"做什么、何时换"）。

```
root --(进战役)--> campaign --(进千里单骑)--> open_pick --(打开选将)--> pick_general
                                                                          |
                                                                  (选好了，面板里已选)
                                                                          v
                                                                     leave_pick
                                                                          |
                                                                  (Esc 回主界面)
                                                                          v
                                                                     start_run --(开始挑战)--> flow
continue_run --(继续挑战)--> flow   （已有进行中的局；也可从任意位置被重定位过来）
```

`flow` 是**局内占位**：对应的状态设了 ``terminal=True``，一进入局内画面就停。
局内流程后续再写（加状态、加节点、把 `flow` 的 terminal 去掉）。
"""

from __future__ import annotations

from gamebot.flow import EngineOptions, Node, Transition
from gamebot.scenario_spec import ScenarioSpec
from games import on_page

from .bindings import BINDINGS
from .pages import FEATURE_TREE
from .steps import (
    continue_run,
    enter_campaign,
    enter_qianli,
    leave_pick,
    open_pick,
    pick_general,
    start_run,
)

__all__ = ["SCENARIO"]


SCENARIO = ScenarioSpec(
    name="qianlidanqi",
    initial="root",
    tree=FEATURE_TREE,
    bindings=BINDINGS,
    nodes=(
        Node(
            "root",
            steps=[enter_campaign],
            description="首页：点「战役」卡",
            transitions=[
                Transition("campaign", on_page("campaign"), 10, "进入战役界面"),
            ],
        ),
        Node(
            "campaign",
            steps=[enter_qianli],
            description="战役界面：点「千里单骑」卡",
            transitions=[
                Transition("open_pick", on_page("qianli/select1"), 10, "进入千里单骑"),
                # 已经有进行中的局时，点「千里单骑」会直接到「继续挑战」界面。
                Transition("continue_run", on_page("qianli/select5"), 5, "已有进行中的局"),
            ],
        ),
        Node(
            "open_pick",
            steps=[open_pick],
            description="主界面：点「选择武将」占位卡",
            transitions=[
                Transition("pick_general", on_page("qianli/select2"), 10, "打开选将面板"),
            ],
        ),
        Node(
            "pick_general",
            steps=[pick_general],
            description="选将面板：搜索入参武将 → 点第一个结果",
            transitions=[
                Transition("leave_pick", on_page("qianli/select3"), 10, "武将已选中"),
            ],
        ),
        Node(
            "leave_pick",
            steps=[leave_pick],
            description="已选将：按 Esc 退回主界面",
            transitions=[
                Transition("start_run", on_page("qianli/select4"), 10, "回到主界面"),
            ],
        ),
        Node(
            "start_run",
            steps=[start_run],
            description="主界面：点红色「开始挑战」",
            transitions=[
                Transition("flow", on_page("qianli/flow"), 10, "进入局内"),
            ],
        ),
        Node(
            "continue_run",
            steps=[continue_run],
            description="已有进行中的局：点「继续挑战」，直接进局内",
            transitions=[
                Transition("flow", on_page("qianli/flow"), 10, "继续挑战进局内"),
            ],
        ),
        Node(
            "flow",
            steps=[],
            description="局内（后续实现；状态 terminal，进入即停）",
        ),
    ),
    options=EngineOptions(
        tick_interval=0.4,
        # 点按钮到界面更新有过渡；连续命中再动手
        require_confirmed=True,
        # 只做选将/开局，总时长兜底
        max_runtime=600.0,
    ),
)
