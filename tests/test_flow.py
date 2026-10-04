"""流程层测试：流程图决策 / 游标 / 脚本校验 / 运行报告。"""

from __future__ import annotations

import pytest

from gamebot.atomic.query import ImageQuery, PixelQuery
from gamebot.exceptions import ConfigError, FlowError, StateError
from gamebot.flow import (
    Decision,
    Edge,
    EdgeKind,
    EngineOptions,
    FlowEngine,
    Graph,
    GraphCursor,
    Node,
    RunReport,
    Scenario,
    StopReason,
    UnknownPolicy,
)
from gamebot.state import Page, PageMatch, PageTracker, PageTree
from gamebot.types import ActionResult, Point


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def small_graph() -> Graph:
    """a <--> b 两条无条件的边。"""
    graph = Graph(initial="a")
    graph.add_node(Node("a"))
    graph.add_node(Node("b"))
    graph.connect("a", "b", priority=10)
    graph.connect("b", "a", priority=20)
    return graph


def guarded_graph() -> Graph:
    """battle 优先试带条件的边（不满足），落到无条件的 home。"""
    graph = Graph(initial="battle")
    graph.add_node(Node("battle"))
    graph.add_node(Node("result"))
    graph.add_node(Node("home"))
    graph.connect("battle", "result", condition=ImageQuery("victory.png"), priority=30)
    graph.connect("battle", "home", priority=5)
    graph.connect("result", "home", priority=20)
    graph.connect("home", "battle", priority=10)
    return graph


# --------------------------------------------------------------------------- #
# Node / Edge
# --------------------------------------------------------------------------- #
class TestNode:
    def test_defaults(self) -> None:
        node = Node("a")
        assert node.steps == []
        assert node.page is None
        assert node.max_visits == 0
        assert node.cooldown == 0.0

    def test_of_shorthand(self) -> None:
        node = Node.of("a", page="home", max_visits=3)
        assert node.id == "a"
        assert node.page == "home"
        assert node.max_visits == 3

    def test_display_and_passive(self) -> None:
        assert Node("a", description="打怪").display == "打怪"
        assert Node("a").is_passive is True

    def test_to_dict(self) -> None:
        payload = Node("a", page="home").to_dict()
        assert payload["id"] == "a"
        assert payload["page"] == "home"
        assert payload["steps"] == 0


class TestEdge:
    def test_unconditional(self) -> None:
        edge = Edge(source="a", target="b")
        assert edge.has_condition is False
        assert edge.display == "a -> b"

    def test_label_wins(self) -> None:
        assert Edge("a", "b", label="开打").display == "开打"

    def test_to_dict(self) -> None:
        payload = Edge("a", "b", kind=EdgeKind.RECOVERY, cooldown=1.0).to_dict()
        assert payload["kind"] == "recovery"
        assert payload["has_condition"] is False
        assert payload["cooldown"] == 1.0


# --------------------------------------------------------------------------- #
# Graph 构建
# --------------------------------------------------------------------------- #
class TestGraphBuild:
    def test_add_node_sets_initial_from_first(self) -> None:
        graph = Graph()
        graph.add_node(Node("first"))
        graph.add_node(Node("second"))
        assert graph.initial == "first"

    def test_duplicate_node_raises(self) -> None:
        with pytest.raises(FlowError):
            small_graph().add_node(Node("a"))

    def test_out_edges_sorted_by_priority_desc(self) -> None:
        assert [e.target for e in guarded_graph().out_edges("battle")] == ["result", "home"]

    def test_in_edges(self) -> None:
        assert {e.source for e in small_graph().in_edges("b")} == {"a"}

    def test_node_for_page(self) -> None:
        graph = Graph()
        graph.add_node(Node("battle", page="qianli/battle"))
        graph.add_node(Node("other", page="home"))
        assert graph.node_for_page("qianli/battle").id == "battle"
        assert graph.node_for_page("nope") is None
        assert len(graph.nodes_for_page("home")) == 1

    def test_reachable_from(self) -> None:
        assert small_graph().reachable_from() == {"a", "b"}
        assert small_graph().reachable_from("b") == {"a", "b"}

    def test_reachable_from_unknown_origin(self) -> None:
        assert small_graph().reachable_from("nope") == set()

    def test_connect_shorthand(self) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.connect("a", "b", condition=ImageQuery("x.png"), label="走")
        assert graph.edges[0].label == "走"

    def test_index_of(self) -> None:
        graph = small_graph()
        assert graph.index_of(graph.edges[0]) == 0
        assert graph.index_of(Edge("x", "y")) == -1

    def test_describe(self) -> None:
        text = guarded_graph().describe()
        assert "Graph(" in text
        assert "battle" in text


