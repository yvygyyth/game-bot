"""日志配置。

约定：

* 所有 logger 都挂在 ``gamebot`` 命名空间下，外部库的噪音不会被我们的配置带走；
* 控制台输出带颜色级别（可选），文件输出不带颜色；
* 流程层 / 执行层不打 print，一律走 logger，方便接 GUI 或落盘分析。

## 界面要日志怎么办

界面不能去解析日志文本（措辞随时会改），也来不及"从今天早上开始"补看，
所以本模块额外提供两个 handler：

* :class:`RingBufferHandler` —— 把最近 N 条记录留在内存里。界面哪怕启动得晚，
  也能把"刚才发生了什么"补出来；
* :class:`CallbackHandler` —— 每条记录回调一次。界面在这里发一个 Qt 信号
  （信号槽的队列连接会把回调切回界面线程）。

两个都**不是** ``setup_logging`` 管的，所以它重复调用时不会把它们冲掉 ——
见 :func:`setup_logging` 里 ``_gamebot_managed`` 的用法。
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path

__all__ = [
    "DEFAULT_DATEFMT",
    "DEFAULT_FORMAT",
    "CallbackHandler",
    "RingBufferHandler",
    "get_logger",
    "setup_logging",
]

DEFAULT_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-24s | %(message)s"
DEFAULT_DATEFMT = "%H:%M:%S"

_ROOT = "gamebot"

#: 打在我们自己创建的 handler 上的标记 —— 重配时只清掉自己人
_MANAGED = "_gamebot_managed"


def setup_logging(
    level: str | int = "INFO",
    *,
    log_file: Path | str | None = None,
    fmt: str = DEFAULT_FORMAT,
    datefmt: str = DEFAULT_DATEFMT,
    file_level: str | int | None = None,
) -> logging.Logger:
    """配置 ``gamebot`` 根 logger，返回它。

    **幂等**：重复调用不会叠加 handler。但它只清掉自己创建的 handler
    （带 ``_gamebot_managed`` 标记的那些），外部挂上去的（比如界面的日志桥）
    会保留 —— 否则界面先挂 handler、后装配日志，桥就被冲掉了。

    :param level: 控制台级别，可以是 ``"DEBUG"`` 或 ``logging.DEBUG``。
    :param log_file: 非 None 时额外写文件（目录会自动创建）。
    :param file_level: 文件级别，默认与 ``level`` 相同。
    """
    logger = logging.getLogger(_ROOT)
    logger.setLevel(logging.DEBUG)  # 交给 handler 过滤
    logger.propagate = False

    for handler in list(logger.handlers):
        if getattr(handler, _MANAGED, False):
            logger.removeHandler(handler)
            handler.close()

    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(_as_level(level))
    console.setFormatter(logging.Formatter(fmt, datefmt))
    setattr(console, _MANAGED, True)
    logger.addHandler(console)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(_as_level(file_level if file_level is not None else level))
        file_handler.setFormatter(logging.Formatter(fmt, datefmt))
        setattr(file_handler, _MANAGED, True)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """取一个 ``gamebot.*`` 下的 logger。``get_logger("flow.engine")``。"""
    if name == _ROOT or name.startswith(_ROOT + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT}.{name}")


# --------------------------------------------------------------------------- #
# 给界面用的两个 handler
# --------------------------------------------------------------------------- #
class RingBufferHandler(logging.Handler):
    """把最近 ``maxlen`` 条记录留在内存里。

    为什么要它：界面可能比引擎晚启动（先跑着脚本，再打开界面看看），
    也可能只是想重新渲染一遍（切换级别过滤时要重画所有行）。
    这两种情况都需要"刚才那些记录还在"。

    ``deque`` 的 ``append`` 是线程安全的，所以引擎线程写、界面线程读没问题。
    """

    def __init__(self, maxlen: int = 2000, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.records: deque[logging.LogRecord] = deque(maxlen=max(1, maxlen))

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def snapshot(self, *, level: int = logging.NOTSET) -> list[logging.LogRecord]:
        """当前缓冲里的记录（按时间正序）。``level`` 可以再过滤一道。"""
        return [r for r in list(self.records) if r.levelno >= level]

    def clear(self) -> None:
        self.records.clear()


class CallbackHandler(logging.Handler):
    """每条记录调一次 ``callback(record)``。

    界面用它把记录变成 Qt 信号。**回调必须自己保证线程安全** ——
    它是在"产生日志的那个线程"里被调用的（可能是引擎的工作线程）。

    :param swallow: True 时回调抛异常只走 :meth:`handleError`，
        不让异常窜回 logging 内部。默认 True：界面桥出问题不该把引擎带崩。
    """

    def __init__(
        self,
        callback: Callable[[logging.LogRecord], None],
        level: int = logging.NOTSET,
        *,
        swallow: bool = True,
    ) -> None:
        super().__init__(level)
        self.callback = callback
        self.swallow = swallow

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.callback(record)
        except Exception:
            if not self.swallow:
                raise
            self.handleError(record)


def attach_handlers(
    logger: logging.Logger,
    handlers: Iterable[logging.Handler],
) -> list[logging.Handler]:
    """给 logger 挂一批 handler（幂等：已经在的不重复挂）。返回实际挂上的。"""
    added: list[logging.Handler] = []
    for handler in handlers:
        if handler in logger.handlers:
            continue
        logger.addHandler(handler)
        added.append(handler)
    return added


def detach_handlers(
    logger: logging.Logger,
    handlers: Iterable[logging.Handler],
) -> None:
    """摘掉一批 handler 并 ``close()``。

    **必须调**：``CallbackHandler`` 的回调通常闭包持有一个界面对象，
    不摘掉的话窗口关了对象也不会释放（表现是"关了窗还有东西在跑"）。
    """
    for handler in handlers:
        if handler in logger.handlers:
            logger.removeHandler(handler)
        handler.close()


def _as_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(level.upper())
    return resolved if isinstance(resolved, int) else logging.INFO
