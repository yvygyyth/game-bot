"""L1 截图层 —— Session。

职责边界（**必须守住，否则分层就烂了**）：

* Session 只负责：截图、坐标系换算、持有输入后端、生命周期管理。
* Session **不做任何查询**：不找图、不找字、不判断状态、不比较相似度。
  所有查询都属于 L2 Frame。

为什么把输入后端也挂在 Session 上：设计文档里 L5 动作层的 13 个方法都只接收
``session`` 一个上下文对象。让 Session 成为"当前这台机器/这个游戏"的门面，
动作层就不需要知道后端是谁。

坐标系统一说明：

* **源分辨率**：截出来的真实像素。Region / Point 默认都是这个坐标系。
* **逻辑分辨率**：写脚本时用的坐标系（比如按 1920x1080 设计稿写死坐标）。
  当窗口被缩放、或模拟器分辨率与设计稿不同时，靠 ``CoordinateMapper`` 换算。
* 屏幕/桌面绝对坐标：windows 后端下等于源分辨率；窗口没在 (0,0) 时由后端内部处理。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..exceptions import BackendUnavailable, Cancelled
from ..types import ActionResult, Point, Region
from ..utils.logging import get_logger
from .backends.base import BackendBundle, InputBackend, ScreenBackend, WindowBackend
from .vision import Matcher, TextReader, UnavailableTextReader

if TYPE_CHECKING:
    from .frame import Frame

__all__ = ["BaseSession", "CoordinateMapper", "Session"]

log = get_logger("atomic.session")

# 懒建取消事件时的互斥，保证多线程首次访问只建一个
_CANCEL_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# 坐标换算
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CoordinateMapper:
    """逻辑分辨率 <-> 源分辨率 的线性映射。

    常见来源：游戏按 1920x1080 设计，实际窗口只有 1280x720。
    或者 Android 模拟器缩放显示。写脚本时按逻辑坐标写，运行期换算成源坐标。

    ``source == logic`` 时退化为恒等映射（最常见的情况）。
    """

    source_width: int
    source_height: int
    logic_width: int
    logic_height: int

    @property
    def scale_x(self) -> float:
        return self.source_width / self.logic_width if self.logic_width else 1.0

    @property
    def scale_y(self) -> float:
        return self.source_height / self.logic_height if self.logic_height else 1.0

    @property
    def is_identity(self) -> bool:
        return self.scale_x == 1.0 and self.scale_y == 1.0

    def to_source(self, point: Point) -> Point:
        """逻辑点 -> 源点。"""
        return Point(round(point.x * self.scale_x), round(point.y * self.scale_y))

    def to_logic(self, point: Point) -> Point:
        """源点 -> 逻辑点。"""
        return Point(round(point.x / self.scale_x), round(point.y / self.scale_y))

    def region_to_source(self, region: Region) -> Region:
        """逻辑区域 -> 源区域。"""
        top_left = self.to_source(Point(region.x, region.y))
        bottom_right = self.to_source(Point(region.right, region.bottom))
        return Region.from_corners(
            top_left.x, top_left.y, bottom_right.x, bottom_right.y
        )

    def region_to_logic(self, region: Region) -> Region:
        """源区域 -> 逻辑区域。"""
        top_left = self.to_logic(Point(region.x, region.y))
        bottom_right = self.to_logic(Point(region.right, region.bottom))
        return Region.from_corners(
            top_left.x, top_left.y, bottom_right.x, bottom_right.y
        )

    @classmethod
    def identity(cls, width: int, height: int) -> CoordinateMapper:
        return cls(width, height, width, height)

    @classmethod
    def detect(
        cls,
        source_size: tuple[int, int],
        logic_size: tuple[int, int] | None,
    ) -> CoordinateMapper:
        """``logic_size`` 为空时退化为恒等映射。"""
        if not logic_size:
            return cls.identity(*source_size)
        return cls(source_size[0], source_size[1], logic_size[0], logic_size[1])


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
class Session(ABC):
    """L1 截图层契约。

    只有 3 个截图方法（``capture`` / ``capture_region`` / ``get_screen_size``），
    外加坐标系换算和输入通道 —— 这就是 L5 动作层所需要的全部。

    另外提供**中止能力**（``request_stop`` / ``raise_if_stopped`` / ``sleep``）。
    为什么挂在 Session 上而不是给每个方法加一个 ``signal`` 参数：
    Session 是原子层**唯一**已经拿到手的上下文对象（等价于 Go 的 ``ctx``、
    .NET 的 ``CancellationToken``、前端的 ``AbortSignal``），
    所以"取消"不需要改任何方法签名，也不需要调用方记得往下传。

    层级影响：L4 组合子只调 ``session.raise_if_stopped()`` /
    ``session.sleep()``，**完全不需要知道 Cancelled 这个异常类型存在**。
    """

    # -- 截图（设计文档 L1 的 1~3 号方法）-------------------------------------
    @abstractmethod
    def capture(self) -> Frame:
        """截取整个屏幕（或当前窗口客户区），返回 Frame 快照。"""
        raise NotImplementedError

    @abstractmethod
    def capture_region(self, region: Region) -> Frame:
        """截取指定区域，返回 Frame。

        返回的 Frame **坐标系仍是源分辨率** —— Frame 记住自己的 origin，
        因此 ``frame.find_image(...)`` 返回的 Point 可以直接拿去点击。
        """
        raise NotImplementedError

    @abstractmethod
    def get_screen_size(self) -> ActionResult[tuple[int, int]]:
        """返回 ``ActionResult.success(value=(w, h))``。

        失败（窗口关了、adb 断了）时返回 ``error`` 而不是抛异常。
        """
        raise NotImplementedError

    # -- 坐标系 ---------------------------------------------------------------
    @property
    @abstractmethod
    def mapper(self) -> CoordinateMapper:
        """当前逻辑 <-> 源 的换算器。"""
        raise NotImplementedError

    def to_screen(self, point: Point) -> Point:
        """逻辑点 -> 源点。动作层发按键/点击前调它。"""
        return self.mapper.to_source(point)

    def to_logic(self, point: Point) -> Point:
        """源点 -> 逻辑点。日志和配置回写时用。"""
        return self.mapper.to_logic(point)

    def region_to_screen(self, region: Region) -> Region:
        return self.mapper.region_to_source(region)

    # -- 输入通道（供 L5 使用）------------------------------------------------
    @property
    @abstractmethod
    def input(self) -> InputBackend:
        """输入后端。动作层通过它发事件。"""
        raise NotImplementedError

    # -- 中止（可取消性）------------------------------------------------------
    def _cancel_event(self) -> threading.Event:
        """懒建、每实例一个的取消事件。

        懒建是为了兼容自己写 ``__init__`` 而不调 ``super().__init__()`` 的子类；
        走 ``self.__dict__`` 是为了兼容定义了 ``__slots__`` 的子类。
        """
        event = self.__dict__.get("_stop_event")
        if event is None:
            with _CANCEL_LOCK:
                event = self.__dict__.get("_stop_event")
                if event is None:
                    event = threading.Event()
                    self.__dict__["_stop_event"] = event
        return event

    @property
    def stop_requested(self) -> bool:
        """是否已请求中止。可以从别的线程读（UI 的停止按钮）。"""
        return self._cancel_event().is_set()

    @property
    def stop_reason(self) -> str:
        """中止原因。没请求过时是空串。"""
        return str(self.__dict__.get("_stop_reason", ""))

    def request_stop(self, reason: str = "") -> None:
        """请求中止。**幂等，可从任意线程调用。**

        只有第一次调用生效，之后的原因会被忽略 —— **第一个原因才是根因**，
        后面的（看门狗超时、超预算）都是它的后果。报告里写"用户点了停止"
        比写"超过总时长预算"有用得多。

        ⚠️ 只设标志，**不会**关掉 session —— 那一刻可能正有一帧 ``capture()``
        在飞。正确收尾顺序是::

            session.request_stop("用户点了停止")   # 任意线程
            工作线程自己退出（Cancelled 穿透到引擎）
            session.close()                       # 最后才关

        用 ``threading.Event`` 而不是 bool：它跨线程安全，并且能**立刻唤醒**
        正在 ``sleep`` 的等待方。
        """
        event = self._cancel_event()
        # 加锁保证"检查 + 写入 + set"是一个原子操作，多个线程同时请求时只有一个赢
        with _CANCEL_LOCK:
            if event.is_set():
                return
            self.__dict__["_stop_reason"] = reason or "已请求中止"
            event.set()

    def clear_stop(self) -> None:
        """清空中止标志。新一轮运行开始前调用。"""
        self.__dict__["_stop_reason"] = ""
        self._cancel_event().clear()

    def raise_if_stopped(self) -> None:
        """已请求中止就抛 ``Cancelled``。

        原子层的每个阻塞循环都在检查点调用它 —— 检查得越密，响应越快。
        典型检查点：循环开头、每次抓帧之前。

        :raises Cancelled: 已请求中止。
        """
        if self.stop_requested:
            raise Cancelled(self.stop_reason or "已请求中止")

    def sleep(self, seconds: float) -> None:
        """**可被中止立刻唤醒**的等待 —— ``time.sleep`` 的可取消版本。

        ``Event.wait()`` 既睡眠又能被 ``request_stop()`` 立即唤醒，
        比"切成 50ms 小片轮询标志"既精确又不空转。

        :raises Cancelled: 等待期间被中止（醒来立刻抛，不会等满）。
        """
        if seconds <= 0:
            # 即使不睡，也走一次检查：调用方把它当检查点用
            self.raise_if_stopped()
            return
        if self._cancel_event().wait(seconds):
            raise Cancelled(self.stop_reason or "已请求中止")

    # -- 生命周期 -------------------------------------------------------------
    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class BaseSession(Session):
    """把 ``ScreenBackend`` / ``InputBackend`` / ``Matcher`` / ``TextReader``
    组装成一个 Session 的通用实现。

    平台后端（windows / android / fake）只需提供 ``BackendBundle`` 和尺寸，
    截图编排、坐标换算、Frame 构造这些活都在这里做一次。
    """

    def __init__(
        self,
        backends: BackendBundle,
        *,
        matcher: Matcher,
        reader: TextReader | None = None,
        logic_size: tuple[int, int] | None = None,
        default_confidence: float = 0.9,
    ) -> None:
        self._backends = backends
        self._matcher = matcher
        self._reader: TextReader = reader or UnavailableTextReader()
        self._default_confidence = default_confidence
        self._closed = False
        # 提前建好取消事件，省掉 _cancel_event() 里的锁路径
        self.__dict__["_stop_event"] = threading.Event()
        self._mapper = CoordinateMapper.detect(self._backends.screen.screen_size(), logic_size)
        log.debug("Session 就绪: %s, mapper=%s", self._backends, self._mapper)

    # -- 内部 -----------------------------------------------------------------
    @property
    def screen_backend(self) -> ScreenBackend:
        return self._backends.screen

    @property
    def window_backend(self) -> WindowBackend | None:
        return self._backends.window

    @property
    def matcher(self) -> Matcher:
        return self._matcher

    @property
    def reader(self) -> TextReader:
        return self._reader

    @property
    def default_confidence(self) -> float:
        return self._default_confidence

    def _make_frame(self, image: Any, origin: Region) -> Frame:
        from .frame import Frame

        return Frame(image, origin, session=self)

    # -- Session 契约 ---------------------------------------------------------
    @property
    def mapper(self) -> CoordinateMapper:
        return self._mapper

    @property
    def input(self) -> InputBackend:
        return self._backends.input

    def get_screen_size(self) -> ActionResult[tuple[int, int]]:
        try:
            return ActionResult.success(self._backends.screen.screen_size())
        except Exception as exc:
            return ActionResult.error(f"获取屏幕尺寸失败: {exc}", exc=exc)

    def capture(self) -> Frame:
        width, height = self._backends.screen.screen_size()
        return self._make_frame(self._backends.screen.grab(None), Region.full(width, height))

    def capture_region(self, region: Region) -> Frame:
        # region 是源分辨率坐标，后端原样接收
        return self._make_frame(self._backends.screen.grab(region), region)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._backends.close()
        log.debug("Session 已关闭")


def build_session(
    backend: str,
    *,
    matcher: Matcher,
    reader: TextReader | None = None,
    logic_size: tuple[int, int] | None = None,
    **kwargs: Any,
) -> Session:
    """按名字装配 Session。``backend`` 取 ``windows`` / ``android`` / ``fake``。

    Windows 与 Android 的差异被收敛到 ``BackendBundle`` 一处，
    上层（状态层 / 流程层 / 执行层）完全无感。
    """
    name = backend.lower()
    if name in ("windows", "win", "desktop"):
        from .backends.windows import build_windows_backends

        bundle = build_windows_backends(**kwargs)
    elif name in ("android", "adb"):
        from .backends.android import build_android_backends

        bundle = build_android_backends(**kwargs)
    elif name in ("fake", "test", "mock"):
        from .backends.fake import build_fake_backends

        bundle = build_fake_backends(**kwargs)
    else:
        raise BackendUnavailable(f"未知后端: {backend!r}（可选 windows / android / fake）")

    return BaseSession(
        bundle,
        matcher=matcher,
        reader=reader,
        logic_size=logic_size,
    )
