"""竞技场的步骤 —— 一个步骤一个文件。

## 为什么按步骤分文件，而不是按"用到的图"分

一个步骤的完整定义 = 它的逻辑 + 它用的模板 + 那些模板的阈值和搜索范围。
把这些**放在一起**，改这个步骤时只动一个文件；按"模板放一起、逻辑放一起"分，
改一步就要在几个文件之间来回跳。

## 队伍流程为什么是**三个**步骤（原来是三个状态用一个步骤）

原来三个状态是同一个页面，页面树区分不了，所以只能让一个步骤"按顺序探测三个
按钮"。现在 :mod:`.pages` 把它们建成了三个并列子状态，于是**一个状态一个步骤**：

* 每个步骤只判断自己那一个按钮，日志能说清是哪个没认出来；
* 每个步骤有位置守卫（节点的 ``page`` 声明），不会在错误的阶段点错的按钮；
* ``describe`` 里能看出走到第几段。

## 一个必须记住的实测事实

**「开始匹配」在三个状态下都在**（从进竞技场就可见，只是没队伍时是灰的）。

这决定了 :data:`~.advance_team.T_START_MATCH` 那张图**必须是在按钮亮起时截的** ——
否则"加完伙伴"这个状态永远认不出来（灰按钮和目标图差得太远）。
这是新页面树正确性的前提，不是可选的细节。

（旧的顺序探测版本里，这条事实的体现是"开始匹配必须排最后"；
现在体现为"模板必须是亮态"。）
"""

from __future__ import annotations

from .advance_team import (
    T_ADD_PET,
    T_CREATE_TEAM,
    T_START_MATCH,
    TEAM_ROI,
    AddPetStep,
    CreateTeamStep,
    StartMatchStep,
)
from .enter_jingji import EnterJingjiStep

__all__ = [
    "TEAM_ROI",
    "T_ADD_PET",
    "T_CREATE_TEAM",
    "T_START_MATCH",
    "AddPetStep",
    "CreateTeamStep",
    "EnterJingjiStep",
    "StartMatchStep",
]
