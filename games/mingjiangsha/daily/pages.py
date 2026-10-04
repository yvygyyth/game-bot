"""每日签到 —— 页面（状态对象）。

只有两个页面，是"功能脚本可以很小"的示范。

注意 ``home/daily/claimed`` 标了 ``terminal=True``：进了它流程就结束，
所以它**不需要节点** —— 一个页面可以只是"观察目标"，不一定非要有动作。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import Page

FEATURE_PAGES: list[tuple[Page, str | None]] = [
    (
        Page(
            "home/daily",
            name="日常面板",
            queries=(
                ImageQuery("daily/panel_header.png", confidence=0.9),
                ImageQuery("daily/sign_in_list.png", confidence=0.85),
            ),
            description="日常任务面板，左上角是标题、中间是签到格子",
        ),
        "home",
    ),
    (
        Page(
            "home/daily/claimed",
            name="已签到",
            terminal=True,
            min_stable_frames=2,  # 签到成功有个盖章动画，等它稳定
            queries=(ImageQuery("daily/claimed_mark.png", confidence=0.9),),
            description="签到完成标记 —— 看到它就说明这个脚本干完了",
        ),
        "home/daily",
    ),
]
