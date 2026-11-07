"""每日领奖 —— 状态树。"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import PageGroup, PageLeaf
from gamebot.types import Region

from .templates import (
    T_ACTIVITY_STATE,
    T_FLOWER_STATE,
    T_GALLERY_STATE,
    T_GONG_HUI_STATE,
    T_HOME,
    T_MAIL_STATE,
    T_SHOP_STATE,
    T_ZHAN_YI_STATE,
    T_ZHU_JIU_STATE,
)

__all__ = ["FEATURE_TREE"]

HOME_ROI = Region(2380, 190, 180, 180)
MAIL_ROI = Region(420, 390, 120, 260)
ACTIVITY_ROI = Region(20, 0, 260, 120)
GALLERY_ROI = Region(20, 0, 320, 120)
SHOP_ROI = Region(1420, 180, 260, 140)
ZHU_JIU_ROI = Region(0, 0, 300, 140)
ZHAN_YI_ROI = Region(0, 0, 300, 140)
GONG_HUI_ROI = Region(0, 0, 400, 140)
FLOWER_ROI = Region(380, 70, 260, 150)


FEATURE_TREE = PageGroup(
    "daily",
    name="每日领奖",
    children=(
        PageLeaf(
            "daily/flower",
            name="好友/送花",
            queries=(ImageQuery(T_FLOWER_STATE, region=FLOWER_ROI),),
            description="好友：送礼 → 油菜花 → 赠送x100 → 好友",
        ),
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
            "daily/zhu_jiu",
            name="煮酒",
            queries=(ImageQuery(T_ZHU_JIU_STATE, region=ZHU_JIU_ROI),),
            description="煮酒：青梅商店入口",
        ),
        PageLeaf(
            "daily/zhan_yi",
            name="战役",
            queries=(ImageQuery(T_ZHAN_YI_STATE, region=ZHAN_YI_ROI),),
            description="战役：战役商店入口",
        ),
        PageLeaf(
            "daily/gong_hui",
            name="公会",
            queries=(ImageQuery(T_GONG_HUI_STATE, region=GONG_HUI_ROI),),
            description="我的公会：商店入口",
        ),
        PageLeaf(
            "daily/shop",
            name="商店",
            queries=(ImageQuery(T_SHOP_STATE, region=SHOP_ROI),),
            description="商店：黄金/碎银/铜钱/金兰/金铺",
        ),
        PageLeaf(
            "daily/gallery",
            name="丹青阁",
            queries=(ImageQuery(T_GALLERY_STATE, region=GALLERY_ROI),),
            description="丹青阁：每日礼包（进去可能先弹购买，Esc 关）",
        ),
    ),
)
