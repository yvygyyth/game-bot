"""L5 动作层 —— 只操作输入，不关心截图。

本层的 13 个方法全部以 ``session`` 为唯一上下文：

* 坐标换算由 ``Session.to_screen()`` 负责，动作层不做缩放；
* 输入通过 ``Session.input``（``InputBackend``）下发，动作层不知道是
  Windows 还是 Android；
* ``click_image`` / ``click_text`` / ``drag_image`` 是语法糖，内部会截一次图，
  其余方法**都不截图**。

## 坐标约定（最容易写错的地方）

有两套坐标，绝不可混用：

* **逻辑坐标** —— 写脚本时用的坐标系。公开 API（``click_point`` / ``drag`` /
  ``move_to`` / ``scroll`` 的 ``point``）收的都是这个，内部会换算成源坐标。
* **源坐标** —— 截图上的真实像素。``find_image`` 返回的就是这个。

所以 ``click_image`` 拿到命中点后**不能再走一次 ``to_screen``** ——
``CoordinateMapper`` 不是幂等的，缩放过一次再缩一次就会点偏。
本模块因此把"源坐标点击"拆成 ``_click_source`` / ``_move_source`` /
``_drag_source`` 三个内部函数，语法糖直接调它们。

## 分层纪律

* 动作层**不判断游戏状态**，不重试，不等待 —— 重试和等待属于执行层；
* 动作层**不抛异常表达业务失败**，一律返回 ``ActionResult``；
  但底层后端真崩了（adb 断连、没装库）会转成 ``ActionResult.error``；
* 所有动作都要往 ``elapsed`` 里填真实耗时，方便执行层做预算控制。

⚠️ ``sleep`` 是唯一"什么都不做"的方法。它在设计上属于动作层，
因为流程脚本里"等一会儿"和点击一样是**基本操作**，且需要统一被记录 / 被打断。
"""

from __future__ import annotations

import time
from time import perf_counter
from typing import TYPE_CHECKING, Any

from ..types import ActionResult, Point, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from .session import Session

log = get_logger("atomic.actions")

__all__ = [
    "click_image",
    "click_logic_point",
    "click_point",
    "click_source_point",
    "click_text",
    "double_click",
    "drag",
    "drag_image",
    "hotkey",
    "move_to",
    "press_key",
    "right_click",
    "scroll",
    "sleep",
    "type_text",
]


# --------------------------------------------------------------------------- #
# 内部：源坐标版本（不做换算，供语法糖使用）
# --------------------------------------------------------------------------- #
def _click_source(
    session: Session,
    source: Point,
    *,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
    started: float | None = None,
) -> ActionResult[Point]:
    """按**源坐标**点击。已换算过的调用方用这个。"""
    began = started if started is not None else perf_counter()
    try:
        session.input.click(source, button=button, clicks=clicks, interval=interval)
    except Exception as exc:
        return ActionResult.error(
            f"点击 ({source.x},{source.y}) 失败: {exc}",
            exc=exc,
            elapsed=perf_counter() - began,
            point=source,
        )
    return ActionResult.success(source, elapsed=perf_counter() - began, point=source)


def _move_source(
    session: Session,
    source: Point,
    *,
    duration: float = 0.2,
    started: float | None = None,
) -> ActionResult[Point]:
    began = started if started is not None else perf_counter()
    try:
        session.input.move_to(source, duration)
    except Exception as exc:
        return ActionResult.error(
            f"移动指针到 ({source.x},{source.y}) 失败: {exc}",
            exc=exc,
            elapsed=perf_counter() - began,
            point=source,
        )
    return ActionResult.success(source, elapsed=perf_counter() - began, point=source)


