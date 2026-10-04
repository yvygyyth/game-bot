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
| **截图失败** | 不适用 | 立即 ``error`` 返回，不再重试 |

**为什么 error 要向上透传**：模板路径写错、OCR 没装、adb 掉线，这些
重试一万次也不会好。如果把它们当成"没命中"，问题到上层就表现为
"明明有这个按钮却找不到"，排查成本极高。唯一例外是 ``count_hits`` ——
它在打分投票，错误不计入命中但在 ``meta["errors"]`` 里列出来。

**为什么截图失败也要转成 error**：``Session.capture()`` 返回 ``Frame``，
没法用返回值表达失败，所以窗口被关掉时它是抛异常的。跨帧组合子必须兜住它，
否则"窗口没了"会变成一条穿过原子层的 traceback，而不是一个可处理的
``ActionResult``。注意这是**异常路径兜底**，不是把异常当正常流程用。

## 效率约定

* 帧内组合子**绝不截图**：帧必须由调用方传进来，保证一次判断看的是同一张画面。
* 5 个查询用 ``find_all_of`` 是 **1 次截图 + 5 次匹配**；
  写成 5 个独立查询就是 5 次截图。能用帧内组合子就别拆开写。
* 跨帧组合子每次轮询都产生**新帧**（不能复用，否则等的是同一张旧图）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from time import perf_counter
from typing import TYPE_CHECKING, Any

from ..types import ActionResult, ActionStatus, Region
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
def _capture_failure(exc: BaseException) -> ActionResult[Any]:
    """把截图异常转成 ``error`` 结果。

    跨帧组合子**必须**兜住 ``session.capture()``：它要返回 ``Frame``，没法用返回值
    表达失败，所以窗口关闭、adb 掉线时它是**抛异常**的。而组合子的契约是
    "失败一律给 ActionResult" —— 漏了这一步，异常会穿过组合子直接砸到流程层，
    把"窗口没了"变成一条 traceback。

    **不重试**：截图失败通常意味着目标已经消失或设备断开，重试只是把等待时间拖满。
    要重试是执行层 ``StepPolicy`` 的事，原子层不掺和。
    """
    return ActionResult.error(f"截图失败，等待中止: {exc}", exc=exc)


