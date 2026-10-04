"""实时画面预览。

## 为什么要单独开一个线程

抓屏本身在 Windows 上只要几毫秒（mss 很快），但 **Android 后端走 adb，
一次截图可能 100~300ms**。放在界面线程里做，界面就会一顿一顿的。
所以抓帧放在工作线程，抓完发个 ``QImage`` 信号回界面。

## 跨线程为什么传 QImage 而不是 QPixmap

``QPixmap`` 依赖图形后端，**只能在界面线程里用**；``QImage`` 是纯内存图像，
跨线程传是安全的（隐式共享，不复制像素）。所以工作线程发 QImage，
界面线程收到之后再转 QPixmap 显示 —— 这是 Qt 的标准做法。

## 抓帧和引擎抢资源

预览用的是和引擎**同一个 Session**（同一个后端），不另开一个 ——
两个 mss 实例同时截屏会互相拖慢，adb 更严重。等引擎接上来之后，
预览要改成"复用引擎那一帧"，而不是自己抓（见 docs/ui.md 待定项 4）。
"""

from __future__ import annotations

import contextlib
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...atomic.frame import Frame
from ...atomic.session import Session

__all__ = ["CaptureWorker", "PreviewPanel"]

#: 抓帧间隔（毫秒）。5 fps 足够看清画面变化，也不会把 CPU 吃掉。
DEFAULT_INTERVAL_MS = 200


class CaptureWorker(QObject):
    """在工作线程里按固定间隔抓帧，并**在这个线程里**管理 Session。

    ## 两条线程规矩

    1. ``QTimer`` **必须在它归属的线程里创建**（Qt 的定时器跟着创建它的线程走），
       所以它是在 :meth:`start` 里建的，不是 ``__init__``；
    2. ``Session`` 也必须在**用的线程**里建、在用完之后 close。
       因为底层 mss 的实例是**线程局部**的 —— 在界面线程 new 出来、
       在工作线程里 capture，是这类项目里最难查的崩溃来源之一。
       所以 :meth:`configure` 这个槽会被排到工作线程里执行，
       Session 的生死都在它里面。
    """

    frameReady = Signal(object, float, tuple, int)
    """``(QImage, 耗时秒, (宽, 高), 帧号)``。"""

    failed = Signal(str)
    sourceReady = Signal(str)
    """Session 就绪，参数是给人看的来源描述。"""

    def __init__(self, interval_ms: int = DEFAULT_INTERVAL_MS) -> None:
        super().__init__()
        self._interval_ms = interval_ms
        self._timer: QTimer | None = None
        self._session: Session | None = None
        self._counter = 0
        self._live = True

    # ------------------------------------------------------------------ #
    # 生命周期（都在工作线程里执行）
    # ------------------------------------------------------------------ #
    @Slot()
    def start(self) -> None:
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setInterval(self._interval_ms)
            self._timer.timeout.connect(self._grab)
        self._timer.start()

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    @Slot(bool)
    def set_live(self, on: bool) -> None:
        self._live = on

    @Slot(int)
    def set_interval(self, interval_ms: int) -> None:
        self._interval_ms = max(50, interval_ms)
        if self._timer is not None:
            self._timer.setInterval(self._interval_ms)

    @Slot(object, str)
    def configure(self, config: object, window_title: str) -> None:
        """换目标窗口：关掉旧 Session，按新配置建一个。

        Session 的建和关都在这里（工作线程），见类 docstring 第 2 条。
        """
        self._close_session()
        if config is None:
            return

        overrides = config
        title = window_title.strip()
        if title:
            # 直接改字段：config 是这次调用专属的对象，不共享给别人
            with contextlib.suppress(AttributeError):
                overrides.screen.window_title = title

        try:
            from ...bootstrap import build_session_from_config

            self._session = build_session_from_config(overrides)
        except Exception as exc:
            self._session = None
            self.failed.emit(f"建立抓屏会话失败: {type(exc).__name__}: {exc}")
            return

        backend = getattr(overrides.screen, "backend", None)
        name = getattr(backend, "value", str(backend))
        self.sourceReady.emit(f"来源: {name} / {title or '未指定窗口'}")

    @Slot()
    def shutdown(self) -> None:
        """线程退出前调：停表 + 关 Session。**必须调**，否则句柄泄漏。"""
        self.stop()
        self._close_session()

    def _close_session(self) -> None:
        session = self._session
        self._session = None
        if session is not None:
            # 关闭失败不值得让界面崩：进程退出时系统会收掉句柄
            with contextlib.suppress(Exception):
                session.close()

    # ------------------------------------------------------------------ #
    @Slot()
    def grab_once(self) -> None:
        """手动抓一张（"抓一张"按钮）。"""
        self._grab()

    @Slot()
    def _grab(self) -> None:
        session = self._session
        if session is None or not self._live:
            return
        started = time.perf_counter()
        try:
            frame = session.capture()
        except Exception as exc:
            self.failed.emit(f"抓屏失败: {type(exc).__name__}: {exc}")
            return
        elapsed = time.perf_counter() - started

        image = to_qimage(frame)
        if image is None:
            self.failed.emit("抓到的帧没法转成图像")
            return

        self._counter += 1
        size = frame.size
        self.frameReady.emit(image, elapsed, size, self._counter)


