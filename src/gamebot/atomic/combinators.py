"""L4 组合子层 —— 多个查询之间如何协作。

两个子族：

**帧内组合子**（不截图、不吃时间预算，必须传入帧）::

    find_all_of     # Promise.all   全部命中才成功
    find_any_of     # Promise.race  任一命中即成功
    find_first_of   # 按顺序取第一个成功的
    find_none_of    # 全部失败才成功（判断"这些都不在"）
    count_hits      # 统计命中数量

**跨帧组合子**（自己循环截图 + 等待）::

    wait_any_of     # 等到任一命中
    wait_all_of     # 等到全部命中
    wait_until      # 等到任意谓词成立
    wait_stable     # 等到画面稳定
    wait_disappear  # 等到某查询不再命中

## 状态语义（统一规则，别记混）

| 情况 | 帧内组合子 | 跨帧组合子 |
|---|---|---|
| 达成 | ``success`` | ``success`` |
| 没达成 | ``not_found`` | ``timeout`` |
| 子查询**报错** | 原样透传 ``error`` | 立即 ``error`` 返回，不再重试 |

**为什么 error 要向上透传**：模板路径写错、OCR 没装、adb 掉线，这些
重试一万次也不会好。如果把它们当成"没命中"，问题到上层就表现为
"明明有这个按钮却找不到"，排查成本极高。唯一例外是 ``count_hits`` ——
它在打分投票，错误不计入命中但在 ``meta["errors"]`` 里列出来。

## 效率约定

* 帧内组合子**绝不截图**：帧必须由调用方传进来，保证一次判断看的是同一张画面。
* 5 个查询用 ``find_all_of`` 是 **1 次截图 + 5 次匹配**；
  写成 5 个独立查询就是 5 次截图。能用帧内组合子就别拆开写。
* 跨帧组合子每次轮询都产生**新帧**（不能复用，否则等的是同一张旧图）。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from time import perf_counter
from typing import TYPE_CHECKING, Any

from ..types import ActionResult, ActionStatus
from ..utils.logging import get_logger
from ..utils.timing import humanize

if TYPE_CHECKING:
    from .frame import Frame
    from .query import Query
    from .session import Session

log = get_logger("atomic.combinators")

__all__ = [
    "count_hits",
    "find_all_of",
    "find_any_of",
    "find_first_of",
    "find_none_of",
    "wait_all_of",
    "wait_any_of",
    "wait_disappear",
    "wait_stable",
    "wait_until",
]


# --------------------------------------------------------------------------- #
# 帧内组合子
# --------------------------------------------------------------------------- #
def _run_query(frame: Frame, query: Any) -> ActionResult[Any]:
    """执行一个查询描述符。

    接受两种形式：带 ``run(frame)`` 的对象（Query），或 ``callable(frame)``。
    查询自己抛异常不会打断整轮判断 —— 转成 ``error`` 结果交给组合子处理。
    """
    runner = getattr(query, "run", None)
    if not callable(runner):
        if callable(query):
            runner = query
        else:
            raise TypeError(f"不是合法的查询（既没有 run(frame) 也不可调用）: {query!r}")
    try:
        return runner(frame)
    except Exception as exc:
        return ActionResult.error(f"查询执行异常: {exc}", exc=exc, query=repr(query))


def _errors(results: Sequence[ActionResult[Any]]) -> list[ActionResult[Any]]:
    return [r for r in results if r.status is ActionStatus.ERROR]


def _first_error(results: Sequence[ActionResult[Any]]) -> ActionResult[Any] | None:
    errored = _errors(results)
    return errored[0] if errored else None


def _propagate(
    error_result: ActionResult[Any],
    results: Sequence[ActionResult[Any]],
    elapsed: float,
) -> ActionResult[Any]:
    """把子查询的 error 提升为整体 error，同时保留全部子结果。"""
    return ActionResult.error(
        f"查询出错: {error_result.message}",
        value=None,
        elapsed=elapsed,
        results=list(results),
        error_count=len(_errors(results)),
    )


def find_all_of(
    frame: Frame,
    queries: Sequence[Query],
) -> ActionResult[list[ActionResult[Any]]]:
    """全部命中才成功（``Promise.all`` 语义）。

    :return: 成功 ``success(value=[每个子结果, ...])``；
             有子查询报错 -> ``error``（带 ``meta["results"]``）；
             有子查询没命中 -> ``not_found(value=None, results=[...])``。

    空列表视为成功（"没有任何要求"就是全部满足）—— 这样流程配置里
    ``precondition`` 留空不会意外失败。
    """
    items = list(queries)
    started = perf_counter()
    if not items:
        return ActionResult.success([], elapsed=perf_counter() - started)

    results = [_run_query(frame, query) for query in items]
    elapsed = perf_counter() - started

    error = _first_error(results)
    if error is not None:
        return _propagate(error, results, elapsed)

    missed = [r for r in results if not r.ok]
    if missed:
        return ActionResult.not_found(
            f"{len(missed)}/{len(results)} 个查询未命中",
            value=None,
            elapsed=elapsed,
            results=results,
        )
    return ActionResult.success(results, elapsed=elapsed, results=results)


def find_any_of(
    frame: Frame,
    queries: Sequence[Query],
    short_circuit: bool = True,
) -> ActionResult[Any]:
    """任一命中即成功（``Promise.race`` 语义）。

    :param short_circuit: True 第一个成功就返回，``value`` 是那个子结果；
        False 跑完全部查询，``value`` 是**所有成功子结果的列表**。
        两种模式的 ``value`` 形状不同是刻意的：短路模式回答"谁先来"，
        全跑模式回答"都有谁"。

    :return: 成功 ``success``；一个都没成功且有报错 -> ``error``；否则 ``not_found``。
    """
    items = list(queries)
    started = perf_counter()
    results: list[ActionResult[Any]] = []

    if not items:
        return ActionResult.not_found("没有任何查询条件", elapsed=perf_counter() - started)

    for query in items:
        result = _run_query(frame, query)
        results.append(result)
        if short_circuit and result.ok:
            return ActionResult.success(
                result.value,
                elapsed=perf_counter() - started,
                result=result,
                results=results,
            )

    elapsed = perf_counter() - started
    hits = [r for r in results if r.ok]
    if hits:
        if short_circuit:
            # 短路模式必然在前面提前返回，这里只是保险
            return ActionResult.success(
                hits[0].value, elapsed=elapsed, result=hits[0], results=results
            )
        return ActionResult.success(
            [r.value for r in hits], elapsed=elapsed, hits=len(hits), results=results
        )

    error = _first_error(results)
    if error is not None:
        return _propagate(error, results, elapsed)
    return ActionResult.not_found(
        f"{len(results)} 个查询全部未命中", value=None, elapsed=elapsed, results=results
    )


def find_first_of(
    frame: Frame,
    queries: Sequence[Query],
) -> ActionResult[Any]:
    """按列表顺序依次执行，返回第一个成功的。

    和 ``find_any_of(short_circuit=True)`` 的区别：这里**顺序是语义的一部分**，
    用于表达优先级（先找"确认弹窗"，再找"主界面按钮"）。

    遇到子查询报错会**立即返回 error**，不再往后试 —— 错误通常意味着配置问题，
    继续用后面的条件做判断只会让现象更难解释。

    :return: 成功 ``success(value=..., index=第几个命中, query=...)``；
             全部没命中 ``not_found``。
    """
    items = list(queries)
    started = perf_counter()
    results: list[ActionResult[Any]] = []

    for index, query in enumerate(items):
        result = _run_query(frame, query)
        results.append(result)
        if result.ok:
            return ActionResult.success(
                result.value,
                elapsed=perf_counter() - started,
                index=index,
                total=len(items),
                query=repr(query),
                result=result,
                results=results,
            )
        if result.status is ActionStatus.ERROR:
            return _propagate(result, results, perf_counter() - started)

    return ActionResult.not_found(
        f"{len(items)} 个查询按顺序都没命中",
        value=None,
        elapsed=perf_counter() - started,
        results=results,
    )


def find_none_of(
    frame: Frame,
    queries: Sequence[Query],
) -> ActionResult[bool]:
    """全部失败才成功。用于判断"这些东西都不在屏幕上"。

    和 ``is_image_visible`` 一样，"不在"是一个**有效答案**，所以成功时
    ``value=True``；一旦有一个命中就返回 ``not_found``。

    子查询报错**必须**让整体失败 —— 把异常当成"不在"会导致流程误判。
    """
    items = list(queries)
    started = perf_counter()
    if not items:
        return ActionResult.success(
            True, message="没有条件，视为都不在", elapsed=perf_counter() - started
        )

    results = [_run_query(frame, query) for query in items]
    elapsed = perf_counter() - started

    error = _first_error(results)
    if error is not None:
        return _propagate(error, results, elapsed)

    hits = [r for r in results if r.ok]
    if hits:
        return ActionResult.not_found(
            f"{len(hits)} 个查询命中了（期望都不在）",
            value=False,
            elapsed=elapsed,
            results=results,
            hit_count=len(hits),
        )
    return ActionResult.success(True, elapsed=elapsed, results=results)


def count_hits(
    frame: Frame,
    queries: Sequence[Query],
) -> ActionResult[int]:
    """统计命中的查询数量，返回 ``success(value=int)``。

    用于打分、投票、优先级排序。**不关心是哪些中了。**

    两个约定：

    * 子查询报错**不计入命中**，但会在 ``meta["errors"]`` 里列出来 ——
      打分场景下，把错误当成命中或让整体失败都不合适；
    * ``VisibleQuery`` 这类"永远成功"的查询在这里没有意义（它总是算命中），
      打分请用 ``ImageQuery``。
    """
    items = list(queries)
    started = perf_counter()
    results = [_run_query(frame, query) for query in items]
    elapsed = perf_counter() - started

    hits = [r for r in results if r.ok]
    errored = _errors(results)
    return ActionResult.success(
        len(hits),
        elapsed=elapsed,
        total=len(items),
        results=results,
        errors=[r.message for r in errored],
    )


# --------------------------------------------------------------------------- #
# 跨帧组合子（自己循环截图）
# --------------------------------------------------------------------------- #
def _budget_left(started: float, timeout: float) -> bool:
    return perf_counter() - started < timeout


def wait_any_of(
    session: Session,
    queries: Sequence[Query],
    timeout: float = 10.0,
    interval: float = 0.3,
    short_circuit: bool = True,
) -> ActionResult[Any]:
    """轮询截图 + ``find_any_of``，直到任一命中或超时。

    每次轮询产生新 Frame（不能复用，否则等的是同一张旧图）。
    先截一帧再判断，所以 ``timeout=0`` 也会至少尝试一次。

    :return: 成功 ``success(value, frames=轮询帧数, frame=命中的那一帧)``；
             超时 ``timeout(message, last=最后一次结果, frames=N)``；
             子查询报错立即 ``error`` 返回（重试不会让模板出现）。
    """
    items = list(queries)
    started = perf_counter()
    frames = 0
    last: ActionResult[Any] | None = None

    while True:
        frame = session.capture()
        frames += 1
        last = find_any_of(frame, items, short_circuit=short_circuit)

        if last.ok:
            return ActionResult.success(
                last.value,
                elapsed=perf_counter() - started,
                frames=frames,
                frame=frame,
                result=last,
            )
        if last.status is ActionStatus.ERROR:
            return ActionResult.error(
                last.message, elapsed=perf_counter() - started, frames=frames, last=last
            )
        if not _budget_left(started, timeout):
            break
        time.sleep(interval)

    return ActionResult.timeout(
        f"等待 {len(items)} 个条件命中超时（{humanize(timeout)}，轮询 {frames} 次）",
        elapsed=perf_counter() - started,
        frames=frames,
        last=last,
    )


def wait_all_of(
    session: Session,
    queries: Sequence[Query],
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[list[ActionResult[Any]]]:
    """轮询截图 + ``find_all_of``，直到全部命中或超时。

    **重要语义**：全部命中必须在**同一帧**里成立。跨帧"先看到 A、再看到 B"
    不算数 —— 否则会漏掉"加载动画一闪而过"这类竞态。
    """
    items = list(queries)
    started = perf_counter()
    frames = 0
    last: ActionResult[Any] | None = None

    while True:
        frame = session.capture()
        frames += 1
        last = find_all_of(frame, items)

        if last.ok:
            return ActionResult.success(
                last.value,
                elapsed=perf_counter() - started,
                frames=frames,
                frame=frame,
                result=last,
            )
        if last.status is ActionStatus.ERROR:
            return ActionResult.error(
                last.message, elapsed=perf_counter() - started, frames=frames, last=last
            )
        if not _budget_left(started, timeout):
            break
        time.sleep(interval)

    return ActionResult.timeout(
        f"等待 {len(items)} 个条件全部命中超时（{humanize(timeout)}，轮询 {frames} 次）",
        elapsed=perf_counter() - started,
        frames=frames,
        last=last,
    )


def wait_until(
    session: Session,
    predicate: Callable[[Frame], bool],
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[Frame]:
    """轮询截图，执行谓词，直到返回 True 或超时。

    谓词自己抛异常会立即转成 ``error`` —— 谓词里的 bug 不该被当成"条件还没成立"
    而静默等到超时。

    :return: 成功时 ``success(value=命中的那帧)`` —— 把帧交出去，
             调用方可以继续在同一帧上做后续判断，避免时序漂移。
    """
    started = perf_counter()
    frames = 0

    while True:
        frame = session.capture()
        frames += 1
        try:
            matched = bool(predicate(frame))
        except Exception as exc:
            return ActionResult.error(
                f"谓词执行异常: {exc}",
                exc=exc,
                elapsed=perf_counter() - started,
                frames=frames,
            )

        if matched:
            return ActionResult.success(frame, elapsed=perf_counter() - started, frames=frames)
        if not _budget_left(started, timeout):
            break
        time.sleep(interval)

    return ActionResult.timeout(
        f"等待条件成立超时（{humanize(timeout)}，轮询 {frames} 次）",
        elapsed=perf_counter() - started,
        frames=frames,
    )


def _similarity(previous: Any, current: Any) -> float:
    """两张同尺寸图的相似度（1.0 = 完全一致）。

    用「灰度平均绝对差」而不是 ``matchTemplate``：后者在纯色区域会返回 NaN，
    还要处理"谁大谁小"，而判断"画面有没有在动"根本不需要那么精确。
    """
    import cv2
    import numpy as np

    if previous.shape != current.shape:
        return 0.0
    a = previous if previous.ndim == 2 else cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY)
    b = current if current.ndim == 2 else cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return 1.0 - float(diff.mean()) / 255.0


def wait_stable(
    session: Session,
    region: Any,
    threshold: float = 0.98,
    stable_frames: int = 3,
    timeout: float = 10.0,
    interval: float = 0.1,
) -> ActionResult[Frame]:
    """等待画面稳定：连续 ``stable_frames`` 帧区域内相似度都 >= ``threshold``。

    用途：点击"进入下一关"后，等动画播完、UI 不再变化，再开始识图。
    比死等 ``sleep(3)`` 可靠得多，也比它快。

    :param region: 源分辨率下的观察区域（``Region``）。区域越小越快，别整屏比对。
    :param stable_frames: 需要连续几帧相似。``1`` 没有意义（首帧没有可比对象），
        内部会按至少 2 处理，即第 ``stable_frames`` 帧返回。

    :return: 成功时返回"确认稳定"的那一帧（可直接复用做查询）。
    """
    started = perf_counter()
    previous: Any = None
    streak = 0
    frames = 0
    needed = max(2, stable_frames)
    score = 0.0

    while True:
        frame = session.capture_region(region)
        frames += 1
        image = frame.to_numpy()

        if previous is not None:
            score = _similarity(previous, image)
            streak = streak + 1 if score >= threshold else 0
            if streak >= needed - 1:
                return ActionResult.success(
                    frame,
                    elapsed=perf_counter() - started,
                    frames=frames,
                    score=score,
                    stable_frames=needed,
                )
        previous = image

        if not _budget_left(started, timeout):
            break
        time.sleep(interval)

    return ActionResult.timeout(
        f"等待画面稳定超时（{humanize(timeout)}，轮询 {frames} 次，"
        f"连续稳定 {streak + 1}/{needed} 帧）",
        elapsed=perf_counter() - started,
        frames=frames,
        streak=streak,
    )


def wait_disappear(
    session: Session,
    query: Query,
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[Frame]:
    """轮询直到 ``query`` 不再命中。

    用途：等 loading 转圈消失、等弹窗关闭。

    :return: 成功时返回"确认消失"的那一帧。
    """
    started = perf_counter()
    frames = 0
    last: ActionResult[Any] | None = None

    while True:
        frame = session.capture()
        frames += 1
        last = _run_query(frame, query)

        if last.status is ActionStatus.ERROR:
            return ActionResult.error(
                last.message, elapsed=perf_counter() - started, frames=frames, last=last
            )
        if not last.ok:
            return ActionResult.success(
                frame, elapsed=perf_counter() - started, frames=frames, last=last
            )
        if not _budget_left(started, timeout):
            break
        time.sleep(interval)

    return ActionResult.timeout(
        f"等待目标消失超时（{humanize(timeout)}，轮询 {frames} 次，仍然可见）",
        elapsed=perf_counter() - started,
        frames=frames,
        last=last,
    )
