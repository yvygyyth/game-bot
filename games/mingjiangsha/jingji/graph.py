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
from .steps import AdvanceTeamStep, EnterJingjiStep

#: 这个功能的流程声明。**只有数据** —— 组装交给框架。
#:
#: 注意两处"为什么这么写"：
#:
#: * ``cooldown`` 是**节点自己的**节流：``jingji`` 给 0.8 是因为那一步会连点三个
#:   按钮、界面每次都有过渡，太密容易在同一个状态上点两下；
#: * 边的 ``condition`` 用 ``on_page("home/jingji")``：**竞技场标题出现**才换节点，
#:   而不是"点完就换" —— 点下去到渲染出来有个过渡，靠画面说话比靠时间可靠。
SCENARIO = ScenarioSpec(
    name="jingji",
    initial="home",
    pages=tuple(FEATURE_PAGES),
    nodes=(
        Node(
            "home",
            page="home",
            steps=[EnterJingjiStep()],
            cooldown=0.5,
            description="在首页点竞技入口",
        ),
        Node(
            "jingji",
            page="home/jingji",
            steps=[AdvanceTeamStep()],
            cooldown=0.8,
            description="创建队伍 → 添加伙伴 → 开始匹配",
        ),
    ),
    edges=(
        (
            "home",
            "jingji",
            {
                "condition": on_page("home/jingji"),
                "priority": 10,
                "label": "竞技场标题出现",
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
