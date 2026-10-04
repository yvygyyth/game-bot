"""状态层测试：页面树 / ROI 继承 / 跟踪层 / 黑板。"""

from __future__ import annotations

import pytest

from gamebot.atomic.query import ImageQuery
from gamebot.exceptions import StateError
from gamebot.state import (
    UNKNOWN_PAGE,
    Blackboard,
    Page,
    PageChange,
    PageKind,
    PageMatch,
    PageState,
    PageTracker,
    PageTree,
)
from gamebot.types import Region


# --------------------------------------------------------------------------- #
# 黑板
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
class TestPage:
    def test_display_prefers_name(self) -> None:
        assert Page("a", name="首页").display == "首页"
        assert Page("a").display == "a"

    def test_kind_defaults_to_page(self) -> None:
        assert Page("a").kind is PageKind.PAGE
        assert Page("a").is_overlay is False
        assert Page("b", kind=PageKind.OVERLAY).is_overlay is True

    def test_has_conditions(self) -> None:
        assert Page("a").has_conditions is False
        assert Page("a", queries=(ImageQuery("x.png"),)).has_conditions is True

    def test_defaults_are_sane(self) -> None:
        page = Page("a")
        assert page.confidence == 0.9
        assert page.min_stable_frames == 1
        assert page.priority == 0
        assert page.terminal is False
        assert page.roi is None
        assert page.timeout is None

    def test_to_dict(self) -> None:
        payload = Page("a", roi=Region(1, 2, 3, 4), queries=(ImageQuery("x.png"),)).to_dict()
        assert payload["id"] == "a"
        assert payload["roi"] == (1, 2, 3, 4)
        assert payload["query_count"] == 1
        assert payload["kind"] == "page"

    def test_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            Page("a").priority = 5  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# PageTree 结构
# --------------------------------------------------------------------------- #
def build_tree() -> PageTree:
    """首页 / 千里单骑 / 战斗（带 roi）/ 两个子页面 + 一个全局叠加层。"""
    tree = PageTree()
    tree.add(Page("home", name="首页", queries=(ImageQuery("home.png"),)))
    tree.add(Page("home/qianli", name="千里单骑", queries=(ImageQuery("q.png"),)), parent="home")
    tree.add(
        Page(
            "home/qianli/battle",
            name="战斗",
            roi=Region(1180, 620, 680, 500),
            queries=(ImageQuery("b.png"),),
        ),
        parent="home/qianli",
    )
    tree.add(
        Page("home/qianli/battle/ready", queries=(ImageQuery("r.png"),)),
        parent="home/qianli/battle",
    )
    tree.add(
        Page("home/qianli/battle/result", queries=(ImageQuery("e.png"),)),
        parent="home/qianli/battle",
    )
    tree.add(
        Page(
            "network_error",
            kind=PageKind.OVERLAY,
            priority=100,
            queries=(ImageQuery("net.png"),),
        )
    )
    return tree


