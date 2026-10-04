"""后端协议 —— "操作系统那一侧"的能力边界。

拆成三个正交协议，是为了让 Windows / Android 共用同一套上层：

* ``ScreenBackend`` 只管把像素拿回来；
* ``InputBackend``  只管把键鼠 / 触摸事件发出去；
* ``WindowBackend`` 只管窗口发现与定位（Android 侧可用空实现）。

坐标系纪律：**后端一律收发源分辨率坐标**，不感知"逻辑分辨率"。
逻辑 <-> 源的换算统一在 ``CoordinateMapper`` 里做一次，别散落到后端。
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ...types import Point, Region

if TYPE_CHECKING:
    import numpy as np

    ImageArray = np.ndarray
else:  # pragma: no cover
    ImageArray = Any

__all__ = [
    "BackendBundle",
    "InputBackend",
    "ScreenBackend",
    "WindowBackend",
    "WindowInfo",
]


@runtime_checkable
class ScreenBackend(Protocol):
    """截图能力。"""

    @property
    def name(self) -> str:
        """后端标识，用于日志：``"mss"`` / ``"adb"``。"""
        ...

    def screen_size(self) -> tuple[int, int]:
        """源分辨率 ``(width, height)``。"""
        ...

    def grab(self, region: Region | None = None) -> ImageArray:
        """抓一帧。

        :param region: 源分辨率下的区域；None 表示全屏。
        :return: ``(H, W, 3)`` 的 BGR 数组。**必须是副本**，不能是复用缓冲区。
        """
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class InputBackend(Protocol):
    """输入能力。坐标为源分辨率。"""

    @property
    def name(self) -> str:
        ...

    def move_to(self, point: Point, duration: float = 0.2) -> None:
        ...

    def click(
        self,
        point: Point,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
    ) -> None:
        ...

    def drag(
        self,
        start: Point,
        end: Point,
        *,
        duration: float = 0.5,
        button: str = "left",
    ) -> None:
        ...

    def scroll(self, clicks: int, point: Point | None = None) -> None:
        ...

    def type_text(self, text: str, *, interval: float = 0.05) -> None:
        ...

    def press_key(self, key: str, *, presses: int = 1, interval: float = 0.1) -> None:
        ...

    def hotkey(self, keys: list[str]) -> None:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class WindowBackend(Protocol):
    """窗口发现 / 定位能力（仅桌面平台有意义）。"""

    def list_windows(self, keyword: str = "") -> list[WindowInfo]:
        """列出可见窗口，``keyword`` 非空时按标题过滤（不区分大小写）。"""
        ...

    def find_window(self, title_pattern: str) -> WindowInfo | None:
        """按标题关键字找窗口，找不到返回 None。"""
        ...


class WindowInfo:
    """窗口描述。用普通类而非 dataclass，避免和后端实现耦合。"""

    __slots__ = ("handle", "region", "title")

    def __init__(self, handle: Any, title: str, region: Region) -> None:
        self.handle = handle
        self.title = title
        self.region = region

    def __repr__(self) -> str:
        return f"WindowInfo(handle={self.handle!r}, title={self.title!r}, region={self.region!r})"


class BackendBundle:
    """把一套互相匹配的后端打包，方便装配与替换。

    ``window`` 可以为 None（Android 侧没有窗口概念）。
    """

    __slots__ = ("input", "screen", "window")

    def __init__(
        self,
        screen: ScreenBackend,
        input: InputBackend,
        window: WindowBackend | None = None,
    ) -> None:
        self.screen = screen
        self.input = input
        self.window = window

    def close(self) -> None:
        # 关闭失败不该影响主流程：后端可能已经自己断开了。
        for backend in (self.screen, self.input):
            with suppress(Exception):
                backend.close()

    def __repr__(self) -> str:
        return f"BackendBundle(screen={self.screen.name!r}, input={self.input.name!r})"
