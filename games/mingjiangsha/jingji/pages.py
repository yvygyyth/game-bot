"""竞技场 —— 状态树。

## 整棵树

```
home                       首页（**分类节点**：容器，不记录信息）
├── lobby                  首页：「竞技」卡上的熊猫头
└── jj                     竞技场（分类节点：三个阶段共用这个界面）
    ├── jj/before_create   「创建队伍」可见
    ├── jj/after_create    「添加伙伴」可见
    ├── jj/after_add       「开始匹配」可见
    ├── select（分类）      选将界面 —— 一个界面、两种样子
    │   ├── select/idle    「确定」是灰的（还没选武将）
    │   └── select/picked  「确定」是金的（选了武将）
    └── fight（分类）       战斗 —— 一个界面、多张快照
        ├── fight/hand     「是否需要更换初始手牌？」（每局开头）
        └── fight/done     结算页的「确认」
```

## 为什么 `select` / `fight` 是分类节点

它们下面挂的"子状态"在**同一个游戏状态**里（同一个界面、同一场战斗），
只是**先后不同的时刻**。这样拆有两个好处：

* **分类节点带 roi**，子状态继承 —— 搜索范围收窄，快而且少误命中；
* 每个时刻有独立的名字，流程图和关联表读起来是"一步步"的。

⚠️ 和"分类节点不记录信息"那条规矩不冲突：**分类节点自己没有 queries**，
记录信息的是叶子（每个叶子一张模板），所以每个叶子仍然需要流程节点认领。

## `fight` 只留两个叶子

玩家给的 15 张截图里有 7 张是战斗过程，但**只有两个值得当状态**：

| 快照 | 当状态吗 | 为什么 |
|---|---|---|
| `zhandou1` 换牌弹窗 | ✅ `fight/hand` | **每局开头**的锚点 —— 关联表靠它把「选完将」接回战斗 |
| `zhandou2` 右上角圆结 | ❌ | 只是"要点的那个东西"，当**点击目标**就够 |
| `zhandou3` 投降菜单 | ❌ | 同上 |
| `zhandou4` 投降确认 | ❌ | 同上 |
| `zhandou5` 点击空白区 | ❌ | 本来就是"点空白处"，用**固定坐标**最稳，不需要模板 |
| `zhandou6` 下一步 | ❌ | 同上 |
| `zhandou7` 结算 | ✅ `fight/done` | "这一局完了"的锚点，也是**循环次数 +1** 的地方 |

**为什么不多做几个状态**：状态越多，识别越频繁、越容易误判，而上面那 5 张
之间**没有分支**（一条直线走到底）。把"直线上的中间态"做成**步骤**而不是**状态**，
是这套设计里最省心智负担的一条 —— 状态只留给"可能停在那、或者可能从别处回来"的地方。

## tip 弹窗为什么**不是**状态

「开始匹配」之后可能弹一个提示框（勾选「本次登录不再提示」+ 确定）。
它不用状态表达，而是塞进「开始匹配」那个步骤里（见 `steps/start_match.py`）：
它只在一个地方出现，而且是"点完按钮**可能**弹"，用状态表达就要多一条边
和一个"弹了就等、没弹就跳过"的判断，反而更绕。

它的识别用**固定坐标**（见 :data:`TIP_CHECKBOX` / :data:`TIP_CONFIRM`）——
复选框太素（灰白方格），裁出来和别处的空白块区分不开，而位置是固定的。

## 阈值

统一 :data:`CONF`。这批模板是 1:1 从玩家截图裁的，同图自己匹配是 1.000。
跨状态的实际分数看干跑时「识图日志」里表 —— 若某两个状态互相超过 0.85，
优先**收窄 roi**，换识别特征（下策）。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import PageGroup, PageLeaf
from gamebot.types import Point, Region

# --------------------------------------------------------------------------- #
# 模板名
#
# **状态锚点**（8 张）：决定"脚本知不知道自己在哪"。
# **点击目标**（6 张）：决定"点哪里"。
# 两组分开列 —— 改名时看得清影响面，也不会把"用来认的图"和"用来点的图"搞混。
#
# 裁切要求和每张图该裁什么：见 templates/README.md。
# --------------------------------------------------------------------------- #
T_LOBBY = "lobby.png"
T_BEFORE_CREATE = "jingji__before_create.png"
T_AFTER_CREATE = "jingji__after_create.png"
T_AFTER_ADD = "jingji__after_add.png"
T_SELECT_IDLE = "select__idle.png"
T_SELECT_PICKED = "select__picked.png"
T_FIGHT_HAND = "fight__hand.png"
T_FIGHT_DONE = "fight__done.png"

T_CLICK_JINGJI = "click__jingji_entry.png"
T_CLICK_SELECT_FIRST = "click__select_first.png"
T_CLICK_FIGHT_MENU = "click__fight_menu.png"
T_CLICK_FIGHT_SURRENDER = "click__fight_surrender.png"
T_CLICK_FIGHT_CONFIRM = "click__fight_confirm.png"
T_CLICK_FIGHT_NEXT = "click__fight_next.png"

# --------------------------------------------------------------------------- #
# 阈值
# --------------------------------------------------------------------------- #
CONF = 0.85
"""状态锚点的阈值。"""

# --------------------------------------------------------------------------- #
# 搜索区域（**客户区坐标**，原点 = 客户区左上角）
#
# 模板就是在这些框里裁出来的，所以框必须包含模板；比模板大一圈是为了
# 容忍界面小幅位移。收窄 roi 是**最有效的提速和防误命中手段**，优先调它。
# --------------------------------------------------------------------------- #
ROI_LOBBY = Region(1120, 380, 620, 500)
"""首页：「竞技」卡那一块。"""

ROI_JJ_BUTTON = Region(2180, 800, 320, 200)
"""竞技场：右侧那个按钮（创建队伍 / 添加伙伴）。

