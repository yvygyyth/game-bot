"""logging → Qt 信号的桥。

## 为什么不能直接往日志框里写

引擎跑在**工作线程**里。Qt 的铁律是"只有界面线程能碰控件"，
从别的线程改控件不会立刻报错，而是随机崩溃 —— 极难查。
所以工作线程里的日志必须**发信号**（队列连接会自动把它排到界面线程），
由界面的槽函数去写控件。

## 三件必须做对的事

1. **信号参数用 ``object``**：直接传 ``logging.LogRecord``，Qt 不需要注册类型；
2. **保留环形缓冲**：界面可能比引擎晚开，切换级别过滤时也要重画所有行，
   这两种情况都要"刚才那些记录还在"；
3. **关窗时必须 :meth:`detach`**：``CallbackHandler`` 的回调闭包持有界面对象，
   不摘掉的话窗口关了对象也不会释放（表现是"关了窗后台还有东西在跑"）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from ..utils.logging import (
    CallbackHandler,
    RingBufferHandler,
    attach_handlers,
    detach_handlers,
)

__all__ = ["LogBridge"]

_LOGGER_NAME = "gamebot"


class LogBridge(QObject):
    """把 ``gamebot`` 命名空间下的日志记录送到界面。

    :param maxlen: 环形缓冲保留多少条。
    """

    #: 收到一条日志。跨线程时是队列连接，槽函数一定跑在界面线程。
    recordArrived = Signal(object)

    def __init__(self, maxlen: int = 2000, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._logger = logging.getLogger(_LOGGER_NAME)
        self._buffer = RingBufferHandler(maxlen)
        self._callback = CallbackHandler(self._on_record)
        self._attached: list[logging.Handler] = []

    # ------------------------------------------------------------------ #
    def attach(self) -> None:
        """挂上 handler。幂等。"""
        if self._attached:
            return
        # 让 handler 去做级别过滤，所以这里把 logger 放开到 DEBUG ——
        # 和 setup_logging 的做法一致。不这么做的话，界面挂得比
        # setup_logging 早时，DEBUG 记录会被 root logger 的默认 WARNING 挡掉。
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        self._attached = attach_handlers(self._logger, [self._buffer, self._callback])

    def detach(self) -> None:
        """摘掉 handler。**关窗时必须调**，否则界面对象不会释放。"""
        detach_handlers(self._logger, self._attached)
        self._attached = []

    @property
    def attached(self) -> bool:
        return bool(self._attached)

    # ------------------------------------------------------------------ #
    def snapshot(self, *, level: int = logging.NOTSET) -> list[logging.LogRecord]:
        """缓冲里的记录（时间正序）。界面开起来时先拿这个补画一遍。"""
        return self._buffer.snapshot(level=level)

    def clear(self) -> None:
        self._buffer.clear()

    def _on_record(self, record: logging.LogRecord) -> None:
        # 这一行在**产生日志的线程**里执行（可能是引擎的工作线程）。
        # emit 本身是线程安全的；Qt 会把槽调用排进界面线程的事件队列。
        self.recordArrived.emit(record)
