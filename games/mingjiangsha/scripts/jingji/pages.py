"""竞技场 —— 状态树。

```
home
├── lobby                  首页：竞技卡（熊猫头）
└── jj                     竞技场（分类）
    ├── jj/before_create   「创建队伍」
    ├── jj/after_create    「添加伙伴」
    ├── jj/after_add       「开始匹配」
    ├── select（分类）
    │   ├── select/idle    「确定」灰
    │   └── select/picked  「确定」金
    └── fight（分类）
        ├── fight/hand     换牌弹窗
        └── fight/done     结算「确认」
```

`select` / `fight` 是分类节点：同一界面的先后时刻，各挂独立叶子。
分类节点自己没有 queries，信息记在叶子上。

## ROI 是量出来的，不是猜的

每个叶子都带 `roi`：**源分辨率 2560x1369 下的实测位置 + 80~100px 余量**。
全屏定位一次约 2.6s，收进 ROI 后只要几毫秒；多给的余量足够容忍
"模板裁得紧一点 / 客户区差一两个像素"。

换分辨率或窗口大小后，ROI 要按新截图重新量（模板也要重裁），
否则会出现"明明在屏幕上却定位不到"。

战斗中间那几张快照（圆结、投降、空白区…）没有分支，做成步骤即可；
状态只留给可能停住或从别处回来的锚点。提示框也是状态（`tip/unchecked` /
`tip/checked`），由流程图的边分流（见 `graph.py`）。

模板路径见 :mod:`.templates`。阈值走框架默认。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import PageGroup, PageLeaf
from gamebot.types import Region

from .templates import (
    T_AFTER_ADD,
    T_AFTER_CREATE,
    T_BEFORE_CREATE,
    T_FIGHT_DONE,
    T_FIGHT_HAND,
    T_LOBBY,
    T_SELECT_IDLE,
    T_SELECT_PICKED,
    T_TIP,
    T_TIP_CHECK,
    T_TIP_CHECKED,
)

#: 提示框大致范围（源坐标）：框体（1065x360）+ 复选框都在里面。
#: 提示框是**模态**的 —— 它盖住竞技场时，`jj/after_add` 要被否决（否则
#: 底下那张「开始匹配」还会被认出来，流程会以为没弹框）。
TIP_ROI = Region(720, 500, 1140, 430)

#: 复选框那一小块。**必须单独框住**：整张提示框里还有别的地方长得像灰方块
#: （实测未勾的模板在"已勾"图上、别处能到 0.96），收进这一块就只剩真复选框。
TIP_CHECKBOX_ROI = Region(1080, 790, 150, 140)

FEATURE_TREE = PageGroup(
    "home",
    name="首页（容器）",
    description="首页这一层：下面是主界面、竞技场等并列状态",
    children=(
        PageLeaf(
            "lobby",
            name="首页",
            min_stable_frames=2,  # 首页那排卡有滑入动画，等它停稳
            roi=Region(1110, 700, 470, 300),
            queries=(ImageQuery(T_LOBBY),),
            description="首页：「竞技」卡（熊猫头）",
        ),
        PageGroup(
            "jj",
            name="竞技场",
            description="竞技场：组队三个阶段共用这个界面",
            children=(
                PageLeaf(
                    "jj/before_create",
                    name="竞技场 · 建队前",
                    roi=Region(2140, 780, 390, 230),
                    queries=(ImageQuery(T_BEFORE_CREATE),),
                    description="右下角是「创建队伍」",
                ),
                PageLeaf(
                    "jj/after_create",
                    name="竞技场 · 建队后",
                    roi=Region(2140, 780, 390, 230),
                    queries=(ImageQuery(T_AFTER_CREATE),),
                    description="右下角是「添加伙伴」",
                ),
                PageLeaf(
                    "jj/after_add",
                    name="竞技场 · 加完伙伴",
                    roi=Region(1850, 1070, 520, 260),
                    queries=(ImageQuery(T_AFTER_ADD),),
                    # 提示框盖住这个界面时，"加完伙伴"就不成立（模态弹窗）。
                    exclude=(ImageQuery(T_TIP, region=TIP_ROI),),
                    description="右下角是「开始匹配」；提示框弹着时不算这个状态",
                ),
            ),
        ),
        PageGroup(
            "tip",
            name="提示框",
            description="开始匹配后可能弹的框：复选框未勾 / 已勾两态",
            children=(
                PageLeaf(
                    "tip/unchecked",
                    name="提示框 · 未勾",
                    roi=TIP_ROI,
                    # 框体证明"是这个弹窗"；复选框（自己的小块）证明"勾没勾"。
                    # 阈值显式写 0.9：复选框两态在整框范围里只差 0.87~0.96，
                    # 收到 0.9 才分得开（未勾 1.0 / 勾上 0.70）。
                    confidence=0.9,
                    queries=(
                        ImageQuery(T_TIP),
                        ImageQuery(T_TIP_CHECK, region=TIP_CHECKBOX_ROI),
                    ),
                    description="「本次登录不再提示」没勾",
                ),
                PageLeaf(
                    "tip/checked",
                    name="提示框 · 已勾",
                    roi=TIP_ROI,
                    confidence=0.9,
                    queries=(
                        ImageQuery(T_TIP),
                        ImageQuery(T_TIP_CHECKED, region=TIP_CHECKBOX_ROI),
                    ),
                    description="勾上了，下一步点「确定」",
                ),
            ),
        ),
        PageGroup(
            "select",
            name="选将",
            description="选将界面：「确定」灰 / 金两态",
            children=(
                PageLeaf(
                    "select/idle",
                    name="选将 · 未选",
                    roi=Region(990, 640, 570, 300),
                    queries=(ImageQuery(T_SELECT_IDLE),),
                    description="「确定」是灰的 —— 还没点武将",
                ),
                PageLeaf(
                    "select/picked",
                    name="选将 · 已选",
                    roi=Region(990, 640, 570, 300),
                    queries=(ImageQuery(T_SELECT_PICKED),),
                    description="「确定」是金的 —— 武将已选",
                ),
            ),
        ),
        PageGroup(
            "fight",
            name="战斗",
            description="战斗：换牌开头 + 结算收尾两个锚点",
            children=(
                PageLeaf(
                    "fight/hand",
                    name="战斗 · 换牌",
                    roi=Region(810, 510, 900, 450),
                    queries=(ImageQuery(T_FIGHT_HAND),),
                    description="「是否需要更换初始手牌？」（每局开头）",
                ),
                PageLeaf(
                    "fight/done",
                    name="战斗 · 结算",
                    roi=Region(1020, 1150, 520, 260),
                    queries=(ImageQuery(T_FIGHT_DONE),),
                    description="结算页的「确认」",
                ),
            ),
        ),
        PageLeaf(
            "over",
            name="刷完了",
            terminal=True,
            roi=Region(1110, 700, 470, 300),
            queries=(ImageQuery(T_LOBBY),),
            description=(
                "局数刷够后的终态。特征和首页一样（还是那张竞技卡）——"
                "点完最后「确认」后游戏回到能用它认出来的界面。"
            ),
        ),
    ),
)
