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

战斗中间那几张快照（圆结、投降、空白区…）没有分支，做成步骤即可；
状态只留给可能停住或从别处回来的锚点。匹配后 tip 弹窗见 `steps/start_match.py`。

模板路径见 :mod:`.templates`。阈值走框架默认。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import PageGroup, PageLeaf

from .templates import (
    T_AFTER_ADD,
    T_AFTER_CREATE,
    T_BEFORE_CREATE,
    T_FIGHT_DONE,
    T_FIGHT_HAND,
    T_LOBBY,
    T_SELECT_IDLE,
    T_SELECT_PICKED,
)

#: 战斗里等下一个界面出现的超时（秒）。
WAIT_FIGHT = 8.0

FEATURE_TREE = PageGroup(
    "home",
    name="首页（容器）",
    description="首页这一层：下面是主界面、竞技场等并列状态",
    children=(
        PageLeaf(
            "lobby",
            name="首页",
            min_stable_frames=2,  # 首页那排卡有滑入动画，等它停稳
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
                    queries=(ImageQuery(T_BEFORE_CREATE),),
                    description="右下角是「创建队伍」",
                ),
                PageLeaf(
                    "jj/after_create",
                    name="竞技场 · 建队后",
                    queries=(ImageQuery(T_AFTER_CREATE),),
                    description="右下角是「添加伙伴」",
                ),
                PageLeaf(
                    "jj/after_add",
                    name="竞技场 · 加完伙伴",
                    queries=(ImageQuery(T_AFTER_ADD),),
                    description="右下角是「开始匹配」",
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
                    queries=(ImageQuery(T_SELECT_IDLE),),
                    description="「确定」是灰的 —— 还没点武将",
                ),
                PageLeaf(
                    "select/picked",
                    name="选将 · 已选",
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
                    queries=(ImageQuery(T_FIGHT_HAND),),
                    description="「是否需要更换初始手牌？」（每局开头）",
                ),
                PageLeaf(
                    "fight/done",
                    name="战斗 · 结算",
                    queries=(ImageQuery(T_FIGHT_DONE),),
                    description="结算页的「确认」",
                ),
            ),
        ),
        PageLeaf(
            "over",
            name="刷完了",
            terminal=True,
            queries=(ImageQuery(T_LOBBY),),
            description=(
                "局数刷够后的终态。特征和首页一样（还是那张竞技卡）——"
                "点完最后「确认」后游戏回到能用它认出来的界面。"
            ),
        ),
    ),
)
