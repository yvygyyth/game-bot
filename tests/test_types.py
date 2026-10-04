"""L0 类型层测试 —— 这是全框架唯一"已完整实现"的一层，所以要测得实一点。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from gamebot.types import ActionResult, ActionStatus, Point, Region


class TestActionStatus:
    def test_four_states(self) -> None:
        assert [s.value for s in ActionStatus] == ["success", "not_found", "timeout", "error"]

    def test_ok_property(self) -> None:
        assert ActionStatus.SUCCESS.ok is True
        for other in (ActionStatus.NOT_FOUND, ActionStatus.TIMEOUT, ActionStatus.ERROR):
            assert other.ok is False

    def test_is_str_enum(self) -> None:
        assert ActionStatus.SUCCESS == "success"
        assert str(ActionStatus.TIMEOUT) == "timeout"


class TestActionResult:
    def test_success_factory(self) -> None:
        result = ActionResult.success(Point(1, 2), score=0.93)
        assert result.ok
        assert result.value == Point(1, 2)
        assert result.meta["score"] == 0.93
        assert result.failed is False

    def test_success_with_named_fields(self) -> None:
        result = ActionResult.success(7, message="读到了", elapsed=0.25)
        assert result.message == "读到了"
        assert result.elapsed == 0.25
        assert result.meta == {}

    def test_not_found_and_timeout(self) -> None:
        assert ActionResult.not_found("没找到").status is ActionStatus.NOT_FOUND
        assert ActionResult.timeout("超时", waited=3.0).meta["waited"] == 3.0

    def test_error_records_exception(self) -> None:
        result = ActionResult.error("崩了", exc=ValueError("坏值"))
        assert result.status is ActionStatus.ERROR
        assert result.meta["exc_type"] == "ValueError"
        assert result.meta["exc"] == "坏值"

    def test_map_only_touches_success(self) -> None:
        assert ActionResult.success(2).map(lambda v: v * 10).value == 20
        failed = ActionResult.not_found("无")
        assert failed.map(lambda v: v * 10).value is None
        assert failed.map(lambda v: v * 10).status is ActionStatus.NOT_FOUND

    def test_unwrap(self) -> None:
        assert ActionResult.success(5).unwrap(0) == 5
        assert ActionResult.not_found().unwrap(0) == 0

    def test_with_meta_does_not_mutate_original(self) -> None:
        original = ActionResult.success(1, a=1)
        changed = original.with_meta(b=2)
        assert original.meta == {"a": 1}
        assert changed.meta == {"a": 1, "b": 2}

    def test_with_elapsed(self) -> None:
        assert ActionResult.success(1).with_elapsed(0.5).elapsed == 0.5

    def test_to_dict_is_jsonable(self) -> None:
        import json

        payload = ActionResult.success(Point(3, 4), score=0.9).to_dict()
        assert payload["status"] == "success"
        assert payload["value"] == {"x": 3, "y": 4}
        json.dumps(payload)  # 不应抛异常

    def test_frozen(self) -> None:
        result = ActionResult.success(1)
        with pytest.raises(FrozenInstanceError):
            result.value = 2  # type: ignore[misc]


class TestPoint:
    def test_basics(self) -> None:
        point = Point(10, 20)
        assert point.as_tuple() == (10, 20)
        assert tuple(point) == (10, 20)

    def test_offset_and_arithmetic(self) -> None:
        assert Point(10, 20).offset(5, -5) == Point(15, 15)
        assert Point(1, 2) + Point(3, 4) == Point(4, 6)
        assert Point(3, 4) - Point(1, 1) == Point(2, 3)

    def test_roundtrip(self) -> None:
        point = Point(7, 8)
        assert Point.from_dict(point.to_dict()) == point
        assert Point.from_tuple((7, 8)) == point

    def test_hashable(self) -> None:
        assert len({Point(1, 2), Point(1, 2)}) == 1


class TestRegion:
    def test_edges_are_half_open(self) -> None:
        region = Region(10, 20, 30, 40)
        assert (region.left, region.top, region.right, region.bottom) == (10, 20, 40, 60)
        assert region.size == (30, 40)
        assert region.area == 1200

    def test_center(self) -> None:
        assert Region(0, 0, 10, 10).center == Point(5, 5)

    def test_contains(self) -> None:
        region = Region(10, 10, 10, 10)
        assert region.contains(Point(10, 10))
        assert region.contains(Point(19, 19))
        assert not region.contains(Point(20, 19))  # 右界不含
        assert not region.contains(Point(9, 10))

    def test_contains_region(self) -> None:
        outer = Region(0, 0, 100, 100)
        assert outer.contains_region(Region(10, 10, 20, 20))
        assert outer.contains_region(outer)
        assert not outer.contains_region(Region(90, 90, 20, 20))

    def test_intersect(self) -> None:
        assert Region(0, 0, 10, 10).intersect(Region(5, 5, 10, 10)) == Region(5, 5, 5, 5)
        assert Region(0, 0, 5, 5).intersect(Region(10, 10, 5, 5)) is None
        # 仅接触边界不算相交（半开区间）
        assert Region(0, 0, 5, 5).intersect(Region(5, 0, 5, 5)) is None

    def test_union(self) -> None:
        assert Region(0, 0, 5, 5).union(Region(10, 10, 5, 5)) == Region(0, 0, 15, 15)

    def test_offset_expand_clamp(self) -> None:
        assert Region(1, 2, 3, 4).offset(10, 10) == Region(11, 12, 3, 4)
        assert Region(10, 10, 10, 10).expand(5) == Region(5, 5, 20, 20)
        assert Region(-10, -10, 30, 30).clamp(Region(0, 0, 100, 100)) == Region(0, 0, 20, 20)

    def test_from_corners_and_full(self) -> None:
        assert Region.from_corners(10, 20, 40, 60) == Region(10, 20, 30, 40)
        assert Region.full(1920, 1080) == Region(0, 0, 1920, 1080)

    def test_to_mss(self) -> None:
        assert Region(1, 2, 3, 4).to_mss() == {"left": 1, "top": 2, "width": 3, "height": 4}

    def test_roundtrip(self) -> None:
        region = Region(1, 2, 3, 4)
        assert Region.from_dict(region.to_dict()) == region
        assert Region.from_tuple(region.to_tuple()) == region
        assert region.to_tuple() == (1, 2, 3, 4)
