"""竞技场 —— 流程图（"做什么、何时换"）。

## 一条主线 + 提示框分支 + 一条回边

```
lobby --(进竞技场)--> create_team --(建队后)--> add_pet --(加伙伴后)--> match
                                                                        |
                                          (弹了提示框，还没勾)          |
                                +---------------------------------------+
                                v                                       |
                           tip_check --(勾上了)--> tip_confirm          |
                                                       |                |
                                          (关掉提示框，进选将)          |
                                                       v                |
                                +---------------------------------------+
                                |                                       |
                                |  (没弹提示框，直接进选将)              |
                                v                                       v
                          pick_general --(点卡+确定)--> fight ...
```

提示框是**模态**的、可能不出现：`match` 三条出边，按画面（`tip/unchecked` /
`tip/checked` / `select`）三选一。**没弹框是正常分支**，不是意外。

## 每条边都等"下一个状态出现了"才走

用 ``on_page(下一个状态)`` 当条件。**点下去到界面更新有个过渡**，
用画面说话比用时间可靠：状态还没变过来，这一轮就不换节点，下一轮再判。
（引擎现在会先判边、判不动才重定位 —— 正常换屏不会留下 Recovery。）

## 回边与两处未亲眼见过的过渡

**循环就是最后那条回边**：``victory`` → ``match``。下面是两处"不知道实际界面
长什么样"的假设，结构上就是普通边：

1. **``victory`` → ``match``** —— 完胜页点完「确认」之后回到哪？玩家没给那张截图。
   这里假设**回到竞技场界面**（加过伙伴、能看到「开始匹配」那个）。
   若实际不是，脚本会卡在 ``victory`` 反复确认，日志里表现为"重定位不到目标" ——
   那时把这条边改成实际去向即可（改一个字符串）。

2. **``pick_general`` → ``fight``** —— 点完确定到进战斗之间有加载。
   这里直接等 ``fight/hand``（换牌弹窗）出现。若加载慢或中间还有"准备"界面，
   需要补一个状态。等待超时写在对应 step 的 ``wait_for`` 调用处。

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
    check_tip,
    confirm_tip,
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
            description="加完伙伴：点「开始匹配」",
            transitions=[
                # 弹没弹提示框由**画面**决定，三条边各管一种：
                Transition("tip_check", on_page("tip/unchecked"), 20, "弹了提示框（还没勾）"),
                Transition("tip_confirm", on_page("tip/checked"), 15, "提示框已经勾好了"),
                Transition("pick_general", on_page("select"), 10, "没弹提示框，直接进选将"),
            ],
        ),
        # ---------------- 提示框（模态，可能不出现）----------------
        Node(
            "tip_check",
            steps=[check_tip],
            description="提示框：勾上「本次登录不再提示」",
            transitions=[
                Transition("tip_confirm", on_page("tip/checked"), 10, "勾上了"),
            ],
        ),
        Node(
            "tip_confirm",
            steps=[confirm_tip],
            description="提示框：点「确定」，关掉它",
            transitions=[
                Transition("pick_general", on_page("select/idle"), 10, "进了选将界面"),
            ],
        ),
        # ---------------- 选将 ----------------
        Node(
            "pick_general",
            steps=[pick_general],
            description="选将：找血条点一张卡，再点「确定」",
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
                Transition("victory", on_page("fight/victory"), 10, "投降后完胜画面"),
            ],
        ),
        Node(
            "victory",
            steps=[finish_round],
            description="完胜：点空白 → 下一步 → 确认（记一局）",
            transitions=[
                # **多条出边，按 priority 分胜负** —— 这就是"循环次数到了就结束"。
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
                # 也见过点完确认回首页的（那就在首页再点一次竞技入口）。
                Transition("lobby", on_page("lobby"), 5, "回到首页"),
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