def _drag_source(
    session: Session,
    start: Point,
    end: Point,
    *,
    duration: float = 0.5,
    button: str = "left",
    started: float | None = None,
) -> ActionResult[tuple[Point, Point]]:
    began = started if started is not None else perf_counter()
    try:
        session.input.drag(start, end, duration=duration, button=button)
    except Exception as exc:
        return ActionResult.error(
            f"拖拽 ({start.x},{start.y}) -> ({end.x},{end.y}) 失败: {exc}",
            exc=exc,
            elapsed=perf_counter() - began,
            start=start,
            end=end,
        )
    return ActionResult.success(
        (start, end), elapsed=perf_counter() - began, start=start, end=end
    )


def _to_source(
    session: Session, point: Point, started: float
) -> tuple[Point | None, ActionResult[Any] | None]:
    """逻辑坐标 -> 源坐标。换算失败时返回 (None, error)。"""
    try:
        return session.to_screen(point), None
    except Exception as exc:
        return None, ActionResult.error(
            f"坐标换算失败 {point.as_tuple()}: {exc}",
            exc=exc,
            elapsed=perf_counter() - started,
        )


def _first_point(result: ActionResult[Any]) -> Point | None:
    """从查询结果里取一个点。``find_image`` 返回 Point，``find_all_images`` 返回列表。"""
    value = result.value
    if isinstance(value, Point):
        return value
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], Point):
        return value[0]
    return None


# --------------------------------------------------------------------------- #
# 点击
# --------------------------------------------------------------------------- #
def click_point(
    session: Session,
    point: Point,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
) -> ActionResult[Point]:
    """点击坐标。

    :param point: **逻辑坐标**（写脚本时用的坐标系），内部会换算成源坐标。
    :return: ``success(value=实际点击的源坐标, logic_point=传入的逻辑坐标)``。
             返回换算后的坐标，方便日志和录屏回放对齐。
    """
    if (blocked := _dry_run_ok(session, "click_point")) is not None:
        return blocked
    started = perf_counter()
    source, failure = _to_source(session, point, started)
    if failure is not None:
        return failure
    assert source is not None
    result = _click_source(
        session, source, button=button, clicks=clicks, interval=interval, started=started
    )
    return result.with_meta(logic_point=point)


def click_image(
    session: Session,
    template: str,
    region: Region | None = None,
    confidence: float = 0.9,
    button: str = "left",
    offset: tuple[int, int] = (0, 0),
) -> ActionResult[Point]:
    """识图并点击 —— "截一次图 + find_image + click_point" 的语法糖。

    :param offset: 相对命中中心的偏移（**源分辨率**像素）。
        点图标左上角、或避开图标中心的可点击区域时用。
    :return: 命中并点击成功返回 ``success(value=命中点)``；
             没找到返回 ``not_found``（**不会乱点**，这是安全边界）；
             模板缺失之类的底层错误原样透传 ``error``。
    """
    if (blocked := _dry_run_ok(session, "click_image")) is not None:
        return blocked
    started = perf_counter()
    frame = session.capture()
    found = frame.find_image(template, region=region, confidence=confidence)
    if not found.ok:
        # 找不到就绝不点 —— 错误也原样往上抛，别把"模板不存在"变成"随便点一下"
        return ActionResult(
            found.status, None, f"{template} 未命中，取消点击", found.elapsed, found.meta
        )

    hit = _first_point(found)
    if hit is None:
        return ActionResult.error(
            f"{template} 命中但结果里没有坐标", elapsed=perf_counter() - started
        )

    source = hit.offset(offset[0], offset[1])
    result = _click_source(session, source, button=button, started=started)
    return result.with_meta(
        template=template,
        hit_point=hit,
        offset=offset,
        score=found.meta.get("score"),
    )