def to_qimage(frame: Frame) -> QImage | None:
    """``Frame`` 的 BGR 数组 -> ``QImage``。

    用 ``QImage(...).copy()``：``QImage`` 的构造函数**不复制像素**，只引用
    numpy 的缓冲区；而那个缓冲区是临时的，出了作用域就回收 —— 不 copy 的话
    界面拿到的是一块已释放的内存（表现是花屏或崩溃，而且很难复现）。

    通道数决定格式：3 通道是 BGR（``Frame.image`` 的约定），
    4 通道是 BGRA（小端机器上对应 ``Format_ARGB32``）。
    """
    array = frame.image
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        return None
    height, width = array.shape[:2]
    if array.shape[2] == 4:
        fmt = QImage.Format.Format_ARGB32
        stride = width * 4
    else:
        fmt = QImage.Format.Format_BGR888
        stride = width * 3
    return QImage(array.data, width, height, stride, fmt).copy()


class PreviewPanel(QWidget):
    """画面 + 它下面的几个开关。

    自己不抓帧，只发意图信号、显示结果 —— 抓帧在 :class:`CaptureWorker` 里。
    """

    intervalChanged = Signal(int)
    liveChanged = Signal(bool)
    grabRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._canvas = QLabel("还没有画面", self)
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setMinimumSize(480, 270)
        self._canvas.setStyleSheet("background:#101216; border:1px solid #2b303b;")
        self._last_image: QImage | None = None

        self._live = QCheckBox("自动刷新", self)
        self._live.setChecked(True)
        self._live.toggled.connect(self.liveChanged.emit)

        self._rate = QComboBox(self)
        for label, value in (("10 fps", 100), ("5 fps", 200), ("2 fps", 500), ("1 fps", 1000)):
            self._rate.addItem(label, value)
        self._rate.setCurrentIndex(1)
        self._rate.currentIndexChanged.connect(
            lambda: self.intervalChanged.emit(int(self._rate.currentData()))
        )

        self._grab_once = QPushButton("抓一张", self)
        self._grab_once.clicked.connect(self.grabRequested.emit)

        self._meta = QLabel("—", self)
        self._meta.setStyleSheet("color:#7f8c8d;")

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self._live)
        bar.addWidget(QLabel("频率", self))
        bar.addWidget(self._rate)
        bar.addWidget(self._grab_once)
        bar.addStretch(1)
        bar.addWidget(self._meta)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._canvas, 1)
        layout.addLayout(bar)

    # ------------------------------------------------------------------ #
    @property
    def interval_ms(self) -> int:
        return int(self._rate.currentData())

    @property
    def live(self) -> bool:
        return self._live.isChecked()

    def show_frame(self, image: QImage, elapsed: float, size: tuple[int, int], seq: int) -> None:
        """槽：显示一帧（已经在界面线程）。

        按控件大小等比缩放，**不放大** —— 放大只会让人误判清晰度。
        """
        self._last_image = image
        self._render()
        self._meta.setText(
            f"{size[0]}x{size[1]}   抓帧 {elapsed * 1000:.1f}ms   第 {seq} 张"
        )

    def show_error(self, message: str) -> None:
        self._meta.setText(f"⚠ {message}")

    def set_source_label(self, text: str) -> None:
        self._meta.setText(text)

    def set_live_enabled(self, on: bool) -> None:
        """置灰面板上的几个开关（运行中会用到）。"""
        self._live.setEnabled(on)
        self._rate.setEnabled(on and self._live.isChecked())
        self._grab_once.setEnabled(on)

    # ------------------------------------------------------------------ #
    def _render(self) -> None:
        image = self._last_image
        if image is None:
            return
        target = self._canvas.size()
        scaled = image.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._canvas.setPixmap(QPixmap.fromImage(scaled))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()
