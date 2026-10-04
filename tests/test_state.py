"""状态层已实现部分的测试：黑板、状态存储、快照、定义、识别器的骨架。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from gamebot.atomic.query import ImageQuery
from gamebot.state.definition import StateDefinition
from gamebot.state.detector import StateDetector
from gamebot.state.snapshot import UNKNOWN_STATE, StateChange, StateSnapshot
from gamebot.state.store import Blackboard, StateStore


class TestBlackboard:
    def test_get_set(self) -> None:
        board = Blackboard()
        board.set("a", 1)
        assert board.get("a") == 1
        assert board.get("missing", "默认") == "默认"

    def test_item_and_contains(self) -> None:
        board = Blackboard({"x": 1})
        assert "x" in board
        assert board["x"] == 1
        board["y"] = 2
        assert board["y"] == 2

    def test_update_and_len(self) -> None:
        board = Blackboard()
        board.update(a=1, b=2)
        assert len(board) == 2
        assert set(board) == {"a", "b"}

    def test_bump(self) -> None:
        board = Blackboard()
        assert board.bump("runs") == 1
        assert board.bump("runs") == 2
        assert board.bump("runs", 5) == 7
        assert board.bump("fresh", start=10) == 11

    def test_bump_on_non_int_falls_back_to_start(self) -> None:
        board = Blackboard({"weird": "字符串"})
        assert board.bump("weird", start=1) == 2

    def test_pop_and_clear(self) -> None:
        board = Blackboard({"a": 1})
        assert board.pop("a") == 1
        assert board.pop("a", 9) == 9
        board.update(b=2)
        board.clear()
        assert len(board) == 0

    def test_as_dict_is_a_copy(self) -> None:
        board = Blackboard({"a": 1})
        snapshot = board.as_dict()
        snapshot["a"] = 99
        assert board.get("a") == 1


class TestStateSnapshot:
    def test_duration(self) -> None:
        snapshot = StateSnapshot(id="battle", since=100.0)
        assert snapshot.duration(103.5) == pytest.approx(3.5)
        assert snapshot.duration(99.0) == 0.0

    def test_stable_flag(self) -> None:
        assert StateSnapshot(id="a", hits=1).stable is False
        assert StateSnapshot(id="a", hits=2).stable is True

    def test_to_dict(self) -> None:
        payload = StateSnapshot(id="a", confidence=0.91234, values={"hp": 10}).to_dict()
        assert payload["id"] == "a"
        assert payload["confidence"] == 0.9123
        assert payload["values"] == {"hp": 10}


class TestStateChange:
    def test_initial_and_stay(self) -> None:
        assert StateChange(from_state="", to_state="a", at=0.0).is_initial is True
        assert StateChange(from_state="a", to_state="a", at=0.0).is_stay is True
        change = StateChange(from_state="a", to_state="b", at=1.0)
        assert change.is_initial is False
        assert change.is_stay is False

    def test_to_dict(self) -> None:
        payload = StateChange(from_state="a", to_state="b", at=1.23456, tick=3).to_dict()
        assert payload["from"] == "a"
        assert payload["to"] == "b"
        assert payload["tick"] == 3


class TestStateStore:
    def test_initial_state_is_unknown(self) -> None:
        store = StateStore()
        assert store.current is None
        assert store.current_id == UNKNOWN_STATE
        assert store.is_(UNKNOWN_STATE)

    def test_set_initial_does_not_record_change(self) -> None:
        store = StateStore()
        store.set_initial("main_menu", now=10.0)
        assert store.current_id == "main_menu"
        assert store.change_count() == 0

    def test_advance_tick(self) -> None:
        store = StateStore()
        assert store.advance_tick() == 1
        assert store.advance_tick() == 2
        assert store.tick == 2

    def test_elapsed_in_state(self) -> None:
        store = StateStore()
        store.set_initial("a", now=100.0)
        assert store.elapsed_in_state(103.0) == pytest.approx(3.0)

    def test_elapsed_without_state(self) -> None:
        assert StateStore().elapsed_in_state(5.0) == 0.0

    def test_reset(self) -> None:
        store = StateStore()
        store.set_initial("a", now=1.0)
        store.advance_tick()
        store.reset()
        assert store.current is None
        assert store.tick == 0
        assert store.changes == []


class TestStateDefinition:
    def test_display_prefers_description(self) -> None:
        assert StateDefinition("a", description="主界面").display == "主界面"
        assert StateDefinition("a").display == "a"

    def test_has_conditions(self) -> None:
        assert StateDefinition("a").has_conditions is False
        assert StateDefinition("a", queries=(ImageQuery("x.png"),)).has_conditions is True

    def test_defaults_are_sane(self) -> None:
        definition = StateDefinition("a")
        assert definition.priority == 0
        assert definition.min_stable_frames == 1
        assert definition.terminal is False
        assert definition.timeout is None

    def test_to_dict_counts_queries(self) -> None:
        definition = StateDefinition(
            "a",
            queries=(ImageQuery("x.png"), ImageQuery("y.png")),
            exclude=(ImageQuery("z.png"),),
        )
        payload = definition.to_dict()
        assert payload["query_count"] == 2
        assert payload["exclude_count"] == 1

    def test_frozen(self) -> None:
        with pytest.raises(FrozenInstanceError):
            StateDefinition("a").priority = 5  # type: ignore[misc]


class TestStateDetectorSetup:
    def test_sorted_by_priority_desc(self) -> None:
        detector = StateDetector(
            [
                StateDefinition("low", priority=1),
                StateDefinition("high", priority=100),
                StateDefinition("mid", priority=10),
            ]
        )
        assert detector.ids == ["high", "mid", "low"]

    def test_get(self) -> None:
        definition = StateDefinition("a", description="甲")
        detector = StateDetector([definition])
        assert detector.get("a") is definition
        assert detector.get("nope") is None

    def test_snapshot_of(self) -> None:
        snapshot = StateDetector([]).snapshot_of("x", now=3.0)
        assert snapshot.id == "x"
        assert snapshot.since == 3.0
        assert snapshot.hits == 0

    def test_reset(self) -> None:
        detector = StateDetector([])
        detector._last_id = "a"
        detector._hits = 5
        detector.reset()
        assert detector._last_id == ""
        assert detector._hits == 0

    def test_confidence_averages_scores(self) -> None:
        from gamebot.types import ActionResult

        detector = StateDetector([])
        results = [
            ActionResult.success(1, score=0.8),
            ActionResult.success(2, score=1.0),
            ActionResult.success(3),  # 没有 score -> 按 1.0 计
        ]
        assert detector._confidence_of(results) == pytest.approx((0.8 + 1.0 + 1.0) / 3)