class TestPageTreeStructure:
    def test_add_and_len(self) -> None:
        tree = build_tree()
        assert len(tree) == 6
        assert "home" in tree
        assert "nope" not in tree

    def test_paths_and_ancestors(self) -> None:
        tree = build_tree()
        assert tree.path_of("home/qianli/battle/result") == (
            "home",
            "home/qianli",
            "home/qianli/battle",
            "home/qianli/battle/result",
        )
        assert tree.ancestors_of("home/qianli/battle") == ("home", "home/qianli")
        assert tree.depth_of("home") == 0
        assert tree.depth_of("home/qianli/battle/result") == 3

    def test_parent_of_root_is_none(self) -> None:
        tree = build_tree()
        assert tree.parent_of("home") is None
        assert tree.parent_of("nope") is None

    def test_roots(self) -> None:
        tree = build_tree()
        assert set(tree.roots) == {"home", "network_error"}
        assert {p.id for p in tree.children_of(None)} == {"home", "network_error"}

    def test_children_sorted_by_priority_desc(self) -> None:
        tree = PageTree()
        tree.add(Page("root"))
        tree.add(Page("root/low", priority=1), parent="root")
        tree.add(Page("root/high", priority=99), parent="root")
        tree.add(Page("root/mid", priority=10), parent="root")
        assert [p.id for p in tree.children_of("root")] == ["root/high", "root/mid", "root/low"]

    def test_siblings(self) -> None:
        tree = build_tree()
        assert [p.id for p in tree.siblings_of("home/qianli/battle/ready")] == [
            "home/qianli/battle/result"
        ]
        assert len(tree.siblings_of("home/qianli/battle/ready", include_self=True)) == 2
        # 顶层页面互为兄弟（home 和 network_error）
        assert [p.id for p in tree.siblings_of("home")] == ["network_error"]

    def test_leaves(self) -> None:
        tree = build_tree()
        assert sorted(p.id for p in tree.leaves()) == [
            "home/qianli/battle/ready",
            "home/qianli/battle/result",
            "network_error",
        ]

    def test_walk_visits_everything(self) -> None:
        tree = build_tree()
        assert sorted(p.id for p in tree.walk()) == sorted(p.id for p in tree.walk("bfs"))
        assert len(list(tree.walk())) == 6

    def test_overlays(self) -> None:
        tree = build_tree()
        assert [p.id for p in tree.global_overlays()] == ["network_error"]
        assert tree.overlays_of("home") == ()

    def test_require_and_get(self) -> None:
        tree = build_tree()
        assert tree.require("home").id == "home"
        assert tree.get("nope") is None
        with pytest.raises(StateError):
            tree.require("nope")

    def test_duplicate_id_raises(self) -> None:
        tree = build_tree()
        with pytest.raises(StateError):
            tree.add(Page("home"))

    def test_missing_parent_raises(self) -> None:
        tree = PageTree()
        with pytest.raises(StateError):
            tree.add(Page("x"), parent="nope")

    def test_describe_is_a_tree_drawing(self) -> None:
        text = build_tree().describe()
        assert "首页" in text
        assert "战斗" in text
        assert "[overlay]" in text


class TestEffectiveRoi:
    def test_single_level(self) -> None:
        assert build_tree().effective_roi("home/qianli/battle") == Region(1180, 620, 680, 500)

    def test_none_along_the_chain(self) -> None:
        assert build_tree().effective_roi("home/qianli") is None

    def test_child_roi_offsets_from_parent(self) -> None:
        tree = build_tree()
        tree.add(
            Page(
                "home/qianli/battle/ready/hp",
                roi=Region(10, 20, 100, 30),
                queries=(ImageQuery("hp.png"),),
            ),
            parent="home/qianli/battle/ready",
        )
        assert tree.effective_roi("home/qianli/battle/ready/hp") == Region(1190, 640, 100, 30)

    def test_missing_layer_does_not_break_the_chain(self) -> None:
        tree = build_tree()
        assert tree.effective_roi("home/qianli/battle/ready") == Region(1180, 620, 680, 500)

    def test_passthrough_group_still_passes_roi_down(self) -> None:
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("r.png"),)))
        tree.add(Page("root/group", roi=Region(0, 0, 100, 100)), parent="root")
        tree.add(Page("root/group/a", queries=(ImageQuery("a.png"),)), parent="root/group")
        assert tree.effective_roi("root/group/a") == Region(0, 0, 100, 100)


