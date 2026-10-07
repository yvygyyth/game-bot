"""选将：点第 1 张武将卡 → 点「确定」。

## 为什么拆成两个函数（对应两个状态）

选将界面的**确定按钮有两种样子**：没选武将时是灰的、选了之后是金的。
关联表把它拆成 ``select/idle`` 和 ``select/picked`` 两个叶子，各有各的步骤：

* ``select/idle``  -> :func:`pick_general`：点第 1 张卡（点完确定变金）
* ``select/picked`` -> :func:`confirm_general`：点确定

**好处是不需要"选没选过"的判断。** 状态机天然知道走到哪一步：
卡在 ``select/idle`` 就说明上次点卡没生效、会再点一次；
而确定按钮只有在状态变成 ``picked``（金）之后才会被点。

## "随便点一个" = 固定点第一个

玩家说"随便点一个然后点确认"。这里固定点**第 1 张卡**（张飞那张）：
位置固定、和"哪张被选中"的高亮无关，换武将也不用改代码。
想换武将就改 ``pages.SELECT_FIRST_CARD`` 和那张模板。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.execution.builtins import click_image
from gamebot.types import ActionResult

from ..pages import CONF, T_CLICK_SELECT_FIRST, T_SELECT_PICKED

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["CONFIRM_SETTLE", "PICK_SETTLE", "confirm_general", "pick_general"]

#: 点武将卡之后等它变成选中态（秒）。界面要重画那张卡的边框。
PICK_SETTLE = 0.5

#: 点「确定」之后等进战斗（秒）。战斗加载比一般界面慢，给宽一点。
CONFIRM_SETTLE = 1.5


def pick_general(ctx: RunContext) -> ActionResult[Any]:
    """选将 · 未选：点第 1 张武将卡。

    点完卡之后「确定」会变金 —— 那是**下一个状态**（``select/picked``），
    所以这里除了作废帧不做别的：状态机下一轮自己会认出来。
    """
    # 全图找。提速时加 region= —— 第 1 张卡在选将界面的**左起第一张**
    # （客户区约 x 190~420, y 300~660）。
    return click_image(ctx, T_CLICK_SELECT_FIRST, confidence=CONF, settle=PICK_SETTLE)


def confirm_general(ctx: RunContext) -> ActionResult[Any]:
    """选将 · 已选：点「确定」进战斗。

    点的目标复用**状态锚点**那张模板（``select/picked.png`` = 金色确定按钮）：
    它就是屏幕中间那个按钮，位置没有歧义，没必要为"点它"再单独裁一张图。
    （代价：改状态识别就会动到这个点击目标 —— 但换按钮样子的概率极低，
    而少维护一张图是实实在在的收益。）
    """
    # 全图找。提速时加 region= —— 确定按钮在**屏幕中间**
    # （客户区约 x 1120~1500, y 750~825）。
    return click_image(ctx, T_SELECT_PICKED, confidence=CONF, settle=CONFIRM_SETTLE)
