"""一局结束：点空白区 → 下一步 → 确认，并把循环次数 +1。

## 这三步对应玩家截图

| 序 | 对应图 | 点什么 | 怎么定位置 |
|---|---|---|---|
| 1 | `zhandou5` | 「点击空白区域到下一步」 | 找 ``T_FIGHT_SPACE``（**提示文字本身**） |
| 2 | `zhandou6` | 「下一步」 | 模板 ``T_FIGHT_NEXT`` |
| 3 | `zhandou7` | 「确认」 | 找 ``T_FIGHT_DONE``（就是状态锚点那张） |

## 第 1 步为什么从固定坐标改成找图

原来点的是固定坐标 ``FIGHT_BLANK``，理由写的是"那儿本来就没有可认的东西" ——
**那条理由是错的**：那行提示文字「点击空白区域到下一步」本身就是可认的
（``fight/space.png``），认出来点它的中心就行。

而且找图**更准也更稳**：

* 那行字在原始像素里约 `x 1088~1480 / y 1205~1245`，客户区中心 ≈ `(1281, 1202)`；
* 原来的固定坐标 `FIGHT_BLANK = (1341, 1226)` 换算过来是 `(1341, 1203)` ——
  **偏右 60px**，落在字的右边缘附近（勉强点中，但不是中心）；
* 结算面板是**滑入**的，固定坐标假定它已经到位；找图则等它真的出现。

于是这一步和另外两步一样，变成"等它出现再点"。

## 循环次数为什么在这里 +1

它是**一局真正结束**的那一刻 —— 打完这一局，循环次数才该加一。
放在别处（比如"点了开始匹配"就加）会让"中途失败、重定位、再来一次"重复计数。

计数器写在**黑板**（``ctx.blackboard``）里，不是运行参数：
黑板是"跑出来的状态"，参数是"进去之前定好的输入"。循环次数是跑出来的。

## 「确认」为什么复用状态锚点

`fight/done` 这个状态就是靠 ``fight/done.png``（结算页的「确认」）认出来的，
而这里要点的也正是它 —— 一张图两用是刻意的：省一张模板，
而且不会出现"认出来是结算页、却点了别的按钮"。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.atomic.query import ImageQuery
from gamebot.execution.builtins import click_image, wait_for
from gamebot.types import ActionResult

from ..form import ROUNDS_PARAM
from ..pages import (
    CONF,
    FIGHT_NEXT_SETTLE,
    T_FIGHT_DONE,
    T_FIGHT_NEXT,
    T_FIGHT_SPACE,
    WAIT_FIGHT,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["ROUNDS_KEY", "finish_round", "noop"]

#: 已完成的局数记在黑板里的这个键上。
#:
#: 用点分层级（``fight.rounds``）避免和别的键撞名 —— 和 ``ctx.param`` 的
#: 命名习惯一致。
ROUNDS_KEY = "fight.rounds"


def finish_round(ctx: RunContext) -> ActionResult[Any]:
    """结算页：点空白区 → 下一步 → 确认，然后记一局。"""
    # ---- 1. 等「点击空白区域到下一步」出现，点那行字 ----
    # 结算面板是**滑入**的，所以是"等它出现"而不是"假定它已经在"。
    # 找图命中的是**中心点**（matcher 返回 top_left + 模板一半），
    # 所以直接点它就是点在那行字上。
    blank = click_image(ctx, T_FIGHT_SPACE, confidence=CONF, settle=FIGHT_NEXT_SETTLE)
    if not blank.ok:
        return blank

    # ---- 2. 等「下一步」出现，点它 ----
    next_query = ImageQuery(T_FIGHT_NEXT, confidence=CONF)
    appeared = wait_for(ctx, next_query, timeout=WAIT_FIGHT)
    if not appeared.ok or appeared.value is None:
        return ActionResult.not_found(
            "等不到「下一步」出现（点空白区没生效？）", template=T_FIGHT_NEXT
        )
    step = actions.click_source_point(ctx.session, appeared.value)
    if not step.ok:
        return step
    ctx.invalidate_frame()

    # ---- 3. 点结算页的「确认」（复用状态锚点那张模板）----
    # 全图找。提速时加 region= —— 结算页的「确认」在**底部中间**
    # （客户区约 x 1200~1445, y 1250~1315）。
    confirmed = click_image(
        ctx, T_FIGHT_DONE, confidence=CONF, settle=FIGHT_NEXT_SETTLE
    )
    if not confirmed.ok:
        return confirmed

    # ---- 4. 记一局 ----
    # 放在最后：前三步任何一个失败都会提前返回，那一局就不算完成 ——
    # 于是"计数"和"真的打完一局"永远一致（中途失败重定位不会重复计数）。
    rounds = int(ctx.blackboard.get(ROUNDS_KEY, 0)) + 1
    ctx.blackboard.set(ROUNDS_KEY, rounds)
    target = int(ctx.param(ROUNDS_PARAM, 0) or 0)
    return confirmed.with_meta(rounds=rounds, target=target, done=rounds >= target)


def noop(ctx: RunContext) -> ActionResult[Any]:
    """什么都不做。给终态节点用。

    ## 为什么终态节点也要有个步骤

    "流程停在哪"和"那个节点做什么"是两件事。终态节点需要的是**一个明确的
    落点**，让报告里能说"停在 finish，因为刷够了" —— 而不是"流程莫名其妙没了"。

    这个函数真的什么都不做：状态认出来了、边条件满足了，流程就该结束。
    留个空函数比把 ``steps`` 留空好排查（日志里会有一条 ``noop``）。
    """
    return ActionResult.success(None, action="noop", message="收工")

