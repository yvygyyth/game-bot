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
    # 固定"鼠标当前在哪" —— 否则滑动手势读的是**真机鼠标位置**，
    # 断言会随你手动挪鼠标而变（这类测试必须与环境无关）。
    backend._cursor_or_none = lambda: (0, 0)  # type: ignore[method-assign]
    return backend, impl


def presses(impl: RecordingImpl) -> list[tuple[str, int, int]]:
    """只取"按下/抬起"事件 —— 滑动过程的 moveTo 数量随参数变，不适合断言。"""
    return [call for call in impl.calls if call[0] in ("down", "up", "click")]


def last_move(impl: RecordingImpl) -> tuple[str, int, int]:
    """最后一次移动 —— 它必须落在目标点上（不管中间滑了几步）。"""
    moves = [call for call in impl.calls if call[0] == "moveTo"]
    assert moves, "一次移动都没有"
    return moves[-1]


class TestInputCoordinateOffset:
    def test_move_to_adds_capture_origin(self) -> None:
        backend, impl = make_backend((21, 49))
        backend.move_to(Point(1005, 455))
        assert impl.calls == [("moveTo", 1026, 504)]

    def test_click_adds_capture_origin(self) -> None:
        backend, impl = make_backend((21, 49))
        backend.click(Point(100, 200))
        # 单击是显式 down/up（见 WindowsInputBackend.click 的说明）；
        # 最后那次移动必须落在 目标 + 捕获区原点 上。
        assert last_move(impl) == ("moveTo", 121, 249)
        assert presses(impl) == [("down", 0, 0), ("up", 0, 0)]

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


class TestMoveSettleBeforePress:
    """**移动和按下之间必须有间隔** —— 这是"点了没反应"那个 bug 的根因。

    症状极具迷惑性：动作层返回成功、`GetCursorPos` 也确实是目标点、
    日志里识别也命中了。**唯一看出问题的地方是游戏自己没反应。**

    原因：游戏的位置跟踪在它自己的帧里做。移过去之后立刻按，游戏下一帧轮询时
    按下的消息已经带着**移动前的位置**到了，于是这一下被当成"在别处点了一下"
    丢掉。
    """

    def _make(self, *, move_settle: float, glide_steps: int = 1):
        backend = WindowsInputBackend(
            offset_provider=lambda: Region(0, 0, 100, 100),
            move_settle=move_settle,
            # 关掉滑动（steps=1）:这条测试只关心"滑到之后有没有停一下"，
            # 让移动只产生一次 moveTo，断言才读得清。
            glide_steps=glide_steps,
            move_glide=0.0,
        )
        impl = RecordingImpl()
        backend._impl = impl
        backend._cursor_or_none = lambda: (0, 0)  # type: ignore[method-assign]
        return backend, impl

    def test_it_sleeps_between_move_and_press(self, monkeypatch) -> None:
        """按下之前必须睡一次 —— 断言的是**顺序**，不是具体秒数。"""
        slept: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

        backend, impl = self._make(move_settle=0.08)
        backend.click(Point(10, 20))

        assert impl.calls[0][0] == "moveTo", "先移动"
        assert impl.calls[1][0] == "down", "再按下"
        assert 0.08 in slept, f"移动和按下之间应该睡 0.08s，实际睡的: {slept}"

    def test_zero_disables_it(self, monkeypatch) -> None:
        """``move_settle=0`` 关掉它 —— 用来复现"点了没反应"。"""
        slept: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

        backend, impl = self._make(move_settle=0)
        backend.click(Point(10, 20))

        assert impl.calls[0][0] == "moveTo"
        assert impl.calls[1][0] == "down"
        assert 0.08 not in slept

    def test_press_and_release_are_separate(self) -> None:
        """单击也要显式 down/up —— 部分游戏把过短的"按下"当抖动丢掉。"""
        backend, impl = self._make(move_settle=0)
        backend.click(Point(10, 20))
        assert [name for name, _, _ in presses(impl)] == ["down", "up"]


class TestGlideGeneratesAContinuousPath:
    """移过去要**分多步**，不能瞬移。

    为什么不直接用 ``impl.moveTo(x, y, duration=...)``：``pydirectinput``
    带 duration 时走 ``moveRel`` —— **一次 SendInput 发完整个位移**，
    不是插值。游戏那一帧收到的还是"从 A 跳到 B"。

    有些游戏（带 3D 场景/自由视角的）自己维护鼠标位置，只认连续轨迹；
    直接跳过去那一跳它可能当成视角回正而丢掉 —— 于是"点不中"。
    """

    def _make(self, *, glide_steps: int, move_glide: float):
        backend = WindowsInputBackend(
            offset_provider=lambda: Region(0, 0, 4000, 4000),
            move_settle=0.0,
            move_glide=move_glide,
            glide_steps=glide_steps,
        )
        impl = RecordingImpl()
        backend._impl = impl
        backend._cursor_or_none = lambda: (0, 0)  # type: ignore[method-assign]
        return backend, impl

    def test_it_emits_multiple_moves(self, monkeypatch) -> None:
        """滑动手势要产生**多于一次**移动事件，而且最后一步落在目标上。"""
        monkeypatch.setattr("time.sleep", lambda _s: None)  # 别真等
        backend, impl = self._make(glide_steps=8, move_glide=0.5)
        backend.click(Point(1000, 500))

        moves = [c for c in impl.calls if c[0] == "moveTo"]
        assert len(moves) > 1, "只移动了一次 —— 那是瞬移，不是滑动"
        assert moves[-1] == ("moveTo", 1000, 500), "最后一步必须精确落在目标点"

    def test_steps_are_monotonic_towards_target(self, monkeypatch) -> None:
        """每一步都要比上一步更靠近目标（是真插值，不是乱跳）。"""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        backend, impl = self._make(glide_steps=6, move_glide=0.5)
        backend.click(Point(600, 300))

        xs = [c[1] for c in impl.calls if c[0] == "moveTo"]
        assert xs == sorted(xs), f"横坐标不是单调靠近目标: {xs}"
        assert xs[0] > 0 and xs[-1] == 600

    def test_one_step_is_a_teleport(self) -> None:
        """``glide_steps=1`` 退化成瞬移 —— 留着复现"点了没反应"。"""
        backend, impl = self._make(glide_steps=1, move_glide=0.0)
        backend.click(Point(1000, 500))
        moves = [c for c in impl.calls if c[0] == "moveTo"]
        assert moves == [("moveTo", 1000, 500)]

    def test_nearby_target_skips_interpolation(self) -> None:
        """已经贴着目标就别插值了 —— 省时间，事件量也够。"""
        backend, impl = self._make(glide_steps=8, move_glide=0.5)
        backend._cursor_or_none = lambda: (998, 500)  # type: ignore[method-assign]
        backend.click(Point(1000, 500))
        moves = [c for c in impl.calls if c[0] == "moveTo"]
        assert moves == [("moveTo", 1000, 500)]


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
