"""竞技场 —— 本功能的页面。

## 整棵树

```
home                      首页（**分类节点**：不记录信息，只是容器）
├── home/lobby            主界面：中间那排模式卡
└── home/jingji           竞技场（**分类节点**：三个并列阶段）
    ├── home/jingji/before_create   建队前（右下角是「创建队伍」）
    ├── home/jingji/after_create    建队后（右下角是「添加伙伴」）
    └── home/jingji/after_add       加完伙伴（右下角是「开始匹配」）
```

## 为什么 `home` 现在才变成分类节点

它原来是**普通页面**（自己记录"我在首页"），用首页上那张**竞技卡**当特征。
那时只有两个状态，把 `home` 改成分类容器要多一层，不划算 —— 文件末尾原来
记着这件事（"加新状态时顺手做掉"）。

现在做了，而且**必须做**：`home` 原来是"竞技卡那一小块"，而竞技场是**另一个
整屏状态**，不是卡里面的一块。于是子页面 `home/jingji` 的 roi 落在 `home`
的 roi 外面，`add()` 直接报错：

    StateError: 页面 'home/jingji' 的 roi ... 超出了父页面 'home' 的有效 roi

这条报错是对的（那句话写在 ``docs/state-and-flow.md`` 里：roi 是整棵子树的
搜索范围，伸到父页面框外会在"父页面不存在"的地方找特征）。它暴露的是**结构错了**：
"首页"和"竞技场"是**并列的两个状态**，不是包含关系。

所以：`home` 退化成纯分类容器（无 roi、无 queries），
"首页上排着模式卡"这件事交给 :data:`~.home_lobby` 这个状态节点。

### 为什么 `home` 不写 roi

分类节点的 roi 会**整棵子树继承**。给它一个窄 roi（比如竞技卡那块），
竞技场那支就全被框死在卡里了 —— 上面那条报错正是这么来的。
给它 ``None``（= 不限制），每个子状态各自声明自己的范围，这才是对的。

## 三个状态靠什么区分

**靠右下角那个按钮** —— 这是三者唯一的不同：

| 状态 | 右下角 | 模板 |
|---|---|---|
| 建队前 | 创建队伍 | ``create_team.png`` |
| 建队后 | 添加伙伴 | ``add_pet.png`` |
| 加完伙伴 | 开始匹配 | ``start_match.png`` |

阈值 0.85：实测自己图上 1.000，而**按钮之间最高 0.690**（创建队伍 vs 添加伙伴
—— 位置一样、只有文字不同），所以 0.85 留了很大余量。

> **前提**：点掉一个按钮之后它就从画面上消失了。这是观测到的行为，
> 但没在三种状态上逐一截图确认过。若不成立，症状是"卡在第一个状态上反复点击"，
> 那时给后两个状态补一条 ``exclude``（排除前一个按钮）即可。

## 为什么左上角的「竞技场」标题**不再**当页面标识

它原来是对的：标题在三种状态下**都是 1.000**，那时拿它当"我在竞技场"的唯一
特征。但现在要区分三个状态，**它区分不了** —— 三个状态里它一模一样。

所以它下移到 :data:`T_TITLE` 这个常量，留给真正需要"是不是竞技场"的地方用；
页面身份改由"右下角是哪个按钮"承担。

## ROI 为什么框右下角

:data:`JINGJI_TEAM_ROI` 只覆盖右下角那块面板。三个按钮都在这儿，而左上角标题、
左边的三个功能按钮都在框外 —— 收窄搜索范围本身就是最有效的提速手段
（见 :mod:`games.mingjiangsha.shortcuts` 里那段实测）。

分类节点 ``home/jingji`` 把这个 ROI 传给三个子状态，所以子状态不用各写一遍。

## 每个记录信息的状态都必须有流程节点认领

``home/lobby`` 和三个竞技场子状态都会记录信息，所以 ``graph.py`` 里必须
**各有一个节点**（节点的 ``page`` 写它）。漏了的话 ``Scenario.validate()``
直接 ``ConfigError``：重定位到那个状态之后无处可去。分类节点没这个要求。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import Page, PageKind
from gamebot.types import Region

from ..shortcuts import CONF_JINGJI, JINGJI_ROI, T_JINGJI

#: 左上角「竞技场」标题。
#:
#: **它不再是页面标识** —— 三张图里它都是 1.000，区分不了三个子状态。
#: 留着这个常量是给"只要判断是不是竞技场"的场合用（叠加层之类）。
T_TITLE = "jingji/title.png"

#: 三个状态各自的按钮。**顺序即状态顺序**（建队前 → 建队后 → 加完伙伴）。
T_CREATE_TEAM = "jingji/create_team.png"
T_ADD_PET = "jingji/add_pet.png"
T_START_MATCH = "jingji/start_match.png"

#: 三个按钮的搜索区域（客户区坐标）：右下角那块面板。
#: 分类节点持有它，三个子状态继承 —— 子状态不用各写一遍。
JINGJI_TEAM_ROI = Region(1400, 630, 470, 360)

#: 按钮的阈值。实测自己图上 1.000、**按钮之间最高 0.690**
#: （创建队伍 vs 添加伙伴：位置一样、只有文字不同），所以 0.85 很宽裕。
CONF_BUTTON = 0.85

#: 首页那个状态。**分类节点 `home` 不记录信息**，真正记录的是它。
home_lobby = Page(
    "home/lobby",
    name="首页",
    min_stable_frames=2,  # 进首页时那排卡有个滑入动画，等它停稳
    roi=JINGJI_ROI,
    queries=(
        # region 显式给上：页面树定位用它、直接跑 Query 时也用它
        ImageQuery(T_JINGJI, region=JINGJI_ROI, confidence=CONF_JINGJI),
    ),
    description="主界面：中间一排模式卡（竞技 / 房间 / 战没 / 煮酒）",
)
"""``home/lobby`` 而不是 ``home`` 自己记录信息。

