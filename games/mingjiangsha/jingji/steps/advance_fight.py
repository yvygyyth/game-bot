"""战斗阶段：从「换牌弹窗」一路点到「结算页」。

## 这一个函数走完 4 个界面

关联表把整个战斗过程接在 ``fight/hand`` 一个状态上（理由见 `pages.py`：
那 4 张快照之间**没有分支**，是一条直线）。所以这里就是一条直线的点击序列：

| 序 | 对应玩家截图 | 点什么 | 怎么定位置 |
|---|---|---|---|
| 1 | `zhandou1` | 「取消」（不换手牌） | **固定坐标** |
| 2 | `zhandou2` | 右上角金色圆结（展开菜单） | 模板 ``T_FIGHT_MENU`` |
| 3 | `zhandou3` | 「投降」 | 模板 ``T_FIGHT_SURRENDER`` |
| 4 | `zhandou4` | 投降弹窗的「确认」 | 模板 ``T_CLICK_FIGHT_CONFIRM`` |

走完这四步画面就到结算页（``fight/done``），剩下的交给 :mod:`.finish_round`。

## 第 1 步为什么用固定坐标

换牌弹窗里的「取消」和**投降弹窗里的「确认」**长得太像（同一个组件、同一行、
都是浅色按钮），共用一套识别会互相误命中。而"取消"的位置是固定的
（玩家原话："zhandou1 的界面点那个取消"），固定坐标最省事也最可靠。

## 2~4 步现在**全图找**（没给 ``region``）

用户要求：默认不加 roi，误命中多了再加。想提速就加 —— 三个目标的框分别是：

* 圆结 / 投降：都在**右上角**那条竖排（客户区约 x 2400~2470）；
* 投降确认：屏幕**中间偏下**那个弹窗（约 x 1000~1240, y 885~960）。

加在 :func:`_wait_then_click` 里那一处，别在别处再建一份。

## 为什么每步都要"等出现"

点击下发之后界面要几百毫秒才变。**不等就点下一步 = 在旧界面上点第二下**，
这一轮就废了。所以每步都是 :func:`~gamebot.execution.builtins.wait_for`
（原子层的轮询，自带 timeout）—— 不是 sleep 一个拍脑袋的秒数，
后者要么不够（界面慢就失败）要么白等。

**等不到就失败，不继续点。** 那说明上一步没生效；继续点后面的按钮会在旧界面上
乱点 —— 那正是识图脚本最危险的失败模式。停下来让上层重定位是唯一安全的选择。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.atomic.query import ImageQuery
from gamebot.execution.builtins import wait_for
from gamebot.types import ActionResult

from ..pages import (
    FIGHT_HAND_CANCEL,
    T_CLICK_FIGHT_CONFIRM,
    T_FIGHT_MENU,
    T_FIGHT_SURRENDER,
    WAIT_FIGHT,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["advance_fight"]


def advance_fight(ctx: RunContext) -> ActionResult[Any]:
    """换牌弹窗 → 投降确认。走完这四步，画面就到结算页了。"""
    # ---- 1. 取消换牌（固定坐标，理由见模块 docstring）----
    cancelled = actions.click_logic_point(ctx.session, FIGHT_HAND_CANCEL)
    if not cancelled.ok:
        return cancelled
    ctx.invalidate_frame()

    # ---- 2~4. 等目标出现 → 点它 ----
    for template, label in (
        (T_FIGHT_MENU, "右上角圆结"),
        (T_FIGHT_SURRENDER, "投降"),
        (T_CLICK_FIGHT_CONFIRM, "投降确认"),
    ):
        step = _wait_then_click(ctx, template, label)
        if not step.ok:
            return step

    return ActionResult.success(
        FIGHT_HAND_CANCEL, action="sequence", message="已发起投降，等结算"
    )


def _wait_then_click(ctx: RunContext, template: str, label: str) -> ActionResult[Any]:
    """等 ``template`` 出现 → 点它。等不到就失败（交给上层重定位）。

    全图找。**想提速就在这里加 ``region=``** —— 只此一处，
    别在别的地方再建一份（那就成了第二份实现）。
    """
    query = ImageQuery(template)
    appeared = wait_for(ctx, query, timeout=WAIT_FIGHT)
    if not appeared.ok or appeared.value is None:
        return ActionResult.not_found(
            f"等不到「{label}」出现（上一步可能没生效）", template=template
        )

    # ⚠️ ``wait_for`` 命中的是**源坐标**（find_image 返回的就是源坐标），
    # 所以必须用 click_source_point。用 click_logic_point 会二次换算、
    # 点偏一个窗口偏移 —— 大目标上看不出来，是这类脚本最阴的一类 bug。
    clicked = actions.click_source_point(ctx.session, appeared.value)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    return ActionResult.success(
        appeared.value, action="click", template=template, message=f"点了「{label}」"
    )
