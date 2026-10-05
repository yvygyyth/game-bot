"""状态层测试：页面树 / ROI 继承 / 跟踪层 / 黑板。"""

from __future__ import annotations

import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.query import ImageQuery
from gamebot.atomic.session import BaseSession
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
from gamebot.types import Point, Region


# --------------------------------------------------------------------------- #
# 定位用的小装置
# --------------------------------------------------------------------------- #
def _frame(matcher):
    """造一帧假画面（内存后端，不碰真实截图）。

    ``locate`` / ``recover`` 只依赖帧上的查询方法，所以这里不需要真图。
    """
    session = BaseSession(build_fake_backends(size=(640, 360)), matcher=matcher)
    return session.capture()


class _Boom:
    """一个永远抛异常的"查询"：用来验"出错"和"未命中"没有被混为一谈。"""

    def run(self, frame):
        raise RuntimeError("故意炸的查询")


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

    def test_locate_is_implemented(self, matcher) -> None:
        """定位不再抛"未实现"——它现在会如实回答"认不出来"。

        认不出来是**有效结果**，所以这里断言的是返回值而不是异常。
        """
        match = build_tree().locate(_frame(matcher)).value
        assert match is not None
        assert match.is_unknown is True


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


# --------------------------------------------------------------------------- #
# 单帧定位（快路径）
# --------------------------------------------------------------------------- #
class TestPageTreeLocate:
    """``PageTree.locate``：自顶向下找最深命中者 + 叠加层。

    一律用 ``FakeMatcher``（conftest 提供的视觉替身），不碰真实截图。
    """

    def test_deepest_match_wins(self, matcher) -> None:
        matcher.matches = {"r.png": (Point(1, 1), 0.99), "k.png": (Point(2, 2), 0.99)}
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("r.png"),)))
        tree.add(Page("root/kid", queries=(ImageQuery("k.png"),)), parent="root")

        match = tree.locate(_frame(matcher)).value
        assert match.id == "root/kid"
        assert match.path == ("root", "root/kid")

    def test_unknown_is_a_successful_result(self, matcher) -> None:
        """认不出来必须是 ``success(UNKNOWN_PAGE)``，不能是 error。"""
        matcher.matches = {}
        result = build_tree().locate(_frame(matcher))
        assert result.ok is True
        assert result.value.is_unknown is True
        assert result.value.attempts, "认不出来也要留下尝试痕迹"

    def test_exclude_vetoes(self, matcher) -> None:
        """exclude 命中就不进这一页 —— 处理"子页面和父页面长得太像"。"""
        matcher.matches = {"b.png": (Point(1, 1), 0.99), "win.png": (Point(2, 2), 0.99)}
        tree = PageTree()
        tree.add(Page("battle", queries=(ImageQuery("b.png"),)))
        tree.add(
            Page(
                "battle/result",
                queries=(ImageQuery("b.png"),),
                exclude=(ImageQuery("win.png"),),
            ),
            parent="battle",
        )
        assert tree.locate(_frame(matcher)).value.id == "battle"

    def test_priority_decides_between_siblings(self, matcher) -> None:
        matcher.matches = {"a.png": (Point(1, 1), 0.99), "b.png": (Point(2, 2), 0.99)}
        tree = PageTree()
        tree.add(Page("root", queries=(ImageQuery("a.png"),)))
        tree.add(Page("root/low", priority=1, queries=(ImageQuery("b.png"),)), parent="root")
        tree.add(Page("root/high", priority=50, queries=(ImageQuery("b.png"),)), parent="root")
        assert tree.locate(_frame(matcher)).value.id == "root/high"

    def test_global_overlay_does_not_replace_the_state(self, matcher) -> None:
        """全局弹窗是**叠加**在主状态上的一层，不是"当前状态"。"""
        matcher.matches = {"home.png": (Point(1, 1), 0.99), "err.png": (Point(2, 2), 0.99)}
        tree = PageTree()
        tree.add(Page("home", queries=(ImageQuery("home.png"),)))
        tree.add(
            Page(
                "network_error",
                kind=PageKind.OVERLAY,
                priority=100,
                queries=(ImageQuery("err.png"),),
            )
        )
        match = tree.locate(_frame(matcher)).value
        assert match.id == "home"
        assert match.overlays == ("network_error",)
        assert match.is_("network_error") is True

    def test_state_level_overlay_is_collected(self, matcher) -> None:
        matcher.matches = {"b.png": (Point(1, 1), 0.99), "pop.png": (Point(2, 2), 0.99)}
        tree = PageTree()
        tree.add(Page("battle", queries=(ImageQuery("b.png"),)))
        tree.add(
            Page("battle/popup", kind=PageKind.OVERLAY, queries=(ImageQuery("pop.png"),)),
            parent="battle",
        )
        match = tree.locate(_frame(matcher)).value
        assert match.id == "battle"
        assert match.overlays == ("battle/popup",)

    def test_expected_fast_path(self, matcher) -> None:
        """``expected`` 命中时只探它 —— 这就是"正常一轮不查树"的实现。"""
        matcher.matches = {"home.png": (Point(1, 1), 0.99), "other.png": (Point(2, 2), 0.99)}
        tree = PageTree()
        tree.add(Page("home", queries=(ImageQuery("home.png"),)))
        tree.add(Page("other", priority=50, queries=(ImageQuery("other.png"),)))
        matcher.calls.clear()
        match = tree.locate(_frame(matcher), expected="home").value
        assert match.id == "home"
        assert [t for t, _ in matcher.calls] == ["home.png"]

    def test_expected_failure_falls_back_to_full_search(self, matcher) -> None:
        matcher.matches = {"other.png": (Point(2, 2), 0.99)}
        tree = PageTree()
        tree.add(Page("home", queries=(ImageQuery("home.png"),)))
        tree.add(Page("other", queries=(ImageQuery("other.png"),)))
        assert tree.locate(_frame(matcher), expected="home").value.id == "other"

    def test_hint_only_saves_work_never_decides(self, matcher) -> None:
        """hint 只影响尝试顺序：给一个**完全错**的 hint 也要能走对。"""
        matcher.matches = {"b.png": (Point(1, 1), 0.99)}
        tree = PageTree()
        tree.add(Page("home", queries=(ImageQuery("home.png"),)))
        tree.add(Page("battle", queries=(ImageQuery("b.png"),)))
        assert tree.locate(_frame(matcher)).value.id == "battle"
        assert tree.locate(_frame(matcher), hint="home").value.id == "battle"

    def test_hint_prunes_other_branches(self, matcher) -> None:
        """hint 命中时，排在前面的无关分支一次都不试。"""
        matcher.matches = {"home.png": (Point(1, 1), 0.99)}
        tree = PageTree()
        tree.add(Page("ui", priority=100, queries=(ImageQuery("ui.png"),)))
        tree.add(Page("home", priority=1, queries=(ImageQuery("home.png"),)))

        def probes(hint: str | None) -> list[str]:
            # 每次都用**新帧**：Frame 会缓存查询结果（同一帧上同一个模板只匹配
            # 一次），复用同一帧会让两次 locate 的匹配次数不可比。
            matcher.calls.clear()
            tree.locate(_frame(matcher), hint)
            return [template for template, _ in matcher.calls]

        assert probes("home") == ["home.png"]
        assert probes(None) == ["ui.png", "home.png"]

    def test_roi_and_query_region_are_intersected(self, matcher) -> None:
        """页面 roi 与查询 region 求交：两边都是作者显式写的，谁也不该覆盖谁。"""
        matcher.matches = {"hit.png": (Point(1, 1), 0.99)}
        tree = PageTree()
        tree.add(
            Page(
                "page",
                roi=Region(0, 0, 100, 100),
                queries=(ImageQuery("hit.png", region=Region(50, 50, 100, 100)),),
            )
        )
        assert tree.locate(_frame(matcher)).value.id == "page"
        assert matcher.calls[-1][1] == Region(50, 50, 50, 50)

    def test_empty_intersection_is_an_error(self, matcher) -> None:
        """两者完全不重叠 = 这一页永远认不出来，必须报错而不是静默未命中。"""
        matcher.matches = {"hit.png": (Point(1, 1), 0.99)}
        tree = PageTree()
        tree.add(
            Page(
                "page",
                roi=Region(0, 0, 10, 10),
                queries=(ImageQuery("hit.png", region=Region(500, 500, 10, 10)),),
            )
        )
        result = tree.locate(_frame(matcher))
        assert result.ok is True, "单帧定位不该因为一页配置坏掉就整体失败"
        assert result.value.is_unknown is True
        assert any("自相矛盾" in a.reason for a in result.value.attempts)

    def test_page_confidence_overrides_query_threshold(self, matcher) -> None:
        """页面显式写了 confidence 才覆盖查询自己的阈值。"""
        matcher.matches = {"hit.png": (Point(1, 1), 0.7)}
        tree = PageTree()
        tree.add(Page("strict", confidence=0.95, queries=(ImageQuery("hit.png", confidence=0.5),)))
        assert tree.locate(_frame(matcher)).value.is_unknown is True

        tree2 = PageTree()
        tree2.add(Page("loose", confidence=0.6, queries=(ImageQuery("hit.png", confidence=0.5),)))
        assert tree2.locate(_frame(matcher)).value.id == "loose"

    def test_query_threshold_survives_default_page_confidence(self, matcher) -> None:
        """页面没写 confidence 时，查询自己的阈值必须原样生效。

        名将杀首页给的是 0.55 —— 被页面默认的 0.9 覆盖掉的话，
        它在悬浮态（实测 0.647）会直接失配。
        """
        matcher.matches = {"hit.png": (Point(1, 1), 0.7)}
        tree = PageTree()
        tree.add(Page("page", queries=(ImageQuery("hit.png", confidence=0.55),)))
        assert tree.locate(_frame(matcher)).value.id == "page"

    def test_matcher_error_is_not_treated_as_miss(self, matcher) -> None:
        """查询求值出错按未命中处理，但痕迹里要说明是"出错"而不是"没看到"。"""
        tree = PageTree()
        tree.add(Page("page", queries=(_Boom(),)))
        match = tree.locate(_frame(matcher)).value
        assert match.is_unknown is True
        assert "求值出错" in match.attempts[0].reason
        assert "故意炸的查询" in match.attempts[0].reason

    def test_values_carry_hit_points(self, matcher) -> None:
        matcher.matches = {"home.png": (Point(11, 22), 0.99)}
        match = build_tree().locate(_frame(matcher)).value
        assert match.values["home.png"] == Point(11, 22)

    def test_frame_id_and_time_are_recorded(self, matcher) -> None:
        matcher.matches = {"home.png": (Point(1, 1), 0.99)}
        frame = _frame(matcher)
        match = build_tree().locate(frame, now=12.5).value
        assert match.frame_id == frame.frame_id
        assert match.observed_at == 12.5


