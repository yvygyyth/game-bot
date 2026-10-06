"""竞技场 —— 本功能的流程声明。

**这里只有数据**：两个节点各自做什么、什么条件下从首页走到竞技场。
组装（建树、加节点、连边、校验）由框架在
:meth:`gamebot.scenario_spec.ScenarioSpec.materialize` 里做 —— 那是每份声明
都一样的事，不该在每个功能里重写一遍。

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
所以流程到这里结束：``jingji`` 是**末梢节点**（没有出边），队伍三步推完之后
它的步骤只会 ``not_found``，于是引擎在连续几轮之后判定
**``no_more_work``（流程走到头了）** 并正常停下，日志里留一条 warning：

```
节点 'jingji' 没有出边，且连续 3 轮找不到可做的事（右下角三个按钮一个都没看到）
—— 按流程走完处理
```

**这比瞎猜下一个节点要好** —— 不知道去哪就不动，是这套设计一直在守的规矩。
判定细节和"为什么收得这么窄"见 :doc:`docs/state-and-flow.md` 第六节
（``options.dead_end_rounds`` 可以调轮数，0 = 关掉）。

补上匹配页的截图之后，这里加一个 ``Page``、一个 ``Node``、一条 ``on_page`` 边，
流程就自然接下去了（那时 ``jingji`` 有出边了，这条判定也不会再触发）。
"""

from __future__ import annotations

from gamebot.flow import EngineOptions, Node, UnknownPolicy
from gamebot.scenario_spec import ScenarioSpec
from games import on_page

from .pages import FEATURE_PAGES
from .steps import AddPetStep, CreateTeamStep, EnterJingjiStep, StartMatchStep

#: 这个功能的流程声明。**只有数据** —— 组装交给框架。
#:
#: ## 队伍流程现在是**四个节点**（原来是两个）
#:
#: 竞技场的三个阶段从"一个页面里的黑盒步骤"变成了三个真正的状态
#: （见 :mod:`.pages`），所以每个状态各有一个节点认领它 —— 这是硬要求：
#: 没有节点认领的状态，``Scenario.validate()`` 会直接报错（重定位过去无处可去）。
#:
#: ```
#: home ──▶ jingji/before_create ──▶ jingji/after_create ──▶ jingji/after_add
#: （首页）   （点创建队伍）            （点添加伙伴）            （点开始匹配）
#: ```
#:
#: ## 边的条件是"下个状态出现了"，不是"点完了"
#:
#: 四条边都用 ``on_page(...)`` 指**下一个状态**。点下去到界面更新有个过渡，
#: 用画面说话比用时间可靠：状态还没变过来，这一轮就不会换节点，
#: 下一轮再判 —— 而不会出现"以为换段了、其实还在原状态"的错位。
#:
#: ``cooldown`` 每一段都给 0.8：点完按钮界面有过渡动画，太密容易在同一处点两下。
SCENARIO = ScenarioSpec(
    name="jingji",
    initial="home",
    pages=tuple(FEATURE_PAGES),
    nodes=(
        Node(
            "home",
            # **注意是 home/lobby，不是 home** —— home 是分类容器，不记录信息。
            # 把节点挂在容器上会被 validate_binding 拦住（那是对的）。
            page="home/lobby",
            steps=[EnterJingjiStep()],
            cooldown=0.5,
            description="在首页点竞技入口",
        ),
        Node(
            "jingji/before_create",
            page="home/jingji/before_create",
            steps=[CreateTeamStep()],
            cooldown=0.8,
            description="建队前：点「创建队伍」",
        ),
        Node(
            "jingji/after_create",
            page="home/jingji/after_create",
            steps=[AddPetStep()],
            cooldown=0.8,
            description="建队后：点「添加伙伴」",
        ),
        Node(
            "jingji/after_add",
            page="home/jingji/after_add",
            steps=[StartMatchStep()],
            cooldown=0.8,
            description="加完伙伴：点「开始匹配」",
        ),
    ),
    edges=(
        (
            "home",
            "jingji/before_create",
            {
                "condition": on_page("home/jingji/before_create"),
                "priority": 10,
                "label": "竞技场出现（建队前）",
            },
        ),
        (
            "jingji/before_create",
            "jingji/after_create",
            {
                "condition": on_page("home/jingji/after_create"),
                "priority": 10,
                "label": "建队后（右下角变成「添加伙伴」）",
            },
        ),
        (
            "jingji/after_create",
            "jingji/after_add",
            {
                "condition": on_page("home/jingji/after_add"),
                "priority": 10,
                "label": "加完伙伴（右下角变成「开始匹配」）",
            },
        ),
    ),
    options=EngineOptions(
        tick_interval=0.4,
        max_runtime=180.0,
        on_unknown=UnknownPolicy.WAIT,
        unknown_grace=1.5,
    ),
)