"首页上排着哪些卡"是**具体状态**，而 `home` 只是"首页这一层"这个容器 ——
两者分开之后，以后加"房间 / 战没 / 煮酒"这些兄弟状态时不用再动结构。
"""

FEATURE_PAGES: list[tuple[Page, str | None]] = [
    (
        # **纯分类容器**：无 queries、无 roi（理由见模块开头）。
        Page(
            "home",
            name="首页（容器）",
            kind=PageKind.GROUP,
            description="首页这一层：下面是主界面、竞技场等并列状态",
        ),
        None,
    ),
    (home_lobby, "home"),
    (
        # 竞技场也是个分类节点：它自己不记录信息，
        # 只提供"右下角那块面板"的 ROI 给三个阶段继承。
        Page(
            "home/jingji",
            name="竞技场",
            kind=PageKind.GROUP,
            roi=JINGJI_TEAM_ROI,
            description="竞技场：三个并列阶段（建队前 / 建队后 / 加完伙伴）",
        ),
        "home",
    ),
    (
        Page(
            "home/jingji/before_create",
            name="竞技场 · 建队前",
            queries=(ImageQuery(T_CREATE_TEAM, confidence=CONF_BUTTON),),
            description="右下角是「创建队伍」",
        ),
        "home/jingji",
    ),
    (
        Page(
            "home/jingji/after_create",
            name="竞技场 · 建队后",
            queries=(ImageQuery(T_ADD_PET, confidence=CONF_BUTTON),),
            description="右下角是「添加伙伴」",
        ),
        "home/jingji",
    ),
    (
        Page(
            "home/jingji/after_add",
            name="竞技场 · 加完伙伴",
            queries=(ImageQuery(T_START_MATCH, confidence=CONF_BUTTON),),
            description="右下角是「开始匹配」",
        ),
        "home/jingji",
    ),
]