def click_logic_point(
    session: Session,
    point: Point,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
) -> ActionResult[Point]:
    """按**逻辑坐标**点击 —— 给"坐标来自配置"的调用方用。

    和 :func:`click_source_point` 的分工，就是这个项目最容易搞错的地方，
    所以两个入口刻意分开、名字里带坐标基准：

    * 坐标**来自配置 / 脚本里写死的相对坐标**（``ClickStep(Point(960, 540))``）
      -> 用本函数，内部 ``session.to_screen()`` 换算成源坐标；
    * 坐标**来自 ``find_image`` / ``find_all_images``**（截图上的真实像素）
      -> 用 :func:`click_source_point`，**绝不能再换算一次**：
      ``CoordinateMapper`` 不是幂等的，缩放过一次再缩一次就会点偏。

    :return: ``success(value=换算后的源坐标, logic_point=传入的逻辑坐标)``。
    """
    if (blocked := _dry_run_ok(session, "click_logic_point")) is not None:
        return blocked
    started = perf_counter()
    source, failure = _to_source(session, point, started)
    if failure is not None:
        return failure
    assert source is not None
    result = _click_source(
        session, source, button=button, clicks=clicks, interval=interval, started=started
    )
    return result.with_meta(logic_point=point)


def click_source_point(
    session: Session,
    point: Point,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
) -> ActionResult[Point]:
    """按**源坐标**点击 —— 给"已经拿到屏幕像素点"的调用方用。

    :param point: **源坐标**（截图上的真实像素），不做任何换算。

    什么时候用它：点一个**不是** ``find_image`` 单点结果的坐标。典型场景是
    ``find_all_images`` 拿到的点列表（关卡列表、背包格子、技能栏里的第 3 个技能）::

        found = ctx.frame().find_all_images("stage_button.png")
        if found.ok and len(found.value) > 2:
            click_source_point(ctx.session, found.value[2])   # 第 3 个关卡

    ⚠️ 这类坐标**不能再走一次** :func:`click_point`：那个收的是逻辑坐标，
    配了 ``logic_size`` 缩放时会二次换算，点偏。这也是它单独存在的原因 ——
    两个坐标系必须有各自的入口，混用是这类脚本最常见的坐标 bug。
    """
    if (blocked := _dry_run_ok(session, "click_source_point")) is not None:
        return blocked
    return _click_source(session, point, button=button, clicks=clicks, interval=interval)


def click_text(
    session: Session,
    text: str,
    region: Region | None = None,
    lang: str = "ch",
    confidence: float = 0.8,
) -> ActionResult[Point]:
    """查文本并点击。用于"开始游戏""确认"这类按钮，避免为每个按钮截模板图。"""
    if (blocked := _dry_run_ok(session, "click_text")) is not None:
        return blocked
    started = perf_counter()
    frame = session.capture()
    found = frame.find_text(text, region=region, lang=lang, confidence=confidence)
    if not found.ok:
        return ActionResult(
            found.status, None, f"文本 {text!r} 未命中，取消点击", found.elapsed, found.meta
        )

    hit = _first_point(found)
    if hit is None:
        return ActionResult.error(
            f"文本 {text!r} 命中但结果里没有坐标", elapsed=perf_counter() - started
        )

    result = _click_source(session, hit, started=started)
    return result.with_meta(text=text, hit_point=hit, score=found.meta.get("score"))


def double_click(
    session: Session,
    point: Point,
    interval: float = 0.1,
) -> ActionResult[Point]:
    """双击。

    :param interval: 两次点击之间的间隔。**给太大游戏会认成两次单击**，
        一般 0.05~0.12 之间。
    """
    if (blocked := _dry_run_ok(session, "double_click")) is not None:
        return blocked
    return click_point(session, point, clicks=2, interval=interval)


def right_click(session: Session, point: Point) -> ActionResult[Point]:
    """右键点击。"""
    if (blocked := _dry_run_ok(session, "right_click")) is not None:
        return blocked
    return click_point(session, point, button="right")


