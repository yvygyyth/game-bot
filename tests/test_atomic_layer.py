"""原子层已实现部分的测试：Session / Frame / Query 的骨架行为。

这些测试**只覆盖已经实现的代码**（Session 组装、坐标换算、Frame 的
crop / get_pixel / 缓存、Query 的委托），不碰待实现的匹配算法 ——
所以它们现在就应该是绿的，而且以后实现算法时也不该变红。
"""

from __future__ import annotations

import pytest

from gamebot.atomic.query import (
    AllImagesQuery,
    AndQuery,
    ImageQuery,
    NotQuery,
    NumberQuery,
    OrQuery,
    PixelQuery,
    TextQuery,
    VisibleQuery,
    query_registry,
)
from gamebot.atomic.session import BaseSession, CoordinateMapper
from gamebot.atomic.vision import UnavailableTextReader
from gamebot.types import ActionResult, ActionStatus, Point, Region


# --------------------------------------------------------------------------- #
# CoordinateMapper
# --------------------------------------------------------------------------- #
class TestCoordinateMapper:
    def test_identity_when_no_logic_size(self) -> None:
        mapper = CoordinateMapper.detect((1920, 1080), None)
        assert mapper.is_identity
        assert mapper.to_source(Point(10, 20)) == Point(10, 20)

    def test_scaling(self) -> None:
        mapper = CoordinateMapper(1280, 720, 1920, 1080)
        assert mapper.scale_x == pytest.approx(1280 / 1920)
        assert mapper.to_source(Point(1920, 1080)) == Point(1280, 720)
        assert mapper.to_source(Point(960, 540)) == Point(640, 360)
        assert mapper.to_logic(Point(640, 360)) == Point(960, 540)

    def test_region_roundtrip(self) -> None:
        mapper = CoordinateMapper(1280, 720, 1920, 1080)
        source = mapper.region_to_source(Region(960, 540, 192, 108))
        assert source == Region(640, 360, 128, 72)
        back = mapper.region_to_logic(source)
        assert back.w == pytest.approx(192, abs=1)
        assert back.h == pytest.approx(108, abs=1)

    def test_identity_factory(self) -> None:
        assert CoordinateMapper.identity(800, 600).is_identity


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
class TestBaseSession:
    def test_capture_returns_full_frame(self, session: BaseSession) -> None:
        frame = session.capture()
        assert frame.size == (640, 360)
        assert frame.origin == Region(0, 0, 640, 360)
        assert frame.session is session

    def test_capture_region_keeps_origin(self, session: BaseSession) -> None:
        region = Region(100, 50, 80, 30)
        frame = session.capture_region(region)
        assert frame.origin == region
        assert frame.size == (80, 30)

    def test_get_screen_size(self, session: BaseSession) -> None:
        result = session.get_screen_size()
        assert result.ok
        assert result.value == (640, 360)

    def test_get_screen_size_wraps_backend_error(self, session: BaseSession) -> None:
        def boom() -> tuple[int, int]:
            raise RuntimeError("设备掉线")

        session.screen_backend.screen_size = boom  # type: ignore[method-assign]
        result = session.get_screen_size()
        assert result.status is ActionStatus.ERROR
        assert "设备掉线" in result.message

    def test_to_screen_uses_mapper(self, session: BaseSession) -> None:
        assert session.to_screen(Point(10, 10)) == Point(10, 10)

    def test_context_manager_closes(self, session: BaseSession) -> None:
        with session as opened:
            assert opened is session
        # 二次 close 不应抛异常（幂等）
        session.close()

    def test_input_backend_is_exposed(self, session: BaseSession) -> None:
        session.input.move_to(Point(1, 2))
        assert session.input.position == Point(1, 2)


# --------------------------------------------------------------------------- #
# Frame
# --------------------------------------------------------------------------- #
class TestFrameImplementedParts:
    def test_to_numpy_returns_same_object(self, frame) -> None:
        assert frame.to_numpy() is frame.image

    def test_crop_translates_origin(self, frame) -> None:
        sub = frame.crop(Region(100, 50, 80, 30))
        assert sub.origin == Region(100, 50, 80, 30)
        assert sub.size == (80, 30)
        # 子帧上的局部点要能换算回源坐标
        assert sub._to_source(Point(0, 0)) == Point(100, 50)

    def test_crop_outside_raises(self, frame) -> None:
        with pytest.raises(ValueError):
            frame.crop(Region(1000, 1000, 10, 10))

    def test_get_pixel_in_range(self, frame) -> None:
        result = frame.get_pixel(Point(5, 5))
        assert result.ok
        assert result.value == (0, 0, 0)

    def test_get_pixel_out_of_range(self, frame) -> None:
        result = frame.get_pixel(Point(9999, 9999))
        assert result.status is ActionStatus.ERROR

    def test_frame_ids_are_unique(self, session: BaseSession) -> None:
        a = session.capture()
        b = session.capture()
        assert a.frame_id != b.frame_id

    def test_cache_stores_result_once(self, frame) -> None:
        calls = 0

        def producer() -> ActionResult[int]:
            nonlocal calls
            calls += 1
            return ActionResult.success(calls)

        assert frame.cached("k", producer).value == 1
        assert frame.cached("k", producer).value == 1
        assert calls == 1
        frame.clear_cache()
        assert frame.cached("k", producer).value == 2

    def test_cache_also_stores_failures(self, frame) -> None:
        calls = 0

        def producer() -> ActionResult[None]:
            nonlocal calls
            calls += 1
            return ActionResult.not_found("没有")

        frame.cached("miss", producer)
        frame.cached("miss", producer)
        assert calls == 1

    def test_resolve_region_clamps(self, frame) -> None:
        assert frame._resolve_region(None) == Region(0, 0, 640, 360)
        clamped = frame._resolve_region(Region(-50, -50, 100, 100))
        assert clamped == Region(0, 0, 50, 50)
        # 超出右下界也要裁掉，但左上角保持原样
        overflow = frame._resolve_region(Region(600, 340, 100, 100))
        assert overflow == Region(600, 340, 40, 20)

    def test_confidence_falls_back_to_session(self, session: BaseSession) -> None:
        frame = session.capture()
        assert frame._confidence(None) == session.default_confidence
        assert frame._confidence(0.5) == 0.5


