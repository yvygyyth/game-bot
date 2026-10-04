"""竞技场 —— 本功能的页面。

## 页面标识用什么

用**左上角的「竞技场」标题**（148x52）。实测它在三种状态下都是 **1.000** ——
这正是页面标识该有的性质：那三种状态都是同一个页面。

不能用的：**右侧队伍面板**。它在三种状态下长得完全不同
（空位+创建队伍 / 空位+添加伙伴 / 两个已准备的头像+开始匹配），
拿它当页面特征会导致"进到第二步就认不出自己在哪一页了"。

也不能用的：**背景**。竞技场背景是活的 —— 那个骑马的角色披风一直在飘，
三张图里背景像素完全不同。模板一旦框进背景，换一帧就废。

## ROI 为什么只框左上角

`:data:`JINGJI_PAGE_ROI` 只覆盖标题那一块。除了"更快"，
更重要的是**排除了中间那个「巅峰竞技场」大横幅** ——
它也含"竞技场"三个字，不做限制会有误命中的风险。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import Page
from gamebot.types import Region

from .steps import T_TITLE

#: 页面标识的搜索区域（客户区坐标）：左上角那一块。
#: 刻意避开中间的「巅峰竞技场」横幅 —— 它也含"竞技场"三个字。
JINGJI_PAGE_ROI = Region(40, 0, 240, 90)

#: 页面标识的阈值。实测三种状态都是 1.000，给 0.90 很宽裕。
CONF_TITLE = 0.90

FEATURE_PAGES: list[tuple[Page, str | None]] = [
    (
        Page(
            "home/jingji",
            name="竞技场",
            roi=JINGJI_PAGE_ROI,
            queries=(
                # region 显式给上：页面树定位用它，直接跑 Query 时也用它，
                # 两条路径都成立（页面 roi 只对前者生效）。
                ImageQuery(T_TITLE, region=JINGJI_PAGE_ROI, confidence=CONF_TITLE),
            ),
            description="竞技场：三张图对应它的三种状态（建队前/建队后/已准备）",
        ),
        "home",
    ),
]
