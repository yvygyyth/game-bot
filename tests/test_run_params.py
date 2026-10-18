"""运行参数（入参）与运行期状态的清理。

参数和黑板是**两件不同的事**，这个文件把界线钉住：

* **参数**：进去之前定好、跑的过程中**不变**（这次运行的目标、开关、阈值）；
* **黑板**：跑的过程中**写**的（连续失败计数、上次读到的体力）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.query import ImageQuery
from gamebot.atomic.session import BaseSession
from gamebot.bootstrap import build_engine
from gamebot.config.schema import RunPaths
from gamebot.context import RunContext
from gamebot.execution.executor import Executor
from gamebot.flow import NodeBindings
from gamebot.flow.graph import Graph, Node
from gamebot.flow.scenario import Scenario
from gamebot.state.page import Page, PageTree
from gamebot.types import ActionResult, Point

from .conftest import FakeMatcher, FakeReader


def _scenario(step, *, max_ticks: int = 1) -> Scenario:
    tree = PageTree()
    tree.add(Page("home", queries=(ImageQuery("home.png"),)))
    graph = Graph(initial="home")
    graph.add_node(Node("home", steps=[step]))
    scenario = Scenario(
        name="params",
        tree=tree,
        graph=graph,
        bindings=NodeBindings.of([("home", "home")]),
    )
    scenario.options.tick_interval = 0.001
    scenario.options.max_ticks = max_ticks
    scenario.validate()
    return scenario


def _ctx(scenario, *, params=None, root: Path | None = None):
    session = BaseSession(
        build_fake_backends(size=(640, 360)),
        matcher=FakeMatcher(matches={"home.png": (Point(1, 1), 0.99)}),
        reader=FakeReader(),
    )
    ctx = RunContext(
        session,
        name="params",
        paths=RunPaths.under(root or Path(".")),
        tree=scenario.tree,
        frame_ttl=0.5,
        params=params,
    )
    ctx.executor = Executor(
        ctx,
        dry_run=False,
        save_frames_on_error=bool(
            getattr(scenario.options, "save_frames_on_error", False)
        ),
    )
    return ctx


class TestRunParams:
    def test_step_reads_a_param(self):
        seen: list[object] = []

        def read_param(ctx):
            seen.append(ctx.param("farm.rounds"))
            return ActionResult.success()

        scenario = _scenario(read_param)
        ctx = _ctx(scenario, params={"farm.rounds": 5})
        engine = build_engine(ctx, scenario)
        try:
            engine.run()
        finally:
            ctx.close()

        assert seen == [5]

    def test_default_applies_when_param_absent(self):
        seen: list[object] = []

        def read_default(ctx):
            seen.append(ctx.param("farm.rounds", 3))
            return ActionResult.success()

        scenario = _scenario(read_default)
        ctx = _ctx(scenario)
        engine = build_engine(ctx, scenario)
        try:
            engine.run()
        finally:
            ctx.close()

        assert seen == [3]

    def test_engine_params_are_merged_with_context_ones(self):
        seen: list[object] = []

        def read_both(ctx):
            seen.append((ctx.param("from.ctx"), ctx.param("from.engine")))
            return ActionResult.success()

        scenario = _scenario(read_both)
        ctx = _ctx(scenario, params={"from.ctx": "a"})
        engine = build_engine(ctx, scenario)
        engine.params = {"from.engine": "b"}
        try:
            engine.run()
        finally:
            ctx.close()

        assert seen == [("a", "b")]

    def test_params_survive_reset(self):
        scenario = _scenario(lambda c: ActionResult.success())
        ctx = _ctx(scenario, params={"keep": 1})
        try:
            ctx.reset()
            assert ctx.param("keep") == 1
        finally:
            ctx.close()

    def test_params_view_is_read_only(self):
        scenario = _scenario(lambda c: ActionResult.success())
        ctx = _ctx(scenario, params={"a": 1})
        try:
            with pytest.raises(TypeError):
                ctx.params["a"] = 2  # type: ignore[index]
        finally:
            ctx.close()

    def test_param_names_can_be_dotted(self):
        scenario = _scenario(lambda c: ActionResult.success())
        ctx = _ctx(scenario, params={"farm.rounds": 1, "rounds": 2})
        try:
            assert ctx.param("farm.rounds") == 1
            assert ctx.param("rounds") == 2
        finally:
            ctx.close()


class TestRunStateReset:
    def test_blackboard_is_cleared_between_runs(self):
        scenario = _scenario(lambda c: ActionResult.success())
        ctx = _ctx(scenario)
        engine = build_engine(ctx, scenario)
        try:
            ctx.blackboard.set("leftover", "上一遍留下的")
            engine.run()
            assert ctx.blackboard.get("leftover") is None
        finally:
            ctx.close()

    def test_counter_does_not_leak_between_runs(self):
        def bump(ctx):
            ctx.blackboard.bump("rounds")
            return ActionResult.success()

        scenario = _scenario(bump, max_ticks=3)
        ctx = _ctx(scenario)
        engine = build_engine(ctx, scenario)
        try:
            engine.run()
            assert ctx.blackboard.get("rounds", 0) > 0, "第一次运行应该写下计数"

            engine.run()
            assert ctx.blackboard.get("rounds", 0) < 2, (
                f"第二次运行看到 rounds={ctx.blackboard.get('rounds')} —— "
                "黑板带着上一遍的数据"
            )
        finally:
            ctx.close()

    def test_report_does_not_count_previous_runs_steps(self):
        scenario = _scenario(lambda c: ActionResult.success(), max_ticks=2)
        ctx = _ctx(scenario)
        engine = build_engine(ctx, scenario)
        try:
            first = engine.run()
            second = engine.run()
            assert first.ticks == second.ticks == 2
            assert second.step_count == first.step_count, (
                f"第二遍报了 {second.step_count} 步、第一遍 {first.step_count} 步"
                " —— 执行器的 outcomes 没清"
            )
        finally:
            ctx.close()

    def test_reset_does_not_touch_params(self):
        scenario = _scenario(lambda c: ActionResult.success())
        ctx = _ctx(scenario, params={"target": "battle"})
        try:
            ctx.blackboard.set("junk", 1)
            ctx.reset()
            assert ctx.blackboard.get("junk") is None
            assert ctx.param("target") == "battle"
        finally:
            ctx.close()

    def test_reset_clears_the_stop_flag(self):
        scenario = _scenario(lambda c: ActionResult.success())
        ctx = _ctx(scenario)
        try:
            ctx.request_stop("上一遍点的停止")
            assert ctx.stop_requested is True
            ctx.reset()
            assert ctx.stop_requested is False
        finally:
            ctx.close()
