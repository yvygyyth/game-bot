"""每日领奖 —— 状态树。"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import PageGroup, PageLeaf
from gamebot.types import Region

from .templates import (
    T_ACTIVITY_STATE,
    T_GALLERY_STATE,
    T_HOME,
    T_MAIL_STATE,
)

__all__ = ["FEATURE_TREE"]

HOME_ROI = Region(2380, 190, 180, 180)
MAIL_ROI = Region(250, 210, 220, 180)
ACTIVITY_ROI = Region(20, 0, 260, 120)
GALLERY_ROI = Region(20, 0, 320, 120)


FEATURE_TREE = PageGroup(
    "daily",
    name="每日领奖",
    children=(
        PageLeaf(
            "daily/root",
            name="首页",
            roi=HOME_ROI,
            queries=(ImageQuery(T_HOME),),
            description="首页：邮件/活动/丹青阁入口",
        ),
        PageLeaf(
            "daily/mail",
            name="邮箱",
            queries=(ImageQuery(T_MAIL_STATE, region=MAIL_ROI),),
            description="我的信件：一键领取",
        ),
        PageLeaf(
            "daily/activity",
            name="活动",
            queries=(ImageQuery(T_ACTIVITY_STATE, region=ACTIVITY_ROI),),
            description="活动：今日卦象（抽两张卡）",
        ),
        PageLeaf(
            "daily/gallery",
            name="丹青阁",
            queries=(ImageQuery(T_GALLERY_STATE, region=GALLERY_ROI),),
            description="丹青阁：每日礼包（进去可能先弹购买，Esc 关）",
        ),
    ),
)