三个阶段共用它 —— 它们只有按钮文字不同，位置一模一样。
"""

ROI_JJ_START = Region(1880, 1120, 480, 180)
"""竞技场：右下「开始匹配」（比上面那个低一截、靠左一点）。"""

ROI_SELECT_CONFIRM = Region(1080, 700, 480, 180)
"""选将：「确定」按钮（灰 / 金两态，位置同一个）。"""

ROI_FIGHT_HAND = Region(920, 540, 440, 200)
"""战斗：换牌弹窗里那行字。"""

ROI_FIGHT_DONE = Region(1150, 1200, 360, 170)
"""战斗：结算页底部的「确认」。"""

ROI_FIGHT_MENU = Region(2360, 40, 160, 140)
"""战斗：右上角那个金色圆结（展开菜单的入口）。"""

ROI_FIGHT_SURRENDER = Region(2360, 260, 160, 140)
"""战斗：展开菜单里的「投降」。"""

ROI_FIGHT_CONFIRM = Region(960, 860, 340, 140)
"""战斗：投降弹窗里的「确认」。"""

ROI_TIP = Region(1000, 780, 420, 220)
"""tip 弹窗的控制区（复选框 + 确定按钮）。

不认图，但要用它判断"这个弹窗到底在不在"（见步骤里的做法）。
"""

# --------------------------------------------------------------------------- #
# 固定坐标（客户区坐标）
# --------------------------------------------------------------------------- #
JINGJI_ENTRY = Point(1365, 585)
"""「竞技」卡上那个熊猫头（宠物头像）的位置。

⚠️ **先移到这儿再点** —— 玩家说明：鼠标不在卡上时熊猫头不完整，
而这个坐标即使熊猫头没完整显示也能点中。所以这一步是"移动 + 点"，
不是"找图再点"：找图会在熊猫头不完整时失败，而它本来就点得中。

这个值取自玩家给的绝对坐标，可能需要按实际效果微调 2~5px。
"""

TIP_CHECKBOX = Point(1148, 874)
"""「本次登录不再提示」复选框的中心（客户区坐标）。"""

TIP_CONFIRM = Point(1085, 951)
"""tip 弹窗里的「确定」。"""

TIP_SETTLE = 0.8
"""点完「开始匹配」之后等弹窗出现的时间（秒）。

tip 是**可能弹也可能不弹**的 —— 不能"等它出现"（没弹就白等满 timeout）。
点完先睡一下让界面反应过来，再看复选框在不在。
"""

TIP_SAMPLE = Region(1125, 858, 45, 37)
"""判"tip 弹了没有"用的取样小块 —— **就是那个复选框的内部**。

弹窗里它是浅色面板上的亮方块，同一个位置在别的界面（刚点完开始匹配时
一定还在竞技场）是深色地形。实测 15 张截图：弹窗的两张都是 219.5，
最接近的非弹窗是 199.4，其余 50~166。

**为什么不用模板匹配**：复选框太素，裁出来的模板在别的界面的空白块上能拿
0.89 分（高于 0.85 阈值）→ 会误判成"弹了"，然后往固定坐标点两下。
亮度判据更钝，但不会骗自己。
"""

TIP_SAMPLE_BRIGHTNESS = 210.0
"""上块取样的亮度阈值（0~255）。取 210 = 199.4 和 219.5 的中间。

**要调就调这个数**：干跑时若发现"没弹窗却去点了两下"，把它调高；
"弹了却没用勾选"，把它调低。"""

FIGHT_BLANK = Point(1341, 1226)
"""战斗结算里「点击空白区域到下一步」要点的位置。

它自己就叫"空白区域"，所以**找图不如点固定坐标** —— 那里本来就没有可认的东西。
这个点落在提示文字上（安全：周围没有可误触的按钮）。
"""

FIGHT_NEXT_SETTLE = 1.2
"""点完空白区之后等「下一步」出现的时间（秒）。结算面板是滑入的。"""

WAIT_FIGHT = 8.0
"""战斗里"等下一个界面出现"的超时（秒）。

比一般的 10 秒短一点：战斗界面的过渡动作很快，超过 8 秒还没变
基本就是上一步没生效，早点失败早重定位比干等有用。
"""

FIGHT_HAND_CANCEL = Point(1513, 815)
"""换牌弹窗里的「取消」（客户区坐标）。