# --------------------------------------------------------------------------- #
# 移动 / 拖拽 / 滚轮
# --------------------------------------------------------------------------- #
def move_to(
    session: Session,
    point: Point,
    duration: float = 0.2,
) -> ActionResult[Point]:
    """移动鼠标 / 指针。

    :param duration: 移动耗时。**不要总是给 0** —— 很多游戏检测瞬时跳变，
        而且 hover 类 UI 不会触发。
    """
    if (blocked := _dry_run_ok(session, "move_to")) is not None:
        return blocked
    started = perf_counter()
    source, failure = _to_source(session, point, started)
    if failure is not None:
        return failure
    assert source is not None
    result = _move_source(session, source, duration=duration, started=started)
    return result.with_meta(logic_point=point)


def drag(
    session: Session,
    start: Point,
    end: Point,
    duration: float = 0.5,
    button: str = "left",
) -> ActionResult[tuple[Point, Point]]:
    """拖拽。

    Windows 后端内部要拆成 mouseDown -> 中间点 -> mouseUp；
    Android 后端直接 ``input swipe``。这些差异由后端吸收。

    :return: ``success(value=(起点源坐标, 终点源坐标))``。
    """
    if (blocked := _dry_run_ok(session, "drag")) is not None:
        return blocked
    started = perf_counter()
    source_start, failure = _to_source(session, start, started)
    if failure is not None:
        return failure
    source_end, failure = _to_source(session, end, started)
    if failure is not None:
        return failure
    assert source_start is not None and source_end is not None
    result = _drag_source(
        session, source_start, source_end, duration=duration, button=button, started=started
    )
    return result.with_meta(logic_start=start, logic_end=end)


def drag_image(
    session: Session,
    source_template: str,
    target: Point,
    duration: float = 0.5,
    confidence: float = 0.9,
) -> ActionResult[tuple[Point, Point]]:
    """识图并把图上的东西拖到目标点。

    :param target: **逻辑坐标**。而拖拽起点是识图命中点（源坐标）——
        这是刻意的：目标点通常来自配置，起点来自画面。
    """
    if (blocked := _dry_run_ok(session, "drag_image")) is not None:
        return blocked
    started = perf_counter()
    frame = session.capture()
    found = frame.find_image(source_template, confidence=confidence)
    if not found.ok:
        return ActionResult(
            found.status,
            None,
            f"{source_template} 未命中，取消拖拽",
            found.elapsed,
            found.meta,
        )

    origin = _first_point(found)
    if origin is None:
        return ActionResult.error(
            f"{source_template} 命中但结果里没有坐标", elapsed=perf_counter() - started
        )

    source_target, failure = _to_source(session, target, started)
    if failure is not None:
        return failure
    assert source_target is not None

    result = _drag_source(
        session, origin, source_target, duration=duration, started=started
    )
    return result.with_meta(
        template=source_template, logic_target=target, score=found.meta.get("score")
    )


def scroll(
    session: Session,
    clicks: int,
    point: Point | None = None,
) -> ActionResult[int]:
    """滚轮。

    :param clicks: 正数向上 / 向前，负数向下 / 向后。
    :param point: **逻辑坐标**；先移到该点再滚（很多列表需要指针悬停在上面才响应）。
    :return: ``success(value=实际滚动格数)``。
    """
    if (blocked := _dry_run_ok(session, "scroll")) is not None:
        return blocked
    started = perf_counter()
    source: Point | None = None
    if point is not None:
        source, failure = _to_source(session, point, started)
        if failure is not None:
            return failure

    try:
        session.input.scroll(clicks, source)
    except Exception as exc:
        return ActionResult.error(
            f"滚轮 {clicks} 失败: {exc}", exc=exc, elapsed=perf_counter() - started
        )
    return ActionResult.success(
        clicks, elapsed=perf_counter() - started, point=source, logic_point=point
    )


