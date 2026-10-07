"""Windows 后端测试：坐标必须是**绝对屏幕坐标**。

## 为什么专门测这一条

输入这条链路一直只用 ``FakeInputBackend`` 验证过，而假后端不关心屏幕坐标 ——
所以"忘了加捕获区原点"这个 bug 靠假后端**永远测不出来**，
靠肉眼也测不出来（整张卡片偏 21/49 像素照样点在卡上）。

真机验证时才发现：`SetCursorPos` / `SendInput` 要的是绝对屏幕坐标，
而 ``session.input`` 收到的是源坐标（客户区相对）。这里用"把真实输入实现
换成记录器"的办法，在不需要真实鼠标的前提下把这个契约钉死。
"""

from __future__ import annotations

import sys

import pytest

from gamebot.atomic.backends.windows import WindowsInputBackend
from gamebot.exceptions import BackendError
from gamebot.types import Point, Region

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="windows 后端专用")


class RecordingImpl:
    """冒充 pydirectinput / pyautogui：只把收到的坐标记下来。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.FAILSAFE = True
        self.PAUSE = 0.0

    def moveTo(self, x: int, y: int, duration: float = 0) -> None:
        self.calls.append(("moveTo", int(x), int(y)))

    def click(self, button: str = "left") -> None:
        self.calls.append(("click", 0, 0))

    def mouseDown(self, button: str = "left") -> None:
        self.calls.append(("down", 0, 0))

    def mouseUp(self, button: str = "left") -> None:
        self.calls.append(("up", 0, 0))

    def scroll(self, clicks: int) -> None:
        self.calls.append(("scroll", 0, 0))


def make_backend(offset: tuple[int, int] | None) -> tuple[WindowsInputBackend, RecordingImpl]:
    backend = WindowsInputBackend(
        offset_provider=(None if offset is None else lambda: Region(offset[0], offset[1], 100, 100))
    )
    impl = RecordingImpl()
    backend._impl = impl  # 直接塞进去，绕开 __import__
    return backend, impl


class TestInputCoordinateOffset:
    def test_move_to_adds_capture_origin(self) -> None:
        backend, impl = make_backend((21, 49))
        backend.move_to(Point(1005, 455))
        assert impl.calls == [("moveTo", 1026, 504)]

    def test_click_adds_capture_origin(self) -> None:
        backend, impl = make_backend((21, 49))
        backend.click(Point(100, 200))
        assert impl.calls[:2] == [("moveTo", 121, 249), ("click", 0, 0)]

    def test_drag_offsets_both_ends(self) -> None:
        backend, impl = make_backend((21, 49))
        backend.drag(Point(10, 10), Point(20, 20), duration=0.06)
        positions = [(x, y) for name, x, y in impl.calls if name == "moveTo"]
        assert positions[0] == (31, 59)
        assert positions[-1] == (41, 69)

    def test_scroll_offsets_point(self) -> None:
        backend, impl = make_backend((21, 49))
        backend.scroll(-3, Point(5, 6))
        assert impl.calls[0] == ("moveTo", 26, 55)

    def test_no_provider_means_zero_offset(self) -> None:
        """抓整屏时捕获区原点就是 (0,0)，这条路径也必须对。"""
        backend, impl = make_backend(None)
        backend.move_to(Point(1005, 455))
        assert impl.calls == [("moveTo", 1005, 455)]

    def test_zero_offset_is_a_noop(self) -> None:
        backend, impl = make_backend((0, 0))
        backend.move_to(Point(7, 8))
        assert impl.calls == [("moveTo", 7, 8)]

    def test_offset_is_read_per_call_not_cached(self) -> None:
        """窗口会被拖动 —— 算死偏移就会悄悄错位。"""
        box = {"region": Region(21, 49, 100, 100)}
        backend = WindowsInputBackend(offset_provider=lambda: box["region"])
        impl = RecordingImpl()
        backend._impl = impl

        backend.move_to(Point(10, 10))
        box["region"] = Region(500, 300, 100, 100)  # 用户把窗口挪走了
        backend.move_to(Point(10, 10))

        assert impl.calls == [("moveTo", 31, 59), ("moveTo", 510, 310)]

    def test_broken_provider_falls_back_to_zero(self) -> None:
        """窗口刚被关掉时取不到区域 —— 宁可点偏，也不能让脚本崩。"""

        def boom() -> Region:
            raise RuntimeError("窗口没了")

        backend = WindowsInputBackend(offset_provider=boom)
        impl = RecordingImpl()
        backend._impl = impl
        backend.move_to(Point(3, 4))
        assert impl.calls == [("moveTo", 3, 4)]


class TestCoordinateSpace:
    """``coordinate_space`` —— 脚本里写的坐标是哪一套。

    两套只差一个常量：**捕获区在屏幕上的原点**。

        source（默认） 0 起点 = 捕获区（客户区）左上角   <- Frame / 模板 / roi
        screen        0 起点 = 显示器左上角            <- 桌面取点工具量出来的

    ``screen`` 时后端**先减掉那个原点**，之后完全走 source 那条路 ——
    所以换算只有一层，动作层 / 步骤 / 模板都不用知道这个开关存在。
    """

    def _make(self, space: str, offset: tuple[int, int] = (1, 31)):
        backend = WindowsInputBackend(
            offset_provider=lambda: Region(offset[0], offset[1], 100, 100),
            coordinate_space=space,
        )
        impl = RecordingImpl()
        backend._impl = impl
        return backend, impl

    def test_screen_space_uses_the_point_as_is(self):
        """屏幕坐标：加一次原点、减一次原点 -> 净效果就是原样点。

        这条是**这个功能的全部意义**：人手量的屏幕坐标 (1366, 616) 必须
        原样落到屏幕 (1366, 616)，不能再被加一次窗口原点。
        """
        backend, impl = self._make("screen")
        backend.move_to(Point(1366, 616))
        assert impl.calls == [("moveTo", 1366, 616)]

    def test_source_space_still_adds_the_origin(self):
        """source 坐标（默认）：加一次原点 —— 老行为一个字不改。"""
        backend, impl = self._make("source")
        backend.move_to(Point(1365, 585))
        assert impl.calls == [("moveTo", 1366, 616)]

    def test_the_two_spaces_land_on_the_same_screen_point(self):
        """同**一个屏幕位置**，两套写法必须点到同一个地方。

        这是"两套坐标能混用"的前提：source (1365,585) + 原点(1,31)
        == screen (1366,616)。
        """
        src_backend, src_impl = self._make("source")
        scr_backend, scr_impl = self._make("screen")

        src_backend.move_to(Point(1365, 585))  # 捕获区坐标
        scr_backend.move_to(Point(1366, 616))  # 同一个位置的屏幕坐标

        assert src_impl.calls == scr_impl.calls == [("moveTo", 1366, 616)]

    def test_screen_space_tracks_a_moved_window(self):
        """窗口挪走之后，屏幕坐标**不需要改**（还是那个屏幕位置）。

        这正是"用屏幕坐标"的取舍：坐标不随窗口动，但也**依赖窗口没动**时
        量的数才对。source 坐标反过来：写死的数跟着窗口走，但换机器要重量。
        """
        box = {"region": Region(1, 31, 100, 100)}
        backend = WindowsInputBackend(
            offset_provider=lambda: box["region"], coordinate_space="screen"
        )
        impl = RecordingImpl()
        backend._impl = impl

        backend.move_to(Point(1366, 616))
        box["region"] = Region(500, 300, 100, 100)  # 窗口被挪走
        backend.move_to(Point(1366, 616))

        # 两次都点屏幕 (1366, 616) —— 屏幕坐标与窗口位置无关
        assert impl.calls == [("moveTo", 1366, 616), ("moveTo", 1366, 616)]

    def test_bad_space_is_rejected_loudly(self):
        """拼错的坐标空间要当场报，不能静默按 source 处理（那样会整体偏）。"""
        with pytest.raises(BackendError, match="coordinate_space"):
            WindowsInputBackend(coordinate_space="screens")