# --------------------------------------------------------------------------- #
# Query 委托
# --------------------------------------------------------------------------- #
class RecordingFrame:
    """记录调用的假帧 —— Query 只依赖 Frame 的方法签名，所以不需要真 Frame。"""

    def __init__(self, result: ActionResult | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._result = result if result is not None else ActionResult.success(Point(1, 1))

    def _record(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        return self._result

    def find_image(self, template, region=None, confidence=None, use_pyramid=True, grayscale=True):
        return self._record(
            "find_image",
            template=template,
            region=region,
            confidence=confidence,
            use_pyramid=use_pyramid,
            grayscale=grayscale,
        )

    def find_all_images(self, template, region=None, confidence=0.9, max_count=0, min_distance=10):
        return self._record("find_all_images", template=template, max_count=max_count)

    def find_text(self, text, region=None, lang="ch", confidence=0.8, exact_match=False):
        return self._record("find_text", text=text, lang=lang, exact_match=exact_match)

    def find_all_texts(self, text, region=None, lang="ch", confidence=0.8):
        return self._record("find_all_texts", text=text)

    def read_number(self, region, lang="en", confidence=0.7):
        return self._record("read_number", region=region, lang=lang)

    def get_pixel(self, point):
        return self._record("get_pixel", point=point)

    def compare_region(self, region, template, confidence=0.9):
        return self._record("compare_region", region=region, template=template)

    def is_image_visible(self, template, region=None, confidence=0.9):
        return self._record("is_image_visible", template=template)


class TestQueries:
    def test_image_query_passes_all_params(self) -> None:
        frame = RecordingFrame()
        region = Region(0, 0, 10, 10)
        ImageQuery(
            "a.png", region=region, confidence=0.8, use_pyramid=False, grayscale=False
        ).run(frame)
        name, kwargs = frame.calls[0]
        assert name == "find_image"
        assert kwargs["template"] == "a.png"
        assert kwargs["region"] == region
        assert kwargs["confidence"] == 0.8
        assert kwargs["use_pyramid"] is False
        assert kwargs["grayscale"] is False

    def test_all_images_query(self) -> None:
        frame = RecordingFrame()
        AllImagesQuery("a.png", max_count=3).run(frame)
        assert frame.calls[0][1]["max_count"] == 3

    def test_text_query(self) -> None:
        frame = RecordingFrame()
        TextQuery("开始", lang="ch", exact_match=True).run(frame)
        assert frame.calls[0][1]["exact_match"] is True

    def test_number_query_passes_through_when_ok(self) -> None:
        frame = RecordingFrame(ActionResult.success(120))
        result = NumberQuery(Region(0, 0, 50, 20), comparator=lambda v: v >= 100).run(frame)
        assert result.ok
        assert result.value == 120

    def test_number_query_fails_on_comparator(self) -> None:
        frame = RecordingFrame(ActionResult.success(5))
        result = NumberQuery(Region(0, 0, 50, 20), comparator=lambda v: v >= 100).run(frame)
        assert result.status is ActionStatus.NOT_FOUND

    def test_pixel_query_matches_expected_color(self) -> None:
        frame = RecordingFrame(ActionResult.success((250, 10, 10)))
        result = PixelQuery(Point(1, 1), expected_color=(255, 0, 0), tolerance=10).run(frame)
        assert result.ok

    def test_pixel_query_rejects_wrong_color(self) -> None:
        frame = RecordingFrame(ActionResult.success((0, 0, 0)))
        result = PixelQuery(Point(1, 1), expected_color=(255, 0, 0), tolerance=10).run(frame)
        assert result.status is ActionStatus.NOT_FOUND

    def test_pixel_query_without_expectation_just_reads(self) -> None:
        frame = RecordingFrame(ActionResult.success((1, 2, 3)))
        assert PixelQuery(Point(1, 1)).run(frame).value == (1, 2, 3)

    def test_visible_query_delegates(self) -> None:
        frame = RecordingFrame(ActionResult.success(False))
        result = VisibleQuery("a.png").run(frame)
        assert result.ok
        assert result.value is False

    def test_composite_queries_are_dataclasses(self) -> None:
        inner = ImageQuery("a.png")
        assert AndQuery((inner,)).queries == (inner,)
        assert OrQuery((inner,), short_circuit=False).short_circuit is False
        assert NotQuery(inner).query is inner

    def test_registry_covers_all(self) -> None:
        registry = query_registry()
        assert registry["ImageQuery"] is ImageQuery
        assert registry["NotQuery"] is NotQuery
        # 返回的是副本，外部改不动内部表
        registry.clear()
        assert query_registry()


# --------------------------------------------------------------------------- #
# 退化 OCR
# --------------------------------------------------------------------------- #
class TestUnavailableTextReader:
    def test_returns_empty_not_raises(self) -> None:
        reader = UnavailableTextReader("没装 OCR")
        assert reader.locate(None, "开始") == []
        assert reader.read(None) == ""
        assert "没装 OCR" in repr(reader)
