"""竞技场 —— 流程图（"做什么、何时换"）。

## 八个节点，一条回边构成循环

```
lobby --(进竞技场)--> create_team --(建队后)--> add_pet --(加伙伴后)--> match
                                                                        |
                                                                  (进选将界面)
                                                                        v
   +------------------------------------------------------------> pick_general
   |                                                                    |
   |                                                              (点了武将)
   |                                                                    v
   |                                                            confirm_general
   |                                                                    |
   |                                                              (点确定)
   |                                                                    v
   |                                                                  fight
   |                                                                    |
   |                                                        (投降确认 -> 结算)
   |                                                                    v
   +------------------（结算确认，回竞技场再开一局）------------------- settle
```

**循环就是最后那条回边**：``settle`` → ``match``，于是又点一次「开始匹配」。
"刷 N 局"因此不需要额外的循环语法 —— 一张图上一条回边，加节点里的一个计数器。

## 每条边都等"下一个状态出现了"才走

用 ``on_page(下一个状态)`` 当条件。**点下去到界面更新有个过渡**，
用画面说话比用时间可靠：状态还没变过来，这一轮就不换节点，下一轮再判 ——
不会出现"以为换段了、其实还在原状态"的错位。

## 桩：两处我没亲眼见过的过渡

1. **``settle`` → ``match``** —— 结算页点完「确认」之后回到哪？玩家没给那张截图。
   这里假设**回到竞技场界面**（加过伙伴、能看到「开始匹配」那个）。
   若实际不是，脚本会卡在 ``settle`` 反复确认，日志里表现为"重定位不到目标" ——
   那时把这条边改成实际去向即可（改一个字符串）。

2. **``confirm_general`` → ``fight``** —— 点完确定到进战斗之间有加载。
   这里直接等 ``fight/hand``（换牌弹窗）出现。若加载慢或中间还有"准备"界面，
   需要补一个状态。超时见 ``pages.WAIT_FIGHT``。

> 这两处**不是猜的代码结构**，只是"不知道实际界面长什么样"。
> 结构上它们就是普通的两条边。
"""

from __future__ import annotations

from gamebot.flow import EdgeKind, EngineOptions, Node, Transition
from gamebot.scenario_spec import ScenarioSpec
from games import on_page

from .bindings import BINDINGS
from .pages import FEATURE_TREE
from .steps import (
    add_pet,
    advance_fight,
    confirm_general,
    create_team,
    enter_jingji,
    finish_round,
    noop,
    pick_general,
    start_match,
)
from .utils import rounds_done

#: 流程图：状态树 + 关联表 + 节点 + 运行选项。**全是数据。**
SCENARIO = ScenarioSpec(
    name="jingji",
    initial="lobby",
    tree=FEATURE_TREE,
    bindings=BINDINGS,
    nodes=(
        # ---------------- 首页 ----------------
        Node(
            "lobby",
            steps=[enter_jingji],
            description="在首页点竞技入口（熊猫头）",
            transitions=[
                Transition(
                    "create_team", on_page("jj/before_create"), 10, "进了竞技场（建队前）"
                ),
            ],
        ),
        # ---------------- 组队三个阶段 ----------------
        # 三个节点而不是一个：每个节点只做一件事，**位置守卫**天然生效
        # （关联表说的状态不对时，这个节点的步骤根本不会被调用）。
        # 合并成一个"点当前能认出的按钮"就把那层守卫丢掉了。
        Node(
            "create_team",
            steps=[create_team],
            description="建队前：点「创建队伍」",
            transitions=[
                Transition(
                    "add_pet", on_page("jj/after_create"), 10, "建队后（按钮变添加伙伴）"
                ),
            ],
        ),
        Node(
            "add_pet",
            steps=[add_pet],
            description="建队后：点「添加伙伴」",
            transitions=[
                Transition("match", on_page("jj/after_add"), 10, "加完伙伴（出现开始匹配）"),
            ],
        ),
        Node(
            "match",
            steps=[start_match],
            description="加完伙伴：点「开始匹配」（+ 提示框善后）",
            transitions=[
                Transition("pick_general", on_page("select/idle"), 10, "进选将界面"),
            ],
        ),
        # ---------------- 选将两步 ----------------
        Node(
            "pick_general",
            steps=[pick_general],
            description="选将：找血条，点一张武将卡",
            transitions=[
                Transition(
                    "confirm_general", on_page("select/picked"), 10, "武将已选（确定变金）"
                ),
            ],
        ),
        Node(
            "confirm_general",
            steps=[confirm_general],
            description="选将：点「确定」进战斗",
            transitions=[
                Transition("fight", on_page("fight/hand"), 10, "进战斗（换牌弹窗）"),
            ],
        ),
        # ---------------- 战斗 ----------------
        Node(
            "fight",
            steps=[advance_fight],
            description="战斗：取消换牌 → 投降 → 确认",
            transitions=[
                Transition("settle", on_page("fight/done"), 10, "投降完成（结算页）"),
            ],
        ),
        Node(
            "settle",
            steps=[finish_round],
            description="结算：点空白区 → 下一步 → 确认（记一局）",
            transitions=[
                # **两条出边，按 priority 分胜负** —— 这就是"循环次数到了就结束"。
                #
                # 优先判"刷够了"：条件看的是黑板里已完成的局数。
                # 用 priority 而不是"先判断再决定"的代码，是因为条件本身
                # 就是可评估的数据（边条件），流程层不需要知道循环这回事。
                Transition(
                    "finish",
                    rounds_done,
                    20,
                    "刷够局数了，收工",
                    kind=EdgeKind.TERMINAL,
                ),
                # **回边** —— 没刷够就回竞技场又点一次「开始匹配」
                Transition("match", on_page("jj/after_add"), 10, "还没刷够，再来一局"),
            ],
        ),
        # ---------------- 收工 ----------------
        Node(
            "finish",
            steps=[noop],
            description="刷完了（终态节点，不做任何事）",
        ),
    ),
    options=EngineOptions(
        tick_interval=0.4,
        # 过场动画本来就会短暂认不出来，给一点宽容期
        unknown_grace=2.0,
        # 连续命中才算"确认进入"，过滤动画里的闪现
        require_confirmed=True,
        # 循环次数由步骤里的计数器决定（见 finish_round），
        # 这里只给一个宽松的总时长上限兜底，防跑飞
        max_runtime=3600.0,
    ),
)
