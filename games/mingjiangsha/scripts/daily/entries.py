"""每日领奖 —— 首页入口与红点区域（纯数据）。

红点只对「每日奖励」入口有意义：

* 只有邮件红点可靠：有红点才进；
* 活动 / 丹青阁 / 商店 / 煮酒 / 战役 / 公会 / 送花：每次进一次；
* 好友的红点是“有人加你”，不是每日奖励，所以不拿它判断。

红点位置实测（2560x1369 客户区）：每个都在入口图标的右上角。
"""

from __future__ import annotations

from dataclasses import dataclass

from gamebot.types import Point, Region

__all__ = ["ENTRIES", "HomeEntry"]


@dataclass(frozen=True)
class HomeEntry:
    """首页一个入口。"""

    key: str
    click: Point
    """点哪里进入。"""
    badge: Region | None = None
    """红点检查区域；None = 不看红点。"""
    check_red: bool = False
    """True = 只有红点存在时才进；False = 日常流程，总是进一次。"""


ENTRIES = (
    # ---- 每日奖励：有红点才进 ----
    HomeEntry("mail", Point(2372, 80), Region(2355, 25, 70, 65), True),
    # 活动/丹青阁/商店红点不可靠，改成每次进一次
    HomeEntry("activity", Point(1784, 280)),
    HomeEntry("gallery", Point(2124, 290)),
    HomeEntry("shop", Point(1955, 282)),
    # ---- 日常流程：没有红点也要做 ----
    HomeEntry("zhu_jiu", Point(2347, 786)),
    HomeEntry("zhan_yi", Point(2025, 642)),
    HomeEntry("gong_hui", Point(1400, 1307)),
    HomeEntry("flower", Point(1573, 1253)),
)
