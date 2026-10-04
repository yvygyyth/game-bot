"""L5 动作层 —— 只操作输入，不关心截图。

本层的 13 个方法全部以 ``session`` 为唯一上下文：

* 坐标换算由 ``Session.to_screen()`` 负责，动作层不做缩放；
* 输入通过 ``Session.input``（``InputBackend``）下发，动作层不知道是
  Windows 还是 Android；
* ``click_image`` / ``click_text`` / ``drag_image`` 是语法糖，内部会截一次图，
  其余方法**都不截图**。

分层纪律：

* 动作层**不判断游戏状态**，不重试，不等待 —— 重试和等待属于执行层；
* 动作层**不抛异常表达业务失败**，一律返回 ``ActionResult``；
  但底层后端真崩了（adb 断连）会转成 ``ActionResult.error``；
* 所有动作都要往 ``elapsed`` 里填真实耗时，方便执行层做预算控制。

⚠️ ``sleep`` 是唯一"什么都不做"的方法。它在设计上属于动作层，
因为流程脚本里"等一会儿"和点击一样是**基本操作**，且需要统一被记录 / 被打断。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..types import ActionResult, Point, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from .session import Session

log = get_logger("atomic.actions")

__all__ = [
    "click_image",
    "click_point",
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
    :return: ``success(value=实际点击的源坐标)``。返回换算后的坐标，
             方便日志和录屏回放对齐。
    """
    raise NotImplementedError("待实现：session.to_screen(point) -> session.input.click(...)")


def click_image(
    session: Session,
    template: str,
    region: Region | None = None,
    confidence: float = 0.9,
    button: str = "left",
    offset: tuple[int, int] = (0, 0),
) -> ActionResult[Point]:
    """识图并点击 —— "截一次图 + find_image + click_point" 的语法糖。

    :param offset: 相对命中中心的偏移。点图标左上角、或避开图标中心的可点击区域时用。
    :return: 命中并点击成功返回 ``success(value=命中点)``；
             没找到返回 ``not_found``（**不会乱点**，这是和自我定位的安全边界）。
    """
    raise NotImplementedError("待实现：session.capture().find_image(...) -> click_point")


def click_text(
    session: Session,
    text: str,
    region: Region | None = None,
    lang: str = "ch",
    confidence: float = 0.8,
) -> ActionResult[Point]:
    """查文本并点击。用于"开始游戏""确认"这类按钮，避免为每个按钮截模板图。"""
    raise NotImplementedError("待实现")


def double_click(
    session: Session,
    point: Point,
    interval: float = 0.1,
) -> ActionResult[Point]:
    """双击。"""
    raise NotImplementedError("待实现：clicks=2，注意 interval 要够短才被识别为双击")


def right_click(session: Session, point: Point) -> ActionResult[Point]:
    """右键点击。"""
    raise NotImplementedError("待实现")


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
        也会导致 hover 类 UI 不触发。
    """
    raise NotImplementedError("待实现")


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
    """
    raise NotImplementedError("待实现")


def drag_image(
    session: Session,
    source_template: str,
    target: Point,
    duration: float = 0.5,
    confidence: float = 0.9,
) -> ActionResult[tuple[Point, Point]]:
    """识图并把图上的东西拖到目标点。"""
    raise NotImplementedError("待实现：find_image(source_template) -> drag(命中点, target)")


def scroll(
    session: Session,
    clicks: int,
    point: Point | None = None,
) -> ActionResult[int]:
    """滚轮。

    :param clicks: 正数向上 / 向前，负数向下 / 向后。
    :param point: 先移到该点再滚（很多列表需要指针悬停在上面才响应）。
    """
    raise NotImplementedError("待实现：Android 侧用 swipe 模拟，幅度需标定")


# --------------------------------------------------------------------------- #
# 键盘
# --------------------------------------------------------------------------- #
def type_text(
    session: Session,
    text: str,
    interval: float = 0.05,
) -> ActionResult[str]:
    """输入文本。

    ⚠️ 中文 / 非 ASCII：Windows 侧通常要走剪贴板粘贴，Android 侧需要 ADBKeyboard，
    这部分由后端实现决定，调用方不要假设 ``type_text("中文")`` 一定能用。
    """
    raise NotImplementedError("待实现")


def press_key(
    session: Session,
    key: str,
    presses: int = 1,
    interval: float = 0.1,
) -> ActionResult[str]:
    """按键。

    :param key: 统一键名（``"enter"`` / ``"esc"`` / ``"space"`` / ``"f1"`` / ``"a"``），
        由后端映射到平台键码。自定义映射放 ``config``，不要写死在业务脚本里。
    """
    raise NotImplementedError("待实现")


def hotkey(session: Session, keys: list[str]) -> ActionResult[list[str]]:
    """组合键，如 ``["ctrl", "s"]``。"""
    raise NotImplementedError("待实现：pydirectinput 组合键支持有限，需 fallback 到 pyautogui")


# --------------------------------------------------------------------------- #
# 等待
# --------------------------------------------------------------------------- #
def sleep(seconds: float) -> ActionResult[float]:
    """固定等待。

    已实现（确实只有这一件事）。返回 ``success(value=实际等待秒数)``，
    让执行层能把它算进时间预算。
    """
    import time

    if seconds > 0:
        time.sleep(seconds)
    return ActionResult.success(seconds)