def _poll(
    session: Session,
    *,
    timeout: float,
    interval: float,
    step: Callable[[Frame], ActionResult[Any] | None],
    on_timeout: Callable[[int], ActionResult[Any]],
    region: Region | None = None,
) -> ActionResult[Any]:
    """跨帧轮询骨架 —— 5 个 ``wait_*`` 共用。

    把所有"容易在 5 个地方各写漏一次"的事收在一处：

    * ``session.raise_if_stopped()`` —— 响应中止（毫秒级，不必等满 timeout）
    * 兜住 ``capture()`` 的异常 —— 转成 ``error`` 而不是让 traceback 穿出去
    * 计时与超时判定
    * ``session.sleep(interval)`` —— 可被中止立刻唤醒的间隔等待

    :param step: 每帧调一次。返回非 None 表示"可以结束了"，直接作为结果返回；
                 返回 None 表示继续轮询。跨帧状态（如上一次的图、连击计数）
                 由调用方用闭包持有 —— 骨架不需要知道。
    :param on_timeout: 超时时调用，参数是已轮询帧数，返回 timeout 结果。
                       ``frames`` / ``elapsed`` 由骨架统一补上。
    :param region: 给了就抓该区域（``wait_stable`` 用），否则抓整帧。
    """
    started = perf_counter()
    frames = 0

    while True:
        session.raise_if_stopped()

        try:
            frame = session.capture() if region is None else session.capture_region(region)
        except Exception as exc:  # 截图失败不重试，直接转成 error
            return _capture_failure(exc).with_meta(frames=frames).with_elapsed(
                perf_counter() - started
            )
        frames += 1

        outcome = step(frame)
        if outcome is not None:
            return outcome.with_meta(frames=frames).with_elapsed(perf_counter() - started)

        if perf_counter() - started >= timeout:
            return on_timeout(frames).with_meta(frames=frames).with_elapsed(
                perf_counter() - started
            )

        session.sleep(interval)


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
             子查询报错或**截图失败**立即 ``error`` 返回，不再重试
             （模板不会自己出现，窗口也不会自己回来）。
    :raises Cancelled: 收到中止请求时**立即**抛出，不会等满 timeout。
    """
    items = list(queries)
    last: ActionResult[Any] | None = None

    def step(frame: Frame) -> ActionResult[Any] | None:
        nonlocal last
        last = find_any_of(frame, items, short_circuit=short_circuit)
        if last.ok:
            return ActionResult.success(last.value, frame=frame, result=last)
        if last.status is ActionStatus.ERROR:
            return last  # 子查询报错原样透传（frames / elapsed 由 _poll 补）
        return None

    def on_timeout(frames: int) -> ActionResult[Any]:
        return ActionResult.timeout(
            f"等待 {len(items)} 个条件命中超时（{humanize(timeout)}，轮询 {frames} 次）",
            last=last,
        )

    return _poll(session, timeout=timeout, interval=interval, step=step, on_timeout=on_timeout)


def wait_all_of(
    session: Session,
    queries: Sequence[Query],
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[list[ActionResult[Any]]]:
    """轮询截图 + ``find_all_of``，直到全部命中或超时。

    **重要语义**：全部命中必须在**同一帧**里成立。跨帧"先看到 A、再看到 B"
    不算数 —— 否则会漏掉"加载动画一闪而过"这类竞态。

    :raises Cancelled: 收到中止请求时立即抛出。
    """
    items = list(queries)
    last: ActionResult[Any] | None = None

    def step(frame: Frame) -> ActionResult[Any] | None:
        nonlocal last
        last = find_all_of(frame, items)
        if last.ok:
            return ActionResult.success(last.value, frame=frame, result=last)
        if last.status is ActionStatus.ERROR:
            return last
        return None

    def on_timeout(frames: int) -> ActionResult[Any]:
        return ActionResult.timeout(
            f"等待 {len(items)} 个条件全部命中超时（{humanize(timeout)}，轮询 {frames} 次）",
            last=last,
        )

    return _poll(session, timeout=timeout, interval=interval, step=step, on_timeout=on_timeout)


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
    :raises Cancelled: 收到中止请求时立即抛出。
    """

    def step(frame: Frame) -> ActionResult[Any] | None:
        try:
            matched = bool(predicate(frame))
        except Exception as exc:  # 谓词的 bug 不该被当成"条件未成立"而静默等超时
            return ActionResult.error(f"谓词执行异常: {exc}", exc=exc)
        return ActionResult.success(frame) if matched else None

    def on_timeout(frames: int) -> ActionResult[Any]:
        return ActionResult.timeout(
            f"等待条件成立超时（{humanize(timeout)}，轮询 {frames} 次）"
        )

    return _poll(session, timeout=timeout, interval=interval, step=step, on_timeout=on_timeout)


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
    :raises Cancelled: 收到中止请求时立即抛出。
    """
    needed = max(2, stable_frames)
    previous: Any = None
    streak = 0
    score = 0.0

    def step(frame: Frame) -> ActionResult[Any] | None:
        nonlocal previous, streak, score
        image = frame.to_numpy()

        if previous is not None:
            score = _similarity(previous, image)
            streak = streak + 1 if score >= threshold else 0
            if streak >= needed - 1:
                return ActionResult.success(frame, score=score, stable_frames=needed)
        previous = image
        return None

    def on_timeout(frames: int) -> ActionResult[Any]:
        return ActionResult.timeout(
            f"等待画面稳定超时（{humanize(timeout)}，轮询 {frames} 次，"
            f"连续稳定 {streak + 1}/{needed} 帧）",
            streak=streak,
        )

    return _poll(
        session,
        timeout=timeout,
        interval=interval,
        step=step,
        on_timeout=on_timeout,
        region=region,
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
    :raises Cancelled: 收到中止请求时立即抛出。
    """
    last: ActionResult[Any] | None = None

    def step(frame: Frame) -> ActionResult[Any] | None:
        nonlocal last
        last = _run_query(frame, query)
        if last.status is ActionStatus.ERROR:
            return last
        if not last.ok:
            return ActionResult.success(frame, last=last)
        return None

    def on_timeout(frames: int) -> ActionResult[Any]:
        return ActionResult.timeout(
            f"等待目标消失超时（{humanize(timeout)}，轮询 {frames} 次，仍然可见）",
            last=last,
        )

    return _poll(session, timeout=timeout, interval=interval, step=step, on_timeout=on_timeout)