# --------------------------------------------------------------------------- #
# 键盘
# --------------------------------------------------------------------------- #
def type_text(
    session: Session,
    text: str,
    interval: float = 0.05,
) -> ActionResult[str]:
    """输入文本。

    ⚠️ 中文 / 非 ASCII：Windows 侧走剪贴板粘贴，Android 侧需要 ADBKeyboard。
    这部分由后端实现决定，调用方不要假设 ``type_text("中文")`` 一定能用 ——
    真的不支持时后端会抛错，这里会转成 ``error``。

    :return: ``success(value=输入的文本)``。
    """
    if (blocked := _dry_run_ok(session, "type_text")) is not None:
        return blocked
    started = perf_counter()
    try:
        session.input.type_text(text, interval=interval)
    except Exception as exc:
        return ActionResult.error(
            f"输入文本失败: {exc}", exc=exc, elapsed=perf_counter() - started, text=text
        )
    return ActionResult.success(text, elapsed=perf_counter() - started)


def press_key(
    session: Session,
    key: str,
    presses: int = 1,
    interval: float = 0.1,
) -> ActionResult[str]:
    """按键。

    :param key: 统一键名（``"enter"`` / ``"esc"`` / ``"space"`` / ``"f1"`` / ``"a"``），
        由后端映射到平台键码。自定义映射放 ``config``，不要写死在业务脚本里。
    :return: ``success(value=键名)``。
    """
    if (blocked := _dry_run_ok(session, "press_key")) is not None:
        return blocked
    started = perf_counter()
    try:
        session.input.press_key(key, presses=presses, interval=interval)
    except Exception as exc:
        return ActionResult.error(
            f"按键 {key!r} 失败: {exc}",
            exc=exc,
            elapsed=perf_counter() - started,
            key=key,
        )
    return ActionResult.success(key, elapsed=perf_counter() - started, presses=presses)


def hotkey(session: Session, keys: list[str]) -> ActionResult[list[str]]:
    """组合键，如 ``["ctrl", "s"]``。

    :return: ``success(value=按键列表)``。
    """
    if (blocked := _dry_run_ok(session, "hotkey")) is not None:
        return blocked
    started = perf_counter()
    combo = list(keys)
    try:
        session.input.hotkey(combo)
    except Exception as exc:
        return ActionResult.error(
            f"组合键 {'+'.join(combo)} 失败: {exc}",
            exc=exc,
            elapsed=perf_counter() - started,
            keys=combo,
        )
    return ActionResult.success(combo, elapsed=perf_counter() - started)


# --------------------------------------------------------------------------- #
# 等待
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 空跑拦截
# --------------------------------------------------------------------------- #
def _dry_run_ok(session: Session, what: str, **meta: Any) -> ActionResult[Any] | None:
    """空跑时**在动作下发那一刻**拦下，返回假装成功；否则返回 None（照常执行）。

    为什么拦在这里（而不是让执行层判断这一步像不像动作）：
    判断像不像动作要么看类型名、要么维护一张注册表 —— 两条路都要额外一份
    元数据，而且漏了就会在空跑时真的去点游戏。放在下发那一刻，
    **拦住是必然的**（所有动作都走这里）。

    `sleep` 不拦：空跑也要能等，否则空跑一遍会把流程跑成完全不同的节奏。
    """
    if not getattr(session, "dry_run", False):
        return None
    return ActionResult.success(None, message=f"空跑，未执行: {what}", dry_run=True, **meta)

def sleep(seconds: float, session: Session | None = None) -> ActionResult[float]:
    """固定等待。

    :param session: 给了就走 ``session.sleep()`` —— **可被中止立刻唤醒**；
        没给就是最朴素的 ``time.sleep``（不知道上下文的场合用）。
        强烈建议在有 session 的地方都传进来，否则点了停止要等满这一觉。

    :return: ``success(value=请求的秒数, elapsed=实际耗时)``。
    :raises Cancelled: 等待期间被中止（只在传了 session 时可能发生）。
    """
    started = perf_counter()
    if session is not None:
        session.sleep(seconds)
    elif seconds > 0:
        time.sleep(seconds)
    return ActionResult.success(seconds, elapsed=perf_counter() - started)
