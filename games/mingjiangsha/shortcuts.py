"""名将杀 —— 游戏级快捷方法。

把"这个游戏里反复要做的几件事"封装成一句话。它们都建立在原子层之上，
返回 ``ActionResult``，所以可以直接塞进 ``FunctionStep``::

    Node("home", page="home", steps=[FunctionStep(shortcuts.back_to_home)])

放在**游戏级**而不是功能级，是因为断线、弹窗、回主界面这些事
每个脚本都会碰到 —— 写一次，全体受益。

约定：

* 快捷方法**只做一件事**，不要把多步策略塞进来（那是流程层的事）；
* 找不到目标时返回 ``not_found``，不要抛异常 —— 上层靠返回值判断；
* 名字用动词短语，因为它们会被当成步骤名打印进日志。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.atomic.combinators import wait_any_of, wait_disappear
from gamebot.atomic.query import ImageQuery
from gamebot.types import ActionResult, Point

if TYPE_CHECKING:
    from gamebot.context import RunContext

#: 模板名（相对游戏级模板根）
T_RETRY = "common/network_retry.png"
T_POPUP_CLOSE = "common/popup_close.png"
T_REWARD_CLAIM = "common/reward_claim.png"
T_BACK = "common/back_button.png"
T_ANNOUNCEMENT = "common/announcement_title.png"


def dismiss_network_error(ctx: RunContext) -> ActionResult[Point]:
    """点掉网络错误弹窗的「重试」。

    没弹窗时返回 ``not_found`` —— 这是**正常情况**，调用方通常直接忽略。
    要当条件用就写 ``if dismiss_network_error(ctx).ok: ...``。
    """
    return actions.click_image(ctx.session, T_RETRY, confidence=0.85)


def dismiss_popups(ctx: RunContext) -> list[ActionResult[Point]]:
    """把当前屏幕上能认出来的弹窗都点掉（网络错误 / 奖励 / 公告）。

    返回每个的点击结果，方便日志里看出到底关掉了哪几个。
    顺序刻意是"网络错误 → 奖励 → 公告"：断线没处理好，点别的都没意义。
    """
    return [
        actions.click_image(ctx.session, T_RETRY, confidence=0.85),
        actions.click_image(ctx.session, T_REWARD_CLAIM, confidence=0.85),
        actions.click_image(ctx.session, T_POPUP_CLOSE, confidence=0.85),
    ]


def wait_popup_gone(ctx: RunContext, timeout: float = 5.0) -> ActionResult[Any]:
    """等公告弹窗消失 —— 点掉之后它通常有个淡出动画。

    用 ``wait_disappear`` 而不是 ``sleep``：动画快的时候立刻返回，
    慢的时候也不会提前动作。这是"等 UI 稳定"的标准写法。
    """
    return wait_disappear(ctx, ImageQuery(T_ANNOUNCEMENT), timeout=timeout)


def back_to_home(ctx: RunContext, attempts: int = 3) -> ActionResult[Point]:
    """一路退到首页：先关弹窗，再点返回。

    找不到「返回」按钮时返回 ``not_found``，而不是无限点 —— 无限重试是
    执行层 ``policy`` 的事，快捷方法只做"试一次"。
    """
    for _ in range(max(1, attempts)):
        dismiss_network_error(ctx)
        result = actions.click_image(ctx.session, T_BACK, confidence=0.85)
        if result.ok:
            return result
    return ActionResult.not_found(f"点了 {attempts} 次都没找到「返回」按钮（{T_BACK}）")


def wait_any_result(ctx: RunContext, timeout: float = 120.0) -> ActionResult[Any]:
    """等战斗结束 —— 胜利或失败任一出现。

    用 L4 的 ``wait_any_of``（内部循环截图 + 可被中止），
    比自己写 ``while True: sleep`` 短得多，也不会漏帧。
    """
    return wait_any_of(
        ctx.session,
        [
            ImageQuery("result/victory.png", confidence=0.9),
            ImageQuery("result/defeat.png", confidence=0.9),
        ],
        timeout=timeout,
        interval=0.5,
    )
