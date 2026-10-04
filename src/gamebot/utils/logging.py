"""日志配置。

约定：

* 所有 logger 都挂在 ``gamebot`` 命名空间下，外部库的噪音不会被我们的配置带走；
* 控制台输出带颜色级别（可选），文件输出不带颜色；
* 流程层 / 执行层不打 print，一律走 logger，方便以后接 GUI 或落盘分析。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

__all__ = ["DEFAULT_DATEFMT", "DEFAULT_FORMAT", "get_logger", "setup_logging"]

DEFAULT_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-24s | %(message)s"
DEFAULT_DATEFMT = "%H:%M:%S"

_ROOT = "gamebot"


def setup_logging(
    level: str | int = "INFO",
    *,
    log_file: Path | str | None = None,
    fmt: str = DEFAULT_FORMAT,
    datefmt: str = DEFAULT_DATEFMT,
    file_level: str | int | None = None,
) -> logging.Logger:
    """配置 ``gamebot`` 根 logger，返回它。

    :param level: 控制台级别，可以是 ``"DEBUG"`` 或 ``logging.DEBUG``。
    :param log_file: 非 None 时额外写文件（目录会自动创建）。
    :param file_level: 文件级别，默认与 ``level`` 相同。
    """
    logger = logging.getLogger(_ROOT)
    logger.setLevel(logging.DEBUG)  # 交给 handler 过滤
    logger.propagate = False

    for handler in list(logger.handlers):  # 幂等：重复调用不叠加 handler
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(_as_level(level))
    console.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(console)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(_as_level(file_level if file_level is not None else level))
        file_handler.setFormatter(logging.Formatter(fmt, datefmt))
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """取一个 ``gamebot.*`` 下的 logger。``get_logger("flow.engine")``。"""
    if name == _ROOT or name.startswith(_ROOT + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT}.{name}")


def _as_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(level.upper())
    return resolved if isinstance(resolved, int) else logging.INFO
