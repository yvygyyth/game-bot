"""推进队伍流程：创建队伍 → 添加伙伴 → 开始匹配。

**三个状态各有一个函数**（它们现在是三个真正的状态，见 :mod:`.pages`）。

## 一个函数 = 一个按钮

每个函数只负责"确认那个按钮在，然后点它"。拆开的好处：

* 位置守卫天然生效（节点的 ``page`` 声明了它只在对应状态下执行），
  所以不会在错误的阶段点错的按钮；
* 失败信息能说清是**哪个**按钮没认出来（合并成一个函数时只会得到
  "三个按钮一个都没看到"）。

## 为什么每个函数还会自己再查一次

函数由位置守卫保护（不在对应状态就不执行），但**仍然自己查一次**。两个理由：

1. **状态识别有帧延迟** —— 点完「创建队伍」的那一帧还没刷新，状态可能仍报
   "建队前"，这时如果直接点，就会在同一个地方点第二下；
2. 守卫和函数用的是同一份依据（节点的 ``page`` 来自树的识别），但它们**发生在
   不同时刻**（守卫在取帧前用上一轮结论，函数在取帧后）。多查一次花不了多少，
   换来的是"点下去的时候按钮确实在"。

三个函数都用 :func:`~gamebot.execution.builtins.click_image`，它自带
"找到 → 点 → 作废帧"。

## 一个必须记住的实测事实

**「开始匹配」在三个状态下都在**（从进竞技场就可见，只是没队伍时是灰的）。

所以 :data:`START_MATCH` 那张图**必须是在按钮亮起时截的** ——
否则"加完伙伴"这个状态永远认不出来（灰按钮和目标图差得太远）。
这是页面树正确性的前提，不是可选的细节。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.execution.builtins import click_image
from gamebot.types import ActionResult

from ..pages import CONF_BUTTON, JINGJI_TEAM_ROI, T_ADD_PET, T_CREATE_TEAM, T_START_MATCH

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "DEFAULT_SETTLE",
    "TEAM_ROI",
    "T_ADD_PET",
    "T_CREATE_TEAM",
    "T_START_MATCH",
    "add_pet",
    "create_team",
    "start_match",
]

#: 三个按钮的搜索区域（客户区坐标）：右下角那块面板。
#: **和页面树共用同一个值** —— 两处各写一份迟早会不一致（改了页面 ROI
#: 忘了改这里，症状是"状态认出来了但按钮找不到"，极难查）。
TEAM_ROI = JINGJI_TEAM_ROI

#: 点完默认等多久（秒）。**只作为声明的镜像** —— 真正生效的值来自运行参数
#: ``jingji.settle``（表单可调）。
DEFAULT_SETTLE = 1.0


def _settle(ctx: RunContext) -> float:
    """点完等多久：来自运行参数（表单可调），每次执行现读。"""
    return ctx.param("jingji.settle", DEFAULT_SETTLE)


def _confidence(ctx: RunContext) -> float:
    """按钮阈值：来自运行参数 ``jingji.confidence``（表单可调）。

    实测：自己的图上 1.000、**按钮之间最高 0.690**（创建队伍 vs 添加伙伴 ——
    位置一样、只有文字不同），所以默认 0.85 留了很大余量。
    """
    return ctx.param("jingji.confidence", CONF_BUTTON)


def create_team(ctx: RunContext) -> ActionResult[Any]:
    """建队前：点「创建队伍」。"""
    return click_image(
        ctx,
        T_CREATE_TEAM,
        region=TEAM_ROI,
        confidence=_confidence(ctx),
        settle=_settle(ctx),
    )


def add_pet(ctx: RunContext) -> ActionResult[Any]:
    """建队后：点「添加伙伴」。"""
    return click_image(
        ctx,
        T_ADD_PET,
        region=TEAM_ROI,
        confidence=_confidence(ctx),
        settle=_settle(ctx),
    )


def start_match(ctx: RunContext) -> ActionResult[Any]:
    """加完伙伴：点「开始匹配」。"""
    return click_image(
        ctx,
        T_START_MATCH,
        region=TEAM_ROI,
        confidence=_confidence(ctx),
        settle=_settle(ctx),
    )
