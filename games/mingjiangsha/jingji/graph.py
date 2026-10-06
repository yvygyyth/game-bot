"""竞技场 —— 本功能的流程声明。

**这里只有数据**：四个节点各自做什么、什么条件下从这一个走到下一个。
组装（建树、加节点、展开边、校验）由框架在
:meth:`gamebot.scenario_spec.ScenarioSpec.materialize` 里做。

```
home ──▶ jingji/before_create ──▶ jingji/after_create ──▶ jingji/after_add
（首页）   （点创建队伍）            （点添加伙伴）            （点开始匹配）
```

## 边写在节点自己的 `transitions` 上

**起点不用写**（它就是"我"），所以不可能出现"边表里的起点和节点对不上"。

以前边是一张单独的 ``edges=(("a", "b", {...}), ...)`` 表，同一条边的事实散在两处：

* 起点要写一遍 —— 而它其实就是"哪个节点声明了这条边"；
* 终点的**状态名**在条件里又要写一遍 —— 两遍对不上只能等组装时才发现。

现在起点不在声明里，剩下那两遍是**挨着的**，读的时候能立刻对上。

``Transition`` 的位置参数就是 ``(to, when, priority, label)``。

## 没有通往"匹配中"的边，这是有意的

点完「开始匹配」之后游戏会进入匹配队列，那一页我还没有截图、也就没有页面定义。
所以流程到这里结束：``jingji/after_add`` 是**末梢节点**（没有出边），
队伍三步推完之后它的步骤只会 ``not_found``，于是引擎在连续几轮之后判定
**``no_more_work``（流程走到头了）** 并正常停下。

**这比瞎猜下一个节点要好** —— 不知道去哪就不动，是这套设计一直在守的规矩。
判定细节见 :doc:`docs/state-and-flow.md` 第六节
（``options.dead_end_rounds`` 可以调轮数，0 = 关掉）。

补上匹配页的截图之后，这里加一个 ``PageLeaf``、一个 ``Node``、一条 ``Transition``，
流程就自然接下去了。
"""

from __future__ import annotations

from gamebot.flow import EngineOptions, Node, Transition, UnknownPolicy
from gamebot.scenario_spec import ScenarioSpec
from games import on_page

from .pages import FEATURE_TREE
from .steps import add_pet, create_team, enter_jingji, start_match

#: 这个功能的流程声明。**只有数据** —— 组装交给框架。
#:
#: ## 条件写"下个状态出现了"，不是"点完了"
#:
#: 三条边都用 ``on_page(下一个状态)``。点下去到界面更新有个过渡，用画面说话比用
#: 时间可靠：状态还没变过来，这一轮就不换节点，下一轮再判 ——
#: 不会出现"以为换段了、其实还在原状态"的错位。
#:
#: ``cooldown`` 每一段都给 0.8：点完按钮界面有过渡动画，太密容易在同一处点两下。
SCENARIO = ScenarioSpec(
    name="jingji",
    initial="home",
    tree=FEATURE_TREE,
    nodes=(
        Node(
            "home",
            # **注意是 home/lobby，不是 home** —— home 是分类容器，不记录信息。
            # 把节点挂在容器上会被 validate_binding 拦住（那是对的）。
            page="home/lobby",
            steps=[enter_jingji],
            description="在首页点竞技入口",
            transitions=[
                Transition(
                    "jingji/before_create",
                    on_page("home/jingji/before_create"),
                    10,
                    "竞技场出现（建队前）",
                ),
            ],
        ),
        Node(
            "jingji/before_create",
            page="home/jingji/before_create",
            steps=[create_team],
            description="建队前：点「创建队伍」",
            transitions=[
                Transition(
                    "jingji/after_create",
                    on_page("home/jingji/after_create"),
                    10,
                    "建队后（右下角变成「添加伙伴」）",
                ),
            ],
        ),
        Node(
            "jingji/after_create",
            page="home/jingji/after_create",
            steps=[add_pet],
            description="建队后：点「添加伙伴」",
            transitions=[
                Transition(
                    "jingji/after_add",
                    on_page("home/jingji/after_add"),
                    10,
                    "加完伙伴（右下角变成「开始匹配」）",
                ),
            ],
        ),
        Node(
            "jingji/after_add",
            page="home/jingji/after_add",
            steps=[start_match],
            description="加完伙伴：点「开始匹配」",
            # 没有出边 —— 见模块开头"没有通往匹配中的边"那一节
        ),
    ),
    options=EngineOptions(
        tick_interval=0.4,
        max_runtime=180.0,
        on_unknown=UnknownPolicy.WAIT,
        unknown_grace=1.5,
    ),
)
