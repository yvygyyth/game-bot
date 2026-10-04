"""假后端 —— 内存实现，给单元测试和"流程空跑"用。

它已经**完整实现**（不依赖任何第三方库之外的 numpy），因为：

* 测试状态层 / 流程层 / 执行层时，不该被真实截图和真实点击拖累；
* 可以在没有游戏、没有 Windows、没有 adb 的机器上跑通整条链路；
* ``FakeInputBackend.events`` 记录所有输入调用，方便断言"到底点没点、点哪儿"。

典型用法::

    bundle = build_fake_backends(size=(1920, 1080))
    session = BaseSession(bundle, matcher=MyFakeMatcher())
    session.capture()                     # 返回全黑帧
    session.input.click(Point(10, 20))
    assert bundle.input.events[0] == ("click", Point(10, 20))
"""

from __future__ import annotations

from typing import Any

from ...types import Point, Region
from .base import BackendBundle, WindowInfo

__all__ = [
    "FakeInputBackend",
    "FakeScreenBackend",
    "FakeWindowBackend",
    "build_fake_backends",
]


class FakeScreenBackend:
    """返回固定图像的截图后端。

    :param image: ``(H, W, 3)`` 的 BGR 数组；None 时生成全黑图。
    :param size: ``image`` 为 None 时用来生成黑图的尺寸。
    :param frames: 预置帧序列。给了的话每次 ``grab`` 依次取出（播完停在最后一帧），
                   用来测"跨帧等待"这类逻辑。
    """

    name = "fake"

    def __init__(
        self,
        image: Any = None,
        size: tuple[int, int] = (1280, 720),
        frames: list[Any] | None = None,
    ) -> None:
        self._frames = list(frames or [])
        self._index = 0
        self._explicit = image
        self._size = size
        self.grab_count = 0

    def _blank(self) -> Any:
        import numpy as np

        height, width = self._size[1], self._size[0]
        return np.zeros((height, width, 3), dtype=np.uint8)

    def screen_size(self) -> tuple[int, int]:
        if self._explicit is not None:
            height, width = self._explicit.shape[:2]
            return (width, height)
        return self._size

    def grab(self, region: Region | None = None) -> Any:
        self.grab_count += 1
        if self._frames:
            image = self._frames[min(self._index, len(self._frames) - 1)]
            self._index += 1
        elif self._explicit is not None:
            image = self._explicit
        else:
            image = self._blank()
        if region is None:
            return image.copy()
        return image[region.y : region.bottom, region.x : region.right].copy()

    def close(self) -> None:
        return None


class FakeInputBackend:
    """记录所有输入调用，不做任何真实操作。"""

    name = "fake-input"

    def __init__(self, size: tuple[int, int] = (1280, 720)) -> None:
        self.events: list[tuple[str, Any]] = []
        self._size = size
        self._pos = Point(0, 0)

    def move_to(self, point: Point, duration: float = 0.2) -> None:
        self._pos = point
        self.events.append(("move_to", point))

    def click(
        self,
        point: Point,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
    ) -> None:
        self._pos = point
        self.events.append(("click", (point, button, clicks)))

    def drag(
        self,
        start: Point,
        end: Point,
        *,
        duration: float = 0.5,
        button: str = "left",
    ) -> None:
        self._pos = end
        self.events.append(("drag", (start, end, duration)))

    def scroll(self, clicks: int, point: Point | None = None) -> None:
        self.events.append(("scroll", (clicks, point)))

    def type_text(self, text: str, *, interval: float = 0.05) -> None:
        self.events.append(("type_text", text))

    def press_key(self, key: str, *, presses: int = 1, interval: float = 0.1) -> None:
        self.events.append(("press_key", (key, presses)))

    def hotkey(self, keys: list[str]) -> None:
        self.events.append(("hotkey", list(keys)))

    def close(self) -> None:
        return None

    @property
    def position(self) -> Point:
        """当前虚拟鼠标位置，方便断言拖拽起点。"""
        return self._pos

    def clear(self) -> None:
        self.events.clear()


class FakeWindowBackend:
    """内存窗口表。"""

    def __init__(self, windows: list[WindowInfo] | None = None) -> None:
        self._windows = list(windows or [])

    def list_windows(self, keyword: str = "") -> list[WindowInfo]:
        if not keyword:
            return list(self._windows)
        lowered = keyword.lower()
        return [w for w in self._windows if lowered in w.title.lower()]

    def find_window(self, title_pattern: str) -> WindowInfo | None:
        found = self.list_windows(title_pattern)
        return found[0] if found else None


def build_fake_backends(
    *,
    image: Any = None,
    size: tuple[int, int] = (1280, 720),
    frames: list[Any] | None = None,
    windows: list[WindowInfo] | None = None,
    **_ignored: Any,
) -> BackendBundle:
    """装配假后端三件套。返回的 ``BackendBundle`` 上可直接取 ``.input.events``。"""
    screen = FakeScreenBackend(image=image, size=size, frames=frames)
    return BackendBundle(
        screen=screen,
        input=FakeInputBackend(size=size),
        window=FakeWindowBackend(windows),
    )
