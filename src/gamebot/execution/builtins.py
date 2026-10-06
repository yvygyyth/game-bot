"""内置步骤 —— 一组普通函数，业务脚本按需组合。

## 这些只是**常用组合**，不是必须用的 API

写业务脚本时可以直接调原子层（``gamebot.atomic``），也可以在这里加自己的函数。
放在这儿的是"几乎每个脚本都要写一遍"的那几个：

| 函数 | 干什么 |
|---|---|
| :func:`click_image` | 找到某张图并点它（找不到就返回 ``not_found``） |
| :func:`click_point` | 点一个点（逻辑坐标） |
| :func:`click_text` | 找到某段文字并点它 |
| :func:`press` | 按一个键 |
| :func:`sleep` | 等一会儿（可被停止打断） |
| :func:`shoot` | 截一张存下来（排查用） |
| :func:`run_all` | 按顺序跑一串步骤，**某一步失败就停在那里** |

## 为什么``run_all``失败就停

一个步骤失败（多半是识图没命中）意味着**前提没成立**，那么"后面那几步"
的前提（"前一步成功了"）也就没了 —— 继续跑只会在错的状态上乱操作。
所以停在失败那一步，把结果交回上层：上层会拿实测状态去重定位。
（这修掉了一个真实问题：以前默认策略下失败**继续跑后续步骤**。）

## 不做的事

* **不重试**（那是重定位的事）；
* **不轮询等待**（"等某张图出现"用原子层的 ``wait_any_of`` / ``wait_disappear``，
  它们自带 ``timeout`` / ``interval``）；
* **不记账**（想记就调 ``ctx.log(...)``）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.atomic.combinators import wait_any_of, wait_disappear
from gamebot.types import ActionResult, Point, Region

from .step import StepFunc, step_name

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "click_image",
    "click_point",
    "click_text",
    "press",
    "run_all",
    "sequence",
    "shoot",
    "sleep",
    "wait_for",
    "wait_gone",
]


def click_image(
    ctx: RunContext,
    template: str,
    *,
    region: Region | None = None,
    confidence: float = 0.9,
    settle: float = 0.0,
) -> ActionResult[Any]:
    """找到 ``template`` 并点它。找不到就 ``not_found``（上层会去重定位）。

    :param region: 搜索区域（客户区坐标）。**收窄它往往比多做一个模板有效。**
    :param settle: 点完等多久。界面有过渡动画时给一点，别让下一步看旧画面。
    """
    found = ctx.frame().find_image(template, region=region, confidence=confidence)
    if not found.ok or found.value is None:
        return ActionResult.not_found(
            f"没看到 {template}",
            template=template,
            region=region.to_tuple() if region else None,
            score=found.meta.get("score", 0.0),
        )
    clicked = actions.click_source_point(ctx.session, found.value)
    if not clicked.ok:
        return clicked
    if settle:
        ctx.sleep(settle)
    # 画面变了，作废当前帧 —— 下一步必须重新截，否则会拿旧图判断
    ctx.invalidate_frame()
    return ActionResult.success(
        found.value,
        action="click",
        template=template,
        score=found.meta.get("score", 0.0),
        message=f"点了 {template}",
    )


def click_point(
    ctx: RunContext, point: Point, *, settle: float = 0.0
) -> ActionResult[Any]:
    """点一个**逻辑坐标**的点。

    注意坐标基准：``Frame`` 和 ``find_image`` 返回的是**源坐标**（客户区相对），
    而这里收的是逻辑坐标 —— 要拿源坐标去点就用 :func:`gamebot.atomic.actions.click_source_point`。
    两个基准混用会点偏一个窗口位置，而大目标上看不出来。
    """
    result = actions.click_logic_point(ctx.session, point)
    if result.ok:
        if settle:
            ctx.sleep(settle)
        ctx.invalidate_frame()
    return result


def click_text(
    ctx: RunContext,
    text: str,
    *,
    region: Region | None = None,
    confidence: float = 0.8,
    exact: bool = False,
    settle: float = 0.0,
) -> ActionResult[Any]:
    """OCR 找到 ``text`` 并点它。需要装了 OCR 后端。"""
    found = ctx.frame().find_text(
        text, region=region, confidence=confidence, exact_match=exact
    )
    if not found.ok or found.value is None:
        return ActionResult.not_found(
            f"没看到文字 {text!r}", text=text, score=found.meta.get("score", 0.0)
        )
    clicked = actions.click_source_point(ctx.session, found.value)
    if not clicked.ok:
        return clicked
    if settle:
        ctx.sleep(settle)
    ctx.invalidate_frame()
    return ActionResult.success(found.value, action="click_text", text=text)


def press(ctx: RunContext, key: str, *, settle: float = 0.0) -> ActionResult[Any]:
    """按一个键（如 ``"esc"`` / ``"space"``）。"""
    result = actions.press_key(ctx.session, key)
    if result.ok:
        if settle:
            ctx.sleep(settle)
        ctx.invalidate_frame()
    return result


def sleep(ctx: RunContext, seconds: float) -> ActionResult[Any]:
    """等一会儿。**可被"停止"打断**（``ctx.sleep`` 是可中止的等待）。"""
    return actions.sleep(seconds, ctx.session)


def wait_for(
    ctx: RunContext,
    query: Any,
    *,
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[Any]:
    """**等某个画面出现**（轮询，最多 ``timeout`` 秒）。

    这只是原子层 ``wait_any_of`` 的薄封装 —— 轮询、超时、间隔都是它自己的参数。
    等的是"画面变过来"，所以成功之后作废当前帧。
    """
    result = wait_any_of(ctx.session, [query], timeout=timeout, interval=interval)
    if result.ok:
        ctx.invalidate_frame()
    return result


def wait_gone(
    ctx: RunContext,
    query: Any,
    *,
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[Any]:
    """**等某个画面消失**（轮询，最多 ``timeout`` 秒）。"""
    result = wait_disappear(ctx.session, query, timeout=timeout, interval=interval)
    if result.ok:
        ctx.invalidate_frame()
    return result


def shoot(ctx: RunContext, name: str) -> ActionResult[Any]:
    """截一张存下来（排查用）。存到哪由配置的 ``paths.screenshots`` 决定。"""
    frame = ctx.frame()
    return ActionResult.success(frame, action="capture", name=name)


def run_all(ctx: RunContext, *steps: StepFunc) -> ActionResult[Any]:
    """按顺序跑一串步骤，**某一步失败就停在那里**。

    为什么要停在失败处：一步失败（多半是识图没命中）意味着它的前提没成立，
    而后面那些步骤的前提正是"前一步成功了" —— 继续跑只会在错的状态上乱操作。
    停下来把结果交回上层，上层拿实测状态去重定位。

    （这修掉了一个真实问题：以前默认策略下失败会**继续跑后面的步骤**。）

    :return: 全成功 -> ``success``；某步失败 -> 那一步的结果原样返回
        （``meta["stopped_at"]`` 写明停在哪一步）。
    """
    for index, step in enumerate(steps):
        result = step(ctx)
        if not result.ok:
            # 保留原始状态（not_found / error），只补上"停在哪"
            return result.with_meta(stopped_at=step_name(step), stopped_index=index)
    return ActionResult.success({"steps": len(steps)})


def sequence(steps: Sequence[StepFunc]) -> StepFunc:
    """把一串步骤打包成**一个**步骤（给 ``Node(steps=[...])`` 用）。

    和 :func:`run_all` 的区别只是写法：``sequence([a, b])`` 适合动态拼。
    """

    def _sequence(ctx: RunContext) -> ActionResult[Any]:
        return run_all(ctx, *steps)

    _sequence.__name__ = f"sequence({len(steps)})"
    return _sequence