class TestPageTreeValidate:
    def test_good_tree_passes(self) -> None:
        assert build_tree().validate() is None

    def test_empty_tree_raises(self) -> None:
        with pytest.raises(StateError):
            PageTree().validate()

    def test_condition_less_leaf_raises(self) -> None:
        """没有识别条件又是叶节点 —— 永远随父页面匹配，等于空壳。"""
        tree = PageTree()
        tree.add(Page("root"))
        tree.add(Page("root/empty"))
        with pytest.raises(StateError):
            tree.validate()

    def test_condition_less_group_is_allowed(self) -> None:
        """中间节点允许无条件：那是合法的 pass-through 分组。"""
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("r.png"),)))
        tree.add(Page("root/group"), parent="root")
        tree.add(Page("root/group/a", queries=(ImageQuery("a.png"),)), parent="root/group")
        assert tree.validate() is None

    def test_overlay_with_children_raises(self) -> None:
        tree = PageTree()
        tree.add(Page("root"))
        tree.add(
            Page("root/popup", kind=PageKind.OVERLAY, queries=(ImageQuery("p.png"),)), parent="root"
        )
        tree.add(Page("root/popup/inner", queries=(ImageQuery("i.png"),)), parent="root/popup")
        with pytest.raises(StateError):
            tree.validate()

    def test_bad_confidence_and_stable_frames_raise(self) -> None:
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("r.png"),), min_stable_frames=0))
        with pytest.raises(StateError):
            tree.validate()

    def test_empty_roi_raises(self) -> None:
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("r.png"),), roi=Region(0, 0, 0, 10)))
        with pytest.raises(StateError):
            tree.validate()

    def test_from_nested_is_a_stub(self) -> None:
        with pytest.raises(NotImplementedError):
            PageTree.from_nested({})

    def test_child_roi_outside_parent_raises(self) -> None:
        """roi 是**整棵子树**的搜索范围，伸出父页面框外就等于在别处瞎找。"""
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("r.png"),), roi=Region(0, 0, 100, 100)))
        tree.add(
            Page("root/kid", queries=(ImageQuery("k.png"),), roi=Region(50, 50, 100, 100)),
            parent="root",
        )
        with pytest.raises(StateError) as excinfo:
            tree.validate()
        assert "超出了父页面" in str(excinfo.value)

    def test_child_roi_inside_parent_passes(self) -> None:
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("r.png"),), roi=Region(0, 0, 200, 200)))
        tree.add(
            Page("root/kid", queries=(ImageQuery("k.png"),), roi=Region(20, 20, 50, 50)),
            parent="root",
        )
        assert tree.validate() is None

    def test_root_with_roi_has_no_parent_constraint(self) -> None:
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("r.png"),), roi=Region(500, 500, 100, 100)))
        assert tree.validate() is None

    def test_locate_is_a_stub(self) -> None:
        with pytest.raises(NotImplementedError):
            build_tree().locate(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# PageMatch
# --------------------------------------------------------------------------- #
class TestPageMatch:
    def test_unknown_is_default(self) -> None:
        match = PageMatch()
        assert match.id == UNKNOWN_PAGE
        assert match.is_unknown is True
        assert match.overlays == ()

    def test_path_and_depth(self) -> None:
        match = PageMatch(id="b", path=("a", "b"))
        assert match.depth == 2
        assert match.has_overlay is False

    def test_is_covers_overlays(self) -> None:
        match = PageMatch(id="battle", overlays=("popup",))
        assert match.is_("battle") is True
        assert match.is_("popup") is True
        assert match.is_("other") is False

    def test_to_dict(self) -> None:
        payload = PageMatch(id="a", path=("a",), confidence=0.91234).to_dict()
        assert payload["id"] == "a"
        assert payload["path"] == ["a"]
        assert payload["confidence"] == 0.9123


# --------------------------------------------------------------------------- #
# 跟踪层
# --------------------------------------------------------------------------- #
class TestPageTracker:
    def test_initial_state_is_unknown(self) -> None:
        tracker = PageTracker()
        assert tracker.current is None
        assert tracker.current_id == UNKNOWN_PAGE
        assert tracker.is_(UNKNOWN_PAGE) is True
        assert tracker.is_("home") is False
        assert tracker.confirmed is False

    def test_set_initial_does_not_record_change(self) -> None:
        tracker = PageTracker()
        tracker.set_initial("home", now=10.0)
        assert tracker.current_id == "home"
        assert tracker.change_count() == 0

    def test_same_page_increments_hits(self) -> None:
        tracker = PageTracker()
        tracker.update(PageMatch(id="a"), now=1.0)
        assert tracker.current.hits == 1
        assert tracker.update(PageMatch(id="a"), now=1.5) is None
        assert tracker.current.hits == 2
        assert tracker.change_count() == 0

    def test_required_hits_comes_from_the_tree(self) -> None:
        tree = PageTree()
        tree.add(Page("slow", queries=(ImageQuery("s.png"),), min_stable_frames=3))
        tracker = PageTracker(tree)
        tracker.update(PageMatch(id="slow"), now=0.0)
        assert tracker.current.required_hits == 3
        assert tracker.confirmed is False
        tracker.update(PageMatch(id="slow"), now=0.1)
        tracker.update(PageMatch(id="slow"), now=0.2)
        assert tracker.confirmed is True

    def test_page_change_records_history(self) -> None:
        tracker = PageTracker()
        tracker.update(PageMatch(id="a", path=("a",)), now=1.0)
        change = tracker.update(PageMatch(id="b", path=("b",)), now=3.0)
        assert isinstance(change, PageChange)
        assert (change.from_id, change.to_id) == ("a", "b")
        assert change.elapsed_in_previous == pytest.approx(2.0)
        assert tracker.change_count() == 1
        assert tracker.change_count("b") == 1
        assert tracker.current.hits == 1

    def test_overlay_change_is_reported_even_if_page_stays(self) -> None:
        """主页面没变但弹窗冒出来了 —— 可用动作完全变了，必须让上层知道。"""
        tracker = PageTracker()
        tracker.update(PageMatch(id="battle"), now=1.0)
        change = tracker.update(PageMatch(id="battle", overlays=("popup",)), now=1.2)
        assert change is not None
        assert change.is_stay is True
        assert change.overlay_changed is True
        assert tracker.is_("popup") is True

    def test_first_update_is_the_baseline_not_a_change(self) -> None:
        """上电时没有"从"，所以第一次观测不算切换 —— 起点看 current。"""
        tracker = PageTracker()
        assert tracker.update(PageMatch(id="a"), now=1.0) is None
        assert tracker.current_id == "a"
        assert tracker.change_count() == 0

    def test_elapsed_and_delayed(self) -> None:
        tree = PageTree()
        tree.add(Page("stuck", queries=(ImageQuery("s.png"),), timeout=5.0))
        tracker = PageTracker(tree)
        tracker.update(PageMatch(id="stuck"), now=10.0)
        assert tracker.elapsed(12.0) == pytest.approx(2.0)
        assert tracker.delayed(14.0) is False
        assert tracker.delayed(16.0) is True

    def test_delayed_is_false_without_timeout(self) -> None:
        tracker = PageTracker()
        tracker.update(PageMatch(id="a"), now=0.0)
        assert tracker.delayed(9999.0) is False

    def test_tick(self) -> None:
        tracker = PageTracker()
        assert tracker.advance_tick() == 1
        assert tracker.advance_tick() == 2
        assert tracker.tick == 2

    def test_reset(self) -> None:
        tracker = PageTracker()
        tracker.update(PageMatch(id="a"), now=1.0)
        tracker.advance_tick()
        tracker.reset()
        assert tracker.current is None
        assert tracker.tick == 0
        assert tracker.changes == []

    def test_to_dict(self) -> None:
        tracker = PageTracker()
        tracker.update(PageMatch(id="a"), now=1.0)
        payload = tracker.to_dict()
        assert payload["current"]["id"] == "a"


class TestPageState:
    def test_duration(self) -> None:
        state = PageState(id="a", since=100.0)
        assert state.duration(103.5) == pytest.approx(3.5)
        assert state.duration(99.0) == 0.0

    def test_confirmed_uses_required_hits(self) -> None:
        assert PageState(id="a", hits=1, required_hits=1).confirmed is True
        assert PageState(id="a", hits=1, required_hits=2).confirmed is False
        assert PageState(id="a", hits=2, required_hits=2).confirmed is True

    def test_is_covers_overlays(self) -> None:
        state = PageState(id="battle", overlays=("popup",))
        assert state.is_("popup") is True
        assert state.is_("battle") is True
        assert state.is_("nope") is False