# --------------------------------------------------------------------------- #
# Graph 决策
# --------------------------------------------------------------------------- #
class TestGraphEvaluate:
    def test_unconditional_edge_fires(self, ctx) -> None:
        assert small_graph().next_node("a", ctx) == "b"

    def test_no_out_edges_stays(self, ctx) -> None:
        graph = Graph(initial="only")
        graph.add_node(Node("only"))
        decision = graph.evaluate("only", ctx)
        assert decision.target is None
        assert decision.stayed is True
        assert "没有出边" in decision.explain()

    def test_query_condition_hit(self, ctx) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.connect(
            "a", "b", condition=PixelQuery(Point(0, 0), expected_color=(0, 0, 0), tolerance=0)
        )
        assert graph.next_node("a", ctx) == "b"

    def test_query_condition_miss_falls_through(self, ctx) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.add_node(Node("c"))
        graph.connect("a", "b", condition=ImageQuery("nope.png"), priority=50)
        graph.connect("a", "c", priority=10)
        assert graph.next_node("a", ctx) == "c"

    def test_callable_condition(self, ctx) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.connect("a", "b", condition=lambda _ctx: True)
        assert graph.next_node("a", ctx) == "b"

    def test_callable_returning_action_result(self, ctx) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.connect("a", "b", condition=lambda _ctx: ActionResult.not_found("没满足"))
        assert graph.next_node("a", ctx) is None

    def test_condition_exception_does_not_break_the_run(self, ctx) -> None:
        """条件写错了不该炸掉整轮，但必须能从 Decision.errors 里看到。"""

        def boom(_ctx):
            raise RuntimeError("条件写错了")

        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.add_node(Node("c"))
        graph.connect("a", "b", condition=boom, priority=50)
        graph.connect("a", "c", priority=10)

        decision = graph.evaluate("a", ctx)
        assert decision.target == "c"
        assert len(decision.errors) == 1
        assert "条件写错了" in decision.errors[0]

    def test_invalid_condition_object_is_reported(self, ctx) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.connect("a", "b", condition=42)
        decision = graph.evaluate("a", ctx)
        assert decision.target is None
        assert len(decision.errors) == 1

    def test_attempts_record_every_edge(self, ctx) -> None:
        decision = guarded_graph().evaluate("battle", ctx)
        assert decision.target == "home"
        assert [a.edge.target for a in decision.attempts] == ["result", "home"]
        assert decision.attempts[0].accepted is False
        assert decision.attempts[1].accepted is True

    def test_decision_moved_property(self, ctx) -> None:
        decision = guarded_graph().evaluate("battle", ctx)
        assert decision.moved is True
        assert decision.explain() == "battle -> home"


# --------------------------------------------------------------------------- #
# Graph 校验
# --------------------------------------------------------------------------- #
class TestGraphValidate:
    def test_good_graph_passes(self) -> None:
        assert small_graph().validate() is None

    def test_empty_graph_raises(self) -> None:
        with pytest.raises(FlowError):
            Graph().validate()

    def test_missing_target_raises(self) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.connect("a", "missing")
        with pytest.raises(FlowError) as excinfo:
            graph.validate()
        assert "target 不存在" in str(excinfo.value)

    def test_missing_source_raises(self) -> None:
        graph = small_graph()
        graph.connect("ghost", "a")
        with pytest.raises(FlowError) as excinfo:
            graph.validate()
        assert "source 不存在" in str(excinfo.value)

    def test_orphan_node_raises(self) -> None:
        graph = small_graph()
        graph.add_node(Node("island"))
        with pytest.raises(FlowError) as excinfo:
            graph.validate()
        assert "走不到" in str(excinfo.value)

    def test_negative_cooldown_raises(self) -> None:
        graph = small_graph()
        graph.edges[0] = Edge("a", "b", cooldown=-1.0)
        with pytest.raises(FlowError):
            graph.validate()

    def test_on_timeout_must_exist(self) -> None:
        graph = small_graph()
        graph.nodes["a"].on_timeout = "ghost"
        with pytest.raises(FlowError):
            graph.validate()

    def test_terminal_edge_to_node_with_out_edges_raises(self) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("end"))
        graph.add_node(Node("after"))
        graph.connect("a", "end", kind=EdgeKind.TERMINAL)
        graph.connect("end", "after")
        with pytest.raises(FlowError) as excinfo:
            graph.validate()
        assert "终态" in str(excinfo.value)

    def test_all_problems_are_reported_together(self) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("island"))
        graph.connect("a", "missing")
        with pytest.raises(FlowError) as excinfo:
            graph.validate()
        assert len(str(excinfo.value).splitlines()) >= 3


