"""运行时上下文与假后端的测试。

上下文是三个层共享的对象，它的行为（帧的新鲜度、可中止的 sleep、中止信号）
如果不对，上层会出现很难查的时序 bug。所以这里测得细一点。

中止的**单一事实源是 session**，`RunContext` 只做转发 —— 所以这一组测试
既测 session 上的原语，也测 `RunContext` 的转发确实通了。
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from gamebot.atomic.backends.fake import FakeInputBackend, build_fake_backends
from gamebot.atomic.session import BaseSession
from gamebot.context import RunContext
from gamebot.exceptions import Cancelled
from gamebot.types import Point, Region


class TestStopSignal:
    """中止信号（跑在 session 上，RunContext 转发）。"""

    def test_default_is_not_requested(self, session: BaseSession) -> None:
        assert session.stop_requested is False
        assert session.stop_reason == ""

    def test_request_records_reason(self, session: BaseSession) -> None:
        session.request_stop("用户点了停止")
        assert session.stop_requested is True
        assert session.stop_reason == "用户点了停止"

    def test_request_is_idempotent_and_keeps_first_reason(self, session: BaseSession) -> None:
        session.request_stop("第一次")
        session.request_stop("第二次")
        assert session.stop_reason == "第一次"

    def test_request_without_reason_gets_a_default(self, session: BaseSession) -> None:
        session.request_stop()
        assert session.stop_requested is True
        assert session.stop_reason

    def test_clear(self, session: BaseSession) -> None:
        session.request_stop("x")
        session.clear_stop()
        assert session.stop_requested is False
        assert session.stop_reason == ""

    def test_raise_if_stopped(self, session: BaseSession) -> None:
        session.raise_if_stopped()  # 未请求时不应抛
        session.request_stop("走开")
        with pytest.raises(Cancelled) as excinfo:
            session.raise_if_stopped()
        assert excinfo.value.reason == "走开"

    def test_cancelled_is_base_exception(self) -> None:
        """必须继承 BaseException：否则会被到处存在的 `except Exception` 吞掉。"""
        assert issubclass(Cancelled, BaseException)
        assert not issubclass(Cancelled, Exception)

    def test_sleep_wakes_immediately_on_stop(self, session: BaseSession) -> None:
        session.request_stop("立刻停")
        started = time.perf_counter()
        with pytest.raises(Cancelled):
            session.sleep(5.0)
        assert time.perf_counter() - started < 0.5

    def test_sleep_is_woken_from_another_thread(self, session: BaseSession) -> None:
        """UI 线程点停止时，正在睡的等待方必须立刻醒 —— 这是"马上中止"的核心。"""
        outcome: list[str] = []

        def worker() -> None:
            started = time.perf_counter()
            try:
                session.sleep(10.0)
            except Cancelled:
                outcome.append("cancelled")
                outcome.append(f"{time.perf_counter() - started:.2f}")

        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.15)
        session.request_stop("外部中止")
        thread.join(timeout=2.0)
        assert not thread.is_alive(), "等待方没有被唤醒"
        assert outcome[0] == "cancelled"
        assert float(outcome[1]) < 1.0

    def test_sleep_zero_still_checks(self, session: BaseSession) -> None:
        session.request_stop("x")
        with pytest.raises(Cancelled):
            session.sleep(0)

    def test_sleep_actually_waits(self, session: BaseSession) -> None:
        started = time.perf_counter()
        session.sleep(0.1)
        assert time.perf_counter() - started >= 0.08

    def test_stop_is_per_session(self) -> None:
        from tests.conftest import FakeMatcher

        first = BaseSession(build_fake_backends(), matcher=FakeMatcher())
        second = BaseSession(build_fake_backends(), matcher=FakeMatcher())
        first.request_stop("只停这个")
        assert first.stop_requested is True
        assert second.stop_requested is False


class TestFrameLifecycle:
    def test_capture_stores_current_frame(self, ctx: RunContext) -> None:
        assert ctx.current_frame is None
        frame = ctx.capture()
        assert ctx.current_frame is frame
        assert ctx.capture_count == 1

    def test_frame_reuses_cached_frame(self, ctx: RunContext) -> None:
        first = ctx.frame()
        second = ctx.frame()
        assert first is second
        assert ctx.capture_count == 1

    def test_frame_refreshes_when_stale(self, ctx: RunContext) -> None:
        ctx.frame_ttl = 0.0
        first = ctx.frame()
        time.sleep(0.01)
        second = ctx.frame()
        assert first is not second

    def test_frame_fresh_flag_forces_capture(self, ctx: RunContext) -> None:
        first = ctx.frame()
        second = ctx.frame(fresh=True)
        assert first is not second

    def test_frame_with_region_always_captures(self, ctx: RunContext) -> None:
        ctx.frame()
        frame = ctx.frame(Region(10, 10, 20, 20))
        assert frame.origin == Region(10, 10, 20, 20)

    def test_invalidate_frame(self, ctx: RunContext) -> None:
        ctx.frame()
        ctx.invalidate_frame()
        assert ctx.current_frame is None
        assert ctx.frame_age == float("inf")

    def test_frame_age(self, ctx: RunContext) -> None:
        ctx.capture()
        assert ctx.frame_age >= 0.0


class TestStopHandling:
    """RunContext 上的中止接口 —— 全部转发给 session。"""

    def test_request_stop(self, ctx: RunContext) -> None:
        assert ctx.stop_requested is False
        ctx.request_stop("测试停止")
        assert ctx.stop_requested is True
        assert ctx.stop_reason == "测试停止"

    def test_forwarded_to_session(self, ctx: RunContext) -> None:
        ctx.request_stop("转发")
        assert ctx.session.stop_requested is True
        assert ctx.session.stop_reason == "转发"

    def test_sleep_raises_immediately_when_stopped(self, ctx: RunContext) -> None:
        """中止是异常、不是"提前返回" —— 调用方必须知道这一觉没睡完。"""
        ctx.request_stop("立刻停")
        started = time.perf_counter()
        with pytest.raises(Cancelled) as excinfo:
            ctx.sleep(5.0)
        assert time.perf_counter() - started < 0.5
        assert excinfo.value.reason == "立刻停"

    def test_raise_if_stopped_forwards(self, ctx: RunContext) -> None:
        ctx.raise_if_stopped()
        ctx.request_stop("走开")
        with pytest.raises(Cancelled):
            ctx.raise_if_stopped()

    def test_sleep_zero_is_noop(self, ctx: RunContext) -> None:
        ctx.sleep(0)

    def test_sleep_actually_waits(self, ctx: RunContext) -> None:
        started = time.perf_counter()
        ctx.sleep(0.15)
        assert time.perf_counter() - started >= 0.12

    def test_reset_clears_everything(self, ctx: RunContext) -> None:
        ctx.capture()
        ctx.blackboard.set("a", 1)
        ctx.pages.advance_tick()
        ctx.request_stop("x")
        ctx.reset()
        assert ctx.blackboard.as_dict() == {}
        assert ctx.pages.tick == 0
        assert ctx.stop_requested is False
        assert ctx.capture_count == 0


class TestQueriesOnContext:
    def test_query_runs_on_current_frame(self, ctx: RunContext) -> None:
        from gamebot.atomic.query import PixelQuery

        result = ctx.query(PixelQuery(Point(1, 1), expected_color=(0, 0, 0), tolerance=0))
        assert result.ok

    def test_find_image_delegates_to_frame(self, ctx: RunContext) -> None:
        """走的是 ctx -> Frame -> Session.matcher 这条链。

        conftest 的 FakeMatcher 登记了 "a.png" -> (100, 50)，所以这里应当命中。
        """
        result = ctx.find_image("a.png")
        assert result.ok
        assert result.value == Point(100, 50)

    def test_find_image_miss_is_not_found(self, ctx: RunContext) -> None:
        result = ctx.find_image("没有这张图.png")
        assert not result.ok
        assert result.status.value == "not_found"


class TestPaths:
    def test_screenshot_path_creates_dir(self, ctx: RunContext) -> None:
        path = ctx.screenshot_path("fail tick 42/step one")
        assert path.parent.is_dir()
        assert path.suffix == ".png"
        # 文件名里的非法字符要被替换掉
        assert " " not in path.name
        assert "/" not in path.name

    def test_journal_path(self, ctx: RunContext) -> None:
        path = ctx.journal_path("demo")
        assert path.parent.is_dir()
        assert path.name.startswith("demo-")
        assert path.suffix == ".jsonl"


class TestFakeBackends:
    def test_screen_size(self) -> None:
        bundle = build_fake_backends(size=(800, 600))
        assert bundle.screen.screen_size() == (800, 600)

    def test_grab_returns_bgr_array(self) -> None:
        bundle = build_fake_backends(size=(64, 32))
        image = bundle.screen.grab()
        assert image.shape == (32, 64, 3)
        assert image.dtype == np.uint8

    def test_grab_region(self) -> None:
        bundle = build_fake_backends(size=(640, 360))
        image = bundle.screen.grab(Region(10, 10, 20, 30))
        assert image.shape == (30, 20, 3)

    def test_grab_returns_a_copy(self) -> None:
        bundle = build_fake_backends(size=(8, 8))
        first = bundle.screen.grab()
        first[:] = 255
        second = bundle.screen.grab()
        assert second.max() == 0

    def test_frames_sequence(self) -> None:
        a = np.zeros((10, 10, 3), dtype=np.uint8)
        b = np.full((10, 10, 3), 9, dtype=np.uint8)
        bundle = build_fake_backends(frames=[a, b])
        assert bundle.screen.grab().max() == 0
        assert bundle.screen.grab().max() == 9
        # 播完停在最后一帧，不抛异常
        assert bundle.screen.grab().max() == 9

    def test_input_backend_records_events(self) -> None:
        bundle = build_fake_backends()
        backend: FakeInputBackend = bundle.input
        backend.click(Point(1, 2))
        backend.hotkey(["ctrl", "s"])
        assert backend.events[0][0] == "click"
        assert backend.events[1] == ("hotkey", ["ctrl", "s"])
        backend.clear()
        assert backend.events == []

    def test_window_backend_filtering(self) -> None:
        from gamebot.atomic.backends.base import WindowInfo

        windows = [
            WindowInfo(1, "游戏 - 主界面", Region(0, 0, 100, 100)),
            WindowInfo(2, "记事本", Region(0, 0, 50, 50)),
        ]
        bundle = build_fake_backends(windows=windows)
        assert len(bundle.window.list_windows()) == 2
        assert bundle.window.find_window("游戏").handle == 1
        assert bundle.window.find_window("不存在") is None

    def test_session_can_be_built_on_fake_backends(self) -> None:
        from tests.conftest import FakeMatcher

        bundle = build_fake_backends(size=(100, 50))
        session = BaseSession(bundle, matcher=FakeMatcher())
        with session:
            assert session.get_screen_size().value == (100, 50)
