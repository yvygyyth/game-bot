"""计时工具。

原子方法都要往 ``ActionResult.elapsed`` 里填耗时，所以统一走这里，
避免每个方法各写一遍 ``time.perf_counter()`` 差值。
"""

from __future__ import annotations

import time
from collections.abc import Callable

__all__ = ["Stopwatch", "humanize", "now", "sleep"]


def now() -> float:
    """单调时钟当前值（秒）。用于计算时间差，不要用于显示绝对时间。"""
    return time.perf_counter()


def sleep(seconds: float) -> None:
    """休眠。``seconds <= 0`` 时立即返回。"""
    if seconds > 0:
        time.sleep(seconds)


def humanize(seconds: float) -> str:
    """把秒数变成人看的样子：``12.3s`` / ``2m03s`` / ``1h02m03s``。"""
    if seconds < 0:
        return "-" + humanize(-seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    return f"{minutes}m{sec:02d}s"


class Stopwatch:
    """可复用秒表。

    典型用法（原子方法内部）::

        sw = Stopwatch()
        ...干活...
        return ActionResult.success(value=pt, elapsed=sw.elapsed)
    """

    __slots__ = ("_clock", "_last_lap", "_start")

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._start = clock()
        self._last_lap = self._start

    def reset(self) -> Stopwatch:
        self._start = self._clock()
        self._last_lap = self._start
        return self

    @property
    def elapsed(self) -> float:
        """从起点到现在（秒）。"""
        return self._clock() - self._start

    def lap(self) -> float:
        """距上次 lap（或起点）的间隔（秒），并重置 lap 计时。"""
        current = self._clock()
        delta = current - self._last_lap
        self._last_lap = current
        return delta

    def __enter__(self) -> Stopwatch:
        return self.reset()

    def __exit__(self, *exc_info: object) -> None:
        return None