# --------------------------------------------------------------------------- #
# GraphCursor
# --------------------------------------------------------------------------- #
class TestGraphCursor:
    def test_starts_at_initial(self) -> None:
        cursor = GraphCursor(small_graph())
        assert cursor.current == "a"
        assert cursor.history == ["a"]

    def test_advance_moves_and_counts(self) -> None:
        cursor = GraphCursor(small_graph())
        assert cursor.advance("b", now=1.0) is True
        assert cursor.current == "b"
        assert cursor.visits_of("b") == 1
        assert cursor.history == ["a", "b"]

    def test_advance_to_same_node_is_noop(self) -> None:
        cursor = GraphCursor(small_graph())
        assert cursor.advance("a") is False
        assert cursor.history == ["a"]

    def test_advance_to_unknown_node_raises(self) -> None:
        cursor = GraphCursor(small_graph())
        with pytest.raises(FlowError):
            cursor.advance("ghost")

    def test_next_returns_target(self, ctx) -> None:
        assert GraphCursor(small_graph()).next(ctx) == "b"

    def test_step_moves(self, ctx) -> None:
        cursor = GraphCursor(small_graph())
        assert cursor.step(ctx) == "b"
        assert cursor.current == "b"

    def test_cooldown_blocks_then_allows(self, ctx) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.connect("a", "b", cooldown=5.0)
        cursor = GraphCursor(graph)
        cursor.advance("b", now=100.0)
        cursor.current = "a"
        blocked = cursor.evaluate(ctx, now=101.0)
        assert blocked.target is None
        assert "冷却" in blocked.attempts[0].reason
        assert cursor.evaluate(ctx, now=106.0).target == "b"

    def test_max_times_exhausts(self, ctx) -> None:
        graph = Graph(initial="a")
        graph.add_node(Node("a"))
        graph.add_node(Node("b"))
        graph.connect("a", "b", max_times=2)
        cursor = GraphCursor(graph)
        for stamp in (1.0, 2.0):
            cursor.advance("b", now=stamp)
            cursor.current = "a"
        decision = cursor.evaluate(ctx, now=3.0)
        assert decision.target is None
        assert "最大次数" in decision.attempts[0].reason

    def test_should_run_respects_max_visits(self, ctx) -> None:
        graph = Graph(initial="x")
        graph.add_node(Node("x", max_visits=1))
        cursor = GraphCursor(graph)
        assert cursor.should_run(ctx) == (True, "")
        cursor.visits["x"] = 1
        ok, why = cursor.should_run(ctx)
        assert ok is False
        assert "最大访问次数" in why

    def test_should_run_page_guard(self, ctx) -> None:
        """实际页面 ≠ 节点期望页面时拒绝执行 —— 防止在错误页面上乱点。"""
        tree = PageTree()
        tree.add(Page("home", queries=(ImageQuery("h.png"),)))
        tree.add(Page("battle", queries=(ImageQuery("b.png"),)))
        ctx.pages = PageTracker(tree)

        graph = Graph(initial="battle")
        graph.add_node(Node("battle", page="battle"))
        cursor = GraphCursor(graph)

        ctx.pages.update(PageMatch(id="home", path=("home",)), now=1.0)
        ok, why = cursor.should_run(ctx)
        assert ok is False
        assert "期望页面" in why

        ctx.pages.update(PageMatch(id="battle", path=("battle",)), now=2.0)
        assert cursor.should_run(ctx) == (True, "")

    def test_should_run_without_page_declaration(self, ctx) -> None:
        graph = Graph(initial="x")
        graph.add_node(Node("x"))
        assert GraphCursor(graph).should_run(ctx) == (True, "")

    def test_should_run_unknown_node(self, ctx) -> None:
        cursor = GraphCursor(small_graph())
        cursor.current = "ghost"
        ok, why = cursor.should_run(ctx)
        assert ok is False
        assert "不存在" in why

    def test_reset(self) -> None:
        cursor = GraphCursor(small_graph())
        cursor.advance("b", now=1.0)
        cursor.reset()
        assert cursor.current == "a"
        assert cursor.visits == {}
        assert cursor.history == ["a"]

    def test_edge_stats_tracks_counts(self) -> None:
        cursor = GraphCursor(small_graph())
        cursor.advance("b", now=5.0)
        assert cursor.stats.count(0) == 1
        assert cursor.stats.since_last(0, 7.0) == pytest.approx(2.0)
        cursor.reset()
        assert cursor.stats.count(0) == 0

    def test_to_dict(self) -> None:
        payload = GraphCursor(small_graph()).to_dict()
        assert payload["current"] == "a"