# --------------------------------------------------------------------------- #
# 分类节点（kind: group）
# --------------------------------------------------------------------------- #
class TestGroupStates:
    """父节点只是分类：**自己不记录信息，也就不参与匹配**。

    这一条是"进下一层之后上一层特征消失"那个坑的根治办法：
    要求父节点成立会让「首页 → 竞技场 → 战斗」这种链条一进下一层就全部失效。
    """

    def build(self) -> PageTree:
        tree = PageTree()
        tree.add(Page("home", kind=PageKind.GROUP))
        tree.add(Page("home/lobby", queries=(ImageQuery("lobby.png"),)), parent="home")
        tree.add(Page("home/jingji", queries=(ImageQuery("t.png"),)), parent="home")
        return tree

    def test_group_never_matches(self, matcher) -> None:
        matcher.matches = {}
        result = self.build().match(_frame(matcher), "home")
        assert result.ok is False
        assert "分类节点" in result.message

    def test_group_is_transparent(self, matcher) -> None:
        """穿过分类节点找到真正的状态 —— 不需要父节点的特征也成立。"""
        matcher.matches = {"t.png": (Point(1, 1), 0.99)}
        match = self.build().locate(_frame(matcher)).value
        assert match.id == "home/jingji"
        assert match.path == ("home", "home/jingji")

    def test_group_never_appears_in_the_result(self, matcher) -> None:
        matcher.matches = {}
        assert self.build().locate(_frame(matcher)).value.id == UNKNOWN_PAGE

    def test_group_is_skipped_when_probing_hint(self, matcher) -> None:
        matcher.matches = {"lobby.png": (Point(1, 1), 0.99)}
        tree = self.build()
        assert tree.locate(_frame(matcher), hint="home").value.id == "home/lobby"

    def test_group_with_queries_is_rejected(self) -> None:
        tree = PageTree()
        tree.add(Page("folder", kind=PageKind.GROUP, queries=(ImageQuery("x.png"),)))
        tree.add(Page("folder/kid", queries=(ImageQuery("k.png"),)), parent="folder")
        with pytest.raises(StateError) as excinfo:
            tree.validate()
        assert "不该写 queries" in str(excinfo.value)

    def test_group_without_children_is_rejected(self) -> None:
        tree = PageTree()
        tree.add(Page("folder", kind=PageKind.GROUP))
        with pytest.raises(StateError) as excinfo:
            tree.validate()
        assert "没有任何子页面" in str(excinfo.value)

    def test_state_leaf_without_queries_is_rejected(self) -> None:
        """状态节点没写 queries = 永远不会被认出来，必须报错。"""
        tree = PageTree()
        tree.add(Page("page"))
        with pytest.raises(StateError) as excinfo:
            tree.validate()
        assert "没有识别条件" in str(excinfo.value)

    def test_confidence_explicit_flag(self) -> None:
        assert Page("a", queries=(ImageQuery("x"),)).confidence_explicit is False
        assert Page("b", confidence=0.8, queries=(ImageQuery("x"),)).confidence_explicit is True


