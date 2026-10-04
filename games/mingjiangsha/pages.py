"""名将杀 —— 游戏级公共页面（状态对象）。

它们是一棵页面树的**根和全局叠加层**，所有功能脚本都挂在这上面。

两条规则：

1. **页面 id 是路径形式**。这里是根（``home``）和顶层叠加层
   （``popup_*``）；功能脚本用 ``parent="home"`` 把自己的页面接上去，
   于是它的 id 自动变成 ``home/千里...``。
2. **弹窗要标 ``kind=PageKind.OVERLAY``**。默认的 ``PAGE`` 是替换式语义
   （进子页面就不再是父页面）；弹窗是**叠加式** —— "在首页" 和
   "有网络错误弹窗" 同时成立。搞混会导致"弹窗挡住了但脚本以为在首页继续点"。

模板名相对**游戏级模板根**（``games/mingjiangsha/templates/``）。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import Page, PageKind

#: ``(页面, 父页面 id)`` —— 顺序必须是父在前（``PageTree.add`` 要求父已存在）
COMMON_PAGES: list[tuple[Page, str | None]] = [
    (
        Page(
            "home",
            name="首页",
            queries=(
                ImageQuery("common/home_logo.png", confidence=0.9),
                ImageQuery("common/bottom_bar.png", confidence=0.85),
            ),
            description="主界面：顶部资源条 + 底部功能栏",
        ),
        None,
    ),
    # ---- 全局叠加层：出现在任何页面都能被认出来 ----
    (
        Page(
            "popup_network",
            name="网络错误弹窗",
            kind=PageKind.OVERLAY,
            priority=100,
            queries=(ImageQuery("common/network_error.png", confidence=0.9),),
            description="掉线重连提示，挡住一切操作",
        ),
        None,
    ),
    (
        Page(
            "popup_announcement",
            name="公告弹窗",
            kind=PageKind.OVERLAY,
            priority=90,
            queries=(ImageQuery("common/announcement_title.png", confidence=0.9),),
            description="每次上线都可能弹的公告，点掉就行",
        ),
        None,
    ),
    (
        Page(
            "popup_reward",
            name="奖励弹窗",
            kind=PageKind.OVERLAY,
            priority=80,
            queries=(ImageQuery("common/reward_panel.png", confidence=0.9),),
            description="各种领奖确认框",
        ),
        None,
    ),
    # ---- 终态 ----
    (
        Page(
            "disconnected",
            name="游戏已关闭",
            terminal=True,
            queries=(ImageQuery("common/window_lost.png", confidence=0.95),),
            description="窗口消失时抓到的黑屏/桌面特征；进了这个页面流程直接结束",
        ),
        None,
    ),
]