# --------------------------------------------------------------------------- #
# Scenario
# --------------------------------------------------------------------------- #
def build_scenario() -> Scenario:
    tree = PageTree()
    tree.add(Page("home", queries=(ImageQuery("home.png"),)))
    tree.add(Page("battle", queries=(ImageQuery("battle.png"),)))
    tree.add(Page("closed", queries=(ImageQuery("closed.png"),), terminal=True))

    graph = Graph(initial="home")
    graph.add_node(Node("home", page="home"))
    graph.add_node(Node("battle", page="battle"))
    graph.add_node(Node("closed", page="closed"))
    graph.connect("home", "battle", priority=10)
    graph.connect("battle", "home", priority=5)
    graph.connect("battle", "closed", priority=1, kind=EdgeKind.TERMINAL)

    return Scenario(
        name="t",
        tree=tree,
        graph=graph,
        options=EngineOptions(tick_interval=0.5, stop_pages=("closed",)),
    )


class TestScenario:
    def test_valid_scenario_passes(self) -> None:
        assert build_scenario().validate() is None

    def test_node_pointing_at_missing_page_raises(self) -> None:
        scenario = build_scenario()
        scenario.graph.nodes["battle"].page = "写错了"
        with pytest.raises(ConfigError) as excinfo:
            scenario.validate()
        assert "不存在的页面" in str(excinfo.value)

    def test_recovery_node_must_exist(self) -> None:
        scenario = build_scenario()
        scenario.options.recovery_node = "ghost"
        with pytest.raises(ConfigError):
            scenario.validate()

    def test_stop_pages_must_exist(self) -> None:
        scenario = build_scenario()
        scenario.options.stop_pages = ("ghost",)
        with pytest.raises(ConfigError):
            scenario.validate()

    def test_bad_tick_interval_raises(self) -> None:
        scenario = build_scenario()
        scenario.options.tick_interval = 0
        with pytest.raises(ConfigError):
            scenario.validate()

    def test_tree_problems_propagate(self) -> None:
        scenario = build_scenario()
        scenario.tree.add(Page("home/empty"), parent="home")
        with pytest.raises(StateError):
            scenario.validate()

    def test_unclaimed_pages(self) -> None:
        scenario = build_scenario()
        scenario.tree.add(Page("nobody", queries=(ImageQuery("n.png"),)))
        assert scenario.unclaimed_pages() == ("nobody",)

    def test_describe_and_to_dict(self) -> None:
        scenario = build_scenario()
        assert "Scenario" in scenario.describe()
        assert scenario.to_dict()["name"] == "t"

    def test_repr(self) -> None:
        assert "t" in repr(build_scenario())


# --------------------------------------------------------------------------- #
# EngineOptions / RunReport / StopReason
# --------------------------------------------------------------------------- #
class TestEngineOptions:
    def test_defaults(self) -> None:
        options = EngineOptions()
        assert options.tick_interval == 0.2
        assert options.on_unknown is UnknownPolicy.WAIT
        assert options.require_confirmed is True
        assert options.validate() == []

    def test_validate_catches_problems(self) -> None:
        assert any("tick_interval" in p for p in EngineOptions(tick_interval=0).validate())
        assert any("max_runtime" in p for p in EngineOptions(max_runtime=0).validate())
        assert any("max_ticks" in p for p in EngineOptions(max_ticks=-1).validate())
        assert any("unknown_grace" in p for p in EngineOptions(unknown_grace=-1).validate())


