"""应用装配与启动。

## 无头自检

``--snapshot`` 会**不开窗口**地渲染一张界面截图就退出，用在两个地方：

* 没有可视环境时验证界面能不能正常构造出来（CI / 这台机器上跑命令时）；
* 给文档配图。

需要 ``QT_QPA_PLATFORM=offscreen``。注意它照样会去枚举真实窗口、抓真实屏幕 ——
"离屏"指的是 Qt 不出可视窗口，不是 mss 抓不到东西。
"""

from __future__ import annotations

import sys
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from ..utils.logging import get_logger
from .theme import apply_dark_theme
from .window import MainWindow

__all__ = ["DEFAULT_SIZE", "main"]

log = get_logger("ui.app")

#: 默认窗口尺寸。够放下"画面 + 信息 + 日志"三块而不至于占满屏。
DEFAULT_SIZE = (1280, 880)

#: 截图前等多久（秒）—— 让工作线程有机会送几帧过来
SNAPSHOT_SETTLE = 1.6


def main(
    *,
    script_key: str = "",
    snapshot: str = "",
    argv: list[str] | None = None,
) -> int:
    """构造界面。``snapshot`` 非空时渲染截图并退出。"""
    # ``QApplication.instance()`` 的静态类型是 ``QCoreApplication | None``，
    # 但它就是本进程那个 QApplication（Qt 只允许一个）。这里断言一下，
    # 好让后面的 ``setApplicationDisplayName`` / ``apply_dark_theme(app)`` 类型成立。
    existing = QApplication.instance()
    app = (
        existing
        if isinstance(existing, QApplication)
        else QApplication(argv if argv is not None else sys.argv[:1])
    )
    QCoreApplication.setApplicationName("gamebot")
    QCoreApplication.setApplicationVersion("0.1.0")
    app.setApplicationDisplayName("gamebot 控制台")
    apply_dark_theme(app)

    window = MainWindow(initial_script=script_key)
    window.resize(*DEFAULT_SIZE)

    if snapshot:
        return _save_snapshot(app, window, snapshot)

    window.show()
    return app.exec()


def _save_snapshot(app: QApplication, window: MainWindow, path: str) -> int:
    """渲染一张界面截图。

    不是简单地 ``grab()`` 一下就完事：界面里有一部分内容是**异步**来的
    （抓帧在工作线程、日志记录在事件队列里），所以要一边
    ``processEvents`` 一边真等一下，否则截出来的是个空壳。
    """
    window.show()
    deadline = time.monotonic() + SNAPSHOT_SETTLE
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    # 收尾：把还在队列里的信号处理掉
    for _ in range(5):
        app.processEvents()

    pixmap = window.grab()
    ok = pixmap.save(path)
    if ok:
        log.info("界面截图已保存: %s (%dx%d)", path, pixmap.width(), pixmap.height())
    else:
        log.error("界面截图保存失败: %s", path)

    window.close()
    for _ in range(3):
        app.processEvents()
    return 0 if ok else 1
