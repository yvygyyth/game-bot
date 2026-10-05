"""竞技场的步骤 —— 一个步骤一个文件。

## 为什么按步骤分文件，而不是按"用到的图"分

一个步骤的完整定义 = 它的逻辑 + 它用的模板 + 那些模板的阈值和搜索范围。
把这些**放在一起**，改这个步骤时只动一个文件；按"模板放一起、逻辑放一起"分，
改一步就要在几个文件之间来回跳。

## 顺序探测为什么在一个步骤里（而不是三个节点）

三个状态（建队前 / 建队后 / 已准备）**是同一个页面** —— 页面标识（左上角
标题）在三种状态下都是 1.000，页面树区分不了它们。所以把"该点哪个"交给游戏
自己：哪个按钮在就点哪个，脚本这边不重复维护一份状态机。
详见 :mod:`.advance_team`。

## 一个必须记住的实测事实

**「开始匹配」在三个状态下都在**（它从进竞技场就可见，只是没队伍时是灰的）。
所以顺序检测里它必须排最后，否则第一轮就直接点它了。
"""

from __future__ import annotations

from .advance_team import (
    CONF_BUTTON,
    T_ADD_PET,
    T_CREATE_TEAM,
    T_START_MATCH,
    TEAM_ROI,
    AdvanceTeamStep,
)
from .enter_jingji import EnterJingjiStep

__all__ = [
    "CONF_BUTTON",
    "TEAM_ROI",
    "T_ADD_PET",
    "T_CREATE_TEAM",
    "T_START_MATCH",
    "AdvanceTeamStep",
    "EnterJingjiStep",
]