class TestStopReason:
    def test_values(self) -> None:
        assert StopReason.USER.value == "user"
        assert StopReason.STOP_PAGE.value == "stop_page"


class TestRunReport:
    def test_duration_and_ok(self) -> None:
        report = RunReport(scenario="t", started_at=100.0, ended_at=112.5)
        assert report.duration == pytest.approx(12.5)
        report.stop_reason = StopReason.STOP_PAGE
        assert report.ok is True
        report.stop_reason = StopReason.ERROR
        assert report.ok is False

    def test_user_stop_counts_as_ok(self) -> None:
        assert RunReport(stop_reason=StopReason.USER).ok is True

    def test_failed_steps(self) -> None:
        from gamebot.execution.executor import StepOutcome

        report = RunReport()
        report.outcomes = [
            StepOutcome("a", ActionResult.success(1)),
            StepOutcome("b", ActionResult.not_found("没找到")),
        ]
        assert report.step_count == 2
        assert [o.step for o in report.failed_steps] == ["b"]

    def test_summary_mentions_key_facts(self) -> None:
        report = RunReport(
            scenario="demo",
            started_at=0.0,
            ended_at=65.0,
            ticks=10,
            initial_page="home",
            final_page="closed",
            final_node="closed",
        )
        report.stop_reason = StopReason.STOP_PAGE
        summary = report.summary()
        assert "demo" in summary
        assert "stop_page" in summary
        assert "1m05s" in summary

    def test_to_dict_keeps_decisions_and_changes(self) -> None:
        payload = RunReport(scenario="x").to_dict()
        assert payload["scenario"] == "x"
        assert payload["decisions"] == []
        assert payload["changes"] == []


# --------------------------------------------------------------------------- #
# 引擎骨架
# --------------------------------------------------------------------------- #
class TestFlowEngine:
    def test_starts_from_initial_node(self, ctx) -> None:
        engine = FlowEngine(build_scenario(), ctx)
        assert engine.cursor.current == "home"
        assert engine.running is True

    def test_uses_ctx_tracker_by_default(self, ctx) -> None:
        engine = FlowEngine(build_scenario(), ctx)
        assert engine.tracker is ctx.pages

    def test_stop_is_idempotent(self, ctx) -> None:
        engine = FlowEngine(build_scenario(), ctx)
        engine.stop(StopReason.USER, "第一次")
        engine.stop(StopReason.ERROR, "第二次")
        assert engine.running is False
        assert engine._stop_message == "第一次"

    def test_tick_is_a_stub(self, ctx) -> None:
        engine = FlowEngine(build_scenario(), ctx)
        with pytest.raises(NotImplementedError):
            engine.tick()

    def test_run_validates_before_looping(self, ctx) -> None:
        scenario = build_scenario()
        scenario.options.tick_interval = -1
        with pytest.raises(ConfigError):
            FlowEngine(scenario, ctx).run()

    def test_tick_interval_respects_node_cooldown(self, ctx) -> None:
        scenario = build_scenario()
        scenario.graph.nodes["home"].cooldown = 2.0
        engine = FlowEngine(scenario, ctx)
        assert engine._tick_interval() == 2.0

    def test_repr(self, ctx) -> None:
        assert "home" in repr(FlowEngine(build_scenario(), ctx))

    def test_align_to_page_without_claimed_node(self, ctx) -> None:
        engine = FlowEngine(build_scenario(), ctx)
        aligned, why = engine._align_to_page("nobody", now=0.0)
        assert aligned is False
        assert "没有节点认领" in why

    def test_align_to_page_moves_cursor(self, ctx) -> None:
        engine = FlowEngine(build_scenario(), ctx)
        aligned, why = engine._align_to_page("battle", now=0.0)
        assert aligned is True
        assert "对齐到节点" in why
        assert engine.cursor.current == "battle"

    def test_check_terminal(self, ctx) -> None:
        engine = FlowEngine(build_scenario(), ctx)
        assert engine._check_terminal("closed", now=0.0) is True
        assert engine.running is False


class TestDecision:
    def test_stayed_decision(self) -> None:
        decision = Decision(current="a")
        assert decision.stayed is True
        assert decision.moved is False
        assert "原地不动" in decision.explain()

    def test_to_dict(self) -> None:
        assert Decision(current="a", target="b").to_dict()["target"] == "b"