**固定坐标的理由**：它和投降弹窗里的「确认」是同一个组件、同一行位置，
共用识别会互相误命中。而它的位置是固定的（玩家："zhandou1 的界面点那个取消"）。
"""

SELECT_FIRST_CARD = Region(190, 300, 230, 360)
"""选将界面里**第 1 张武将卡**的搜索范围（张飞那张）。

"随便点一个然后点确认" —— 这里固定点第一个。想换武将就改这张卡的
模板（``click__select_first.png``）和这个 roi。
"""

# --------------------------------------------------------------------------- #
# 状态树
# --------------------------------------------------------------------------- #
#: 首页那个状态的 id（流程起点）。
LOBBY = "lobby"

FEATURE_TREE = PageGroup(
    "home",
    name="首页（容器）",
    description="首页这一层：下面是主界面、竞技场等并列状态",
    children=(
        PageLeaf(
            LOBBY,
            name="首页",
            min_stable_frames=2,  # 首页那排卡有滑入动画，等它停稳
            roi=ROI_LOBBY,
            queries=(ImageQuery(T_LOBBY, region=ROI_LOBBY, confidence=CONF),),
            description="首页：「竞技」卡（熊猫头）",
        ),
        PageGroup(
            "jj",
            name="竞技场",
            description="竞技场：组队三个阶段共用这个界面",
            children=(
                # ⚠️ 这个分类节点**不带 roi**，因为三个叶子在**不同位置**：
                # 前两个在右侧按钮区、第三个在右下角那块。
                # 分类节点的 roi 会被整棵子树继承（子框必须在父框内），
                # 带一个框就会把另外两个挡住 —— 装配期那条 StateError 正是
                # 为这种情况写的。三个叶子各自声明自己的 roi。
                PageLeaf(
                    "jj/before_create",
                    name="竞技场 · 建队前",
                    roi=ROI_JJ_BUTTON,
                    queries=(
                        ImageQuery(T_BEFORE_CREATE, region=ROI_JJ_BUTTON, confidence=CONF),
                    ),
                    description="右下角是「创建队伍」",
                ),
                PageLeaf(
                    "jj/after_create",
                    name="竞技场 · 建队后",
                    roi=ROI_JJ_BUTTON,
                    queries=(
                        ImageQuery(T_AFTER_CREATE, region=ROI_JJ_BUTTON, confidence=CONF),
                    ),
                    description="右下角是「添加伙伴」",
                ),
                PageLeaf(
                    "jj/after_add",
                    name="竞技场 · 加完伙伴",
                    roi=ROI_JJ_START,
                    queries=(
                        ImageQuery(T_AFTER_ADD, region=ROI_JJ_START, confidence=CONF),
                    ),
                    description="右下角是「开始匹配」",
                ),
            ),
        ),
        PageGroup(
            "select",
            name="选将",
            roi=ROI_SELECT_CONFIRM,
            description="选将界面：「确定」灰 / 金两态",
            children=(
                PageLeaf(
                    "select/idle",
                    name="选将 · 未选",
                    queries=(ImageQuery(T_SELECT_IDLE, confidence=CONF),),
                    description="「确定」是灰的 —— 还没点武将",
                ),
                PageLeaf(
                    "select/picked",
                    name="选将 · 已选",
                    queries=(ImageQuery(T_SELECT_PICKED, confidence=CONF),),
                    description="「确定」是金的 —— 武将已选",
                ),
            ),
        ),
        PageGroup(
            "fight",
            name="战斗",
            description="战斗：只留两个值得当状态的锚点（见模块 docstring）",
            children=(
                PageLeaf(
                    "fight/hand",
                    name="战斗 · 换牌",
                    roi=ROI_FIGHT_HAND,
                    queries=(ImageQuery(T_FIGHT_HAND, confidence=CONF),),
                    description="「是否需要更换初始手牌？」（每局开头）",
                ),
                PageLeaf(
                    "fight/done",
                    name="战斗 · 结算",
                    roi=ROI_FIGHT_DONE,
                    queries=(ImageQuery(T_FIGHT_DONE, confidence=CONF),),
                    description="结算页的「确认」",
                ),
            ),
        ),
        PageLeaf(
            "over",
            name="刷完了",
            terminal=True,
            roi=ROI_LOBBY,
            queries=(ImageQuery(T_LOBBY, region=ROI_LOBBY, confidence=CONF),),
            description=(
                "局数刷够了，流程到此结束。"
                "它的识别特征**故意和首页一样**（还是那张竞技卡）—— 因为点完"
                "最后那下「确认」之后，游戏就回到能用这张卡认出来的界面上。"
                "它是**终态**：进了就结束流程（不终结的话，流程会卡在这里"
                "反复认出一个不存在的'下一步'）。"
            ),
        ),
    ),
)
"""整棵状态树。

**「开始匹配」按钮既是状态锚点又是点击目标**（``T_AFTER_ADD``）——
这是刻意的：它就是"加完伙伴"这个状态唯一可靠的标志，而点它也是那个状态要做的事。
两处用同一张模板，省一张图，也不会出现"认出来是 A、点的却是 B 的按钮"。
"""
