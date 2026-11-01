"""千里单骑 —— 状态树。

```
home（容器）
├── root                     首页（还没进战役）
├── campaign                 战役界面（千里单骑 / 山河争锋…）
└── qianli                   千里单骑
    ├── qianli/select1       主界面 · 没选将（开始挑战是灰的）
    ├── qianli/select2       武将选择面板 · 没选将
    ├── qianli/select3       武将选择面板 · 已选将
    ├── qianli/select4       主界面 · 已选将（开始挑战是红的）
    ├── qianli/select5       主界面 · 继续挑战（已有进行中的局）
    └── qianli/run           局内
        ├── qianli/map       地图（选节点）
        ├── qianli/pre_battle 战斗预览（开始对局）
        ├── qianli/fight     战斗中（取消/设置/托管）
        ├── qianli/gift      选赠礼武将
        ├── qianli/gift_kind 选赠礼类别
        ├── qianli/end       本局结束（领取奖励）
        └── qianli/end2      恭喜获得浮层（Esc 回选将）
```

五个 select 状态的区分：

| 状态 | 有什么 | 没什么 |
|---|---|---|
| `select1` | 千里单骑标题 + 灰色开始挑战 + 「选择武将」占位卡 | 选将面板 |
| `select2` | 标题 + 「武将选择」面板标题 + 搜索按钮 + 占位卡 | — |
| `select3` | 标题 + 面板标题 + 搜索按钮 | **占位卡**（已换成武将卡） |
| `select4` | 标题 + 红色「开始挑战」 | 占位卡、面板 |
| `select5` | 标题 + 红色「继续挑战」 | 占位卡、面板 |

提示：这些模板的位置都在**源坐标 2560x1369** 下量过；换分辨率要重量。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery, any_image
from gamebot.state import PageGroup, PageLeaf
from gamebot.types import Region

from .templates import (
    T_CAMPAIGN,
    T_CLAIM_REWARD,
    T_CONGRATS,
    T_FIGHT_AUTO,
    T_FIGHT_AUTO_OFF,
    T_FIGHT_CANCEL,
    T_FIGHT_SETTING,
    T_FLOW,
    T_FLOW_MAP,
    T_GIFT_KIND_TITLE,
    T_GIFT_TITLE,
    T_HOME,
    T_NEXT,
    T_PICK_TITLE,
    T_PLACEHOLDER,
    T_SEARCH,
    T_SELECT_TITLE,
    T_START,
    T_START_BATTLE,
    T_START_DISABLED,
)

#: 首页右上角那个小图标（状态锚点）。
HOME_ROI = Region(2380, 187, 160, 160)

#: 战役界面的「战旗 + 战役商店」。
CAMPAIGN_ROI = Region(0, 0, 560, 400)

#: 千里单骑标题。
TITLE_ROI = Region(0, 0, 480, 110)

#: 灰色/红色「开始挑战」。
START_ROI = Region(1980, 1157, 440, 140)

#: 「武将选择」标题。
PICK_TITLE_ROI = Region(1080, 787, 400, 120)

#: 「搜索」按钮。
SEARCH_ROI = Region(2300, 897, 190, 100)

#: 主界面上的「选择武将」占位卡。
MAIN_PLACEHOLDER_ROI = Region(1980, 477, 440, 280)

#: 选将面板里的「选择武将」占位卡（面板打开后它挪到了上面）。
PICK_PLACEHOLDER_ROI = Region(1990, 217, 430, 260)

#: 局内标题「千里单骑 · 无尽」。
FLOW_ROI = Region(0, 0, 600, 120)

#: 局内地图右侧的小图标（和标题一起认地图）。
MAP_ICON_ROI = Region(2430, 507, 100, 110)

#: 地图上可以点的节点区域（旧脚本的 CHOICE_REGION）。
NODE_REGION = Region(800, 327, 1630, 780)

#: 点节点后的「开始对局」。
START_BATTLE_ROI = Region(700, 1067, 350, 110)

#: 赠礼第一屏标题。
GIFT_TITLE_ROI = Region(950, 1142, 640, 95)

#: 赠礼第二屏标题。
GIFT_KIND_TITLE_ROI = Region(1025, 1142, 480, 95)

#: 本局结束「领取奖励」。
CLAIM_ROI = Region(1080, 1157, 420, 120)

#: 「恭喜获得」浮层。
CONGRATS_ROI = Region(880, 252, 640, 140)


FEATURE_TREE = PageGroup(
    "home",
    name="首页（容器）",
    description="首页这一层：战役、千里单骑等界面",
    children=(
        PageLeaf(
            "root",
            name="首页",
            roi=HOME_ROI,
            queries=(ImageQuery(T_HOME),),
            description="还在首页，需要先点「战役」",
        ),
        PageLeaf(
            "campaign",
            name="战役",
            roi=CAMPAIGN_ROI,
            queries=(ImageQuery(T_CAMPAIGN),),
            description="战役界面：千里单骑 / 山河争锋…",
        ),
        PageGroup(
            "qianli",
            name="千里单骑",
            description="千里单骑：选将 → 开始挑战 → 局内",
            children=(
                PageGroup(
                    "qianli/run",
                    name="局内",
                    description="千里单骑一局：地图 → 战斗 → 赠礼 → 地图/结束",
                    children=(
                        PageLeaf(
                            "qianli/map",
                            name="局内 · 地图",
                            queries=(
                                ImageQuery(T_FLOW, region=FLOW_ROI),
                                ImageQuery(T_FLOW_MAP, region=MAP_ICON_ROI),
                            ),
                            description="地图：三个节点 + 当前挑战层数 + 结束挑战",
                        ),
                        PageLeaf(
                            "qianli/pre_battle",
                            name="局内 · 战斗预览",
                            queries=(
                                ImageQuery(T_START_BATTLE, region=START_BATTLE_ROI),
                            ),
                            description="点节点后的战斗预览：开始对局 / 再想一想",
                        ),
                        PageLeaf(
                            "qianli/fight",
                            name="局内 · 战斗中",
                            queries=(
                                any_image(
                                    T_FIGHT_CANCEL,
                                    T_FIGHT_SETTING,
                                    T_FIGHT_AUTO,
                                    T_FIGHT_AUTO_OFF,
                                    confidence=0.9,
                                ),
                            ),
                            description="战斗界面：取消换牌 / 设置 / 托管",
                        ),
                        PageLeaf(
                            "qianli/gift",
                            name="局内 · 选赠礼武将",
                            queries=(
                                ImageQuery(T_GIFT_TITLE, region=GIFT_TITLE_ROI),
                            ),
                            description="请选择接受谁的赠礼？",
                        ),
                        PageLeaf(
                            "qianli/gift_kind",
                            name="局内 · 选赠礼类别",
                            queries=(
                                ImageQuery(T_GIFT_KIND_TITLE, region=GIFT_KIND_TITLE_ROI),
                            ),
                            description="请选择一项赠礼？信物 / 武将牌 / 并肩作战…",
                        ),
                        PageLeaf(
                            "qianli/end",
                            name="局内 · 本局结束",
                            queries=(
                                ImageQuery(T_CLAIM_REWARD, region=CLAIM_ROI),
                            ),
                            description="本局结束：领取奖励",
                        ),
                        PageLeaf(
                            "qianli/end2",
                            name="局内 · 恭喜获得",
                            queries=(
                                ImageQuery(T_CONGRATS, region=CONGRATS_ROI),
                            ),
                            description="领奖后的「恭喜获得」浮层；Esc 关闭回选将",
                        ),
                    ),
                ),
                PageLeaf(
                    "qianli/select1",
                    name="千里单骑 · 没选将",
                    queries=(
                        ImageQuery(T_SELECT_TITLE, region=TITLE_ROI),
                        ImageQuery(T_START_DISABLED, region=START_ROI),
                        ImageQuery(T_PLACEHOLDER, region=MAIN_PLACEHOLDER_ROI),
                    ),
                    description="主界面：开始挑战是灰的，右边是「选择武将」占位卡",
                ),
                PageLeaf(
                    "qianli/select2",
                    name="选将面板 · 没选",
                    queries=(
                        ImageQuery(T_SELECT_TITLE, region=TITLE_ROI),
                        ImageQuery(T_PICK_TITLE, region=PICK_TITLE_ROI),
                        ImageQuery(T_SEARCH, region=SEARCH_ROI),
                        ImageQuery(T_PLACEHOLDER, region=PICK_PLACEHOLDER_ROI),
                    ),
                    description="武将选择面板：有搜索框和占位卡",
                ),
                PageLeaf(
                    "qianli/select3",
                    name="选将面板 · 已选",
                    queries=(
                        ImageQuery(T_SELECT_TITLE, region=TITLE_ROI),
                        ImageQuery(T_PICK_TITLE, region=PICK_TITLE_ROI),
                        ImageQuery(T_SEARCH, region=SEARCH_ROI),
                    ),
                    # 已选将时占位卡会被武将卡替换 —— 用"没什么"来区分。
                    exclude=(ImageQuery(T_PLACEHOLDER, region=PICK_PLACEHOLDER_ROI),),
                    description="武将选择面板：占位卡没了，说明已经选中武将",
                ),
                PageLeaf(
                    "qianli/select5",
                    name="千里单骑 · 继续挑战",
                    queries=(
                        ImageQuery(T_SELECT_TITLE, region=TITLE_ROI),
                        ImageQuery(T_NEXT, region=START_ROI),
                    ),
                    description="主界面：按钮是「继续挑战」，说明已有进行中的局，点了直接进局内",
                ),
                PageLeaf(
                    "qianli/select4",
                    name="千里单骑 · 已选将",
                    queries=(
                        ImageQuery(T_SELECT_TITLE, region=TITLE_ROI),
                        ImageQuery(T_START, region=START_ROI),
                    ),
                    # 「继续挑战」和「开始挑战」是同一块红按钮、只差文字，
                    # 用"没什么"把两者钉死，避免互相误认。
                    exclude=(ImageQuery(T_NEXT, region=START_ROI),),
                    description="主界面：开始挑战变红，可以开局",
                ),
            ),
        ),
    ),
)