# --------------------------------------------------------------------------- #
# 慢路径：末梢优先 + 逐步扩散
# --------------------------------------------------------------------------- #
class TestPageTreeRecover:
    """``recover``：从最近的末梢开始逐步扩大范围。

    用途只有一个 —— 意外时的重定位。正常一轮用不上它。
    """

    def build(self) -> PageTree:
        tree = PageTree()
        tree.add(Page("home", kind=PageKind.GROUP))
        tree.add(Page("home/lobby", queries=(ImageQuery("lobby.png"),)), parent="home")
        tree.add(Page("home/shop", queries=(ImageQuery("shop.png"),)), parent="home")
        tree.add(Page("battle", kind=PageKind.GROUP))
        tree.add(Page("battle/fight", queries=(ImageQuery("fight.png"),)), parent="battle")
        return tree

    def test_near_itself_is_tried_first(self, matcher) -> None:
        matcher.matches = {"lobby.png": (Point(1, 1), 0.99)}
        match = self.build().recover(_frame(matcher), near="home/lobby").value
        assert match.id == "home/lobby"
        assert [a.id for a in match.attempts] == ["home/lobby"]

    def test_siblings_of_near_come_next(self, matcher) -> None:
        """最近的兄弟优先于远处分支。"""
        matcher.matches = {"shop.png": (Point(1, 1), 0.99)}
        match = self.build().recover(_frame(matcher), near="home/lobby").value
        assert match.id == "home/shop"

    def test_expands_to_the_whole_tree(self, matcher) -> None:
        """近处都不成立时扩到别处 —— 这正是"意外"的救回能力。"""
        matcher.matches = {"fight.png": (Point(1, 1), 0.99)}
        match = self.build().recover(_frame(matcher), near="home/lobby").value
        assert match.id == "battle/fight"

    def test_attempts_record_each_ring(self, matcher) -> None:
        """每一圈试过谁都要留痕 —— "为什么最后认成了这个"只能靠它。"""
        matcher.matches = {"fight.png": (Point(1, 1), 0.99)}
        match = self.build().recover(_frame(matcher), near="home/lobby").value
        tried = [a.id for a in match.attempts]
        assert tried[0] == "home/lobby"
        assert "battle/fight" in tried
        assert "home/shop" in tried

    def test_cheaper_candidates_are_tried_first(self, matcher) -> None:
        """同一圈里 ROI 小的先试（"看得少"更快也更不容易误判）。"""
        tree = PageTree()
        tree.add(Page("root", kind=PageKind.GROUP))
        tree.add(
            Page("root/big", roi=Region(0, 0, 600, 600), queries=(ImageQuery("big.png"),)),
            parent="root",
        )
        tree.add(
            Page("root/small", roi=Region(0, 0, 20, 20), queries=(ImageQuery("small.png"),)),
            parent="root",
        )
        matcher.matches = {"big.png": (Point(1, 1), 0.99), "small.png": (Point(2, 2), 0.99)}
        match = tree.recover(_frame(matcher)).value
        assert next(a.id for a in match.attempts) == "root/small"

    def test_unknown_when_nothing_matches(self, matcher) -> None:
        matcher.matches = {}
        match = self.build().recover(_frame(matcher), near="home/lobby").value
        assert match.is_unknown is True

    def test_unknown_near_falls_back_to_full_search(self, matcher) -> None:
        matcher.matches = {"fight.png": (Point(1, 1), 0.99)}
        match = self.build().recover(_frame(matcher), near="不存在的状态").value
        assert match.id == "battle/fight"

    def test_group_is_never_returned(self, matcher) -> None:
        """分类节点永远不会成为"真实状态" —— 把它报出去会得到一个
        既认不出、又没节点认领的假状态。"""
        matcher.matches = {}
        match = self.build().recover(_frame(matcher)).value
        assert match.is_unknown is True

    def test_overlay_fallback(self, matcher) -> None:
        """主状态全认不出来，但弹窗还在 —— 至少要把弹窗报出来。"""
        tree = self.build()
        tree.add(
            Page("net", kind=PageKind.OVERLAY, queries=(ImageQuery("net.png"),))
        )
        matcher.matches = {"net.png": (Point(1, 1), 0.99)}
        match = tree.recover(_frame(matcher), near="home/lobby").value
        assert match.is_unknown is True
        assert match.overlays == ("net",)
