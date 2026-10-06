"""首页 → 竞技场：把鼠标移到熊猫头，再点它。

## 为什么是"移过去再点"，不是"找到再点"

玩家说明：**鼠标不在卡上时熊猫头不是完整的** —— 要先悬浮上去它才完整显示。
所以"先找图再点"会在熊猫头不完整时**找不到**，而这个位置即使不完整也点得中
（玩家给了绝对坐标）。

于是顺序是 **移动 → 等一下 → 点**：

* 移动让熊猫头完整显示（也让视觉上和玩家自己的操作一致）；
* 等待是因为悬浮态要一帧才生效（游戏要做一次 hover 重绘）；
* 点击用**固定坐标**，不依赖识别 —— 玩家明确说了"没出现完整熊猫头，
  大概绝对坐标位置也能正常点击"。

## 为什么这里可以用固定坐标

那个环节的背景一直在动（花瓣、光效、飘雪），熊猫头自己又随悬浮态变化 ——
**没有可靠的可识别目标**。而玩家给了一个稳定的可点坐标，那就是最可靠的依据。

代价：窗口位置或分辨率变了它就失效。所以只写一处
（``pages.JINGJI_ENTRY``），改起来是一个数字。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.types import ActionResult

from ..pages import JINGJI_ENTRY

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["HOVER_SETTLE", "enter_jingji"]

#: 悬浮之后等多久让熊猫头完整显示（秒）。
#: 0.3 够一次重绘，又不至于让每一步都慢半拍。
HOVER_SETTLE = 0.3


def enter_jingji(ctx: RunContext) -> ActionResult[Any]:
    """移鼠标到熊猫头 → 等它完整显示 → 点下去进竞技场。"""
    moved = actions.move_to(ctx.session, JINGJI_ENTRY)
    if not moved.ok:
        return moved

    # 悬浮态要一帧才生效。分开两次调用也让日志里能分清是"移动没生效"
    # 还是"点击没生效" —— 合成一个动作就查不出来了。
    ctx.sleep(HOVER_SETTLE)

    clicked = actions.click_logic_point(ctx.session, JINGJI_ENTRY)
    if not clicked.ok:
        return clicked

    # 画面马上要变（要进竞技场），作废当前帧
    ctx.invalidate_frame()
    return ActionResult.success(
        JINGJI_ENTRY, action="click", message="点了首页的竞技入口（熊猫头）"
    )
