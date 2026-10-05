"""运行参数（入参）与运行期状态的清理。

## 为什么需要"运行参数"

``Scenario`` 是在 ``build_scenario()`` 里构造的**静态对象** —— 那次调用拿不到
任何运行期信息。而"这次刷几局""用哪套阈值""开不开某个分支"要等到点开始才知道。
没有入参，这些值只能写死在脚本里，或者让步骤在构造时被焊死。

参数和黑板是**两件不同的事**，这个文件把界线钉住：

* **参数**：进去之前定好、跑的过程中**不变**（这次运行的目标、开关、阈值）；
* **黑板**：跑的过程中**写**的（连续失败计数、上次读到的体力）。
"""

from __future__ import annotations

import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.query import ImageQuery
from gamebot.atomic.session import BaseSession
from gamebot.bootstrap import build_context, build_engine
from gamebot.config.schema import AppConfig, BackendKind
from gamebot.execution.step import FunctionStep
from gamebot.flow.graph import Graph, Node
from gamebot.flow.scenario import Scenario
from gamebot.state.page import Page, PageTree
from gamebot.types import ActionResult, Point

from .conftest import FakeMatcher, FakeReader


def _scenario(step, *, max_ticks: int = 1) -> Scenario:
    tree = PageTree()
    tree.add(Page("home", queries=(ImageQuery("home.png"),)))
    graph = Graph(initial="home")
    graph.add_node(Node("home", page="home", steps=[step]))
    scenario = Scenario(name="params", tree=tree, graph=graph)
    scenario.options.tick_interval = 0.001
    scenario.options.max_ticks = max_ticks
    scenario.validate()
    return scenario


def _ctx(scenario, **kwargs):
    config = AppConfig.defaults()
    config.screen.backend = BackendKind.FAKE
    config.vision.record = False
    session = BaseSession(
        build_fake_backends(size=(640, 360)),
        matcher=FakeMatcher(matches={"home.png": (Point(1, 1), 0.99)}),
        reader=FakeReader(),
    )
    return build_context(
        config, scenario=scenario, session=session, scenario_options=scenario.options, **kwargs
    )


class TestRunParams:
    def test_step_reads_a_param(self):
        """步骤通过 ``ctx.param`` 读入参 —— 这是它存在的理由。"""
        seen: list[object] = []
        scenario = _scenario(
            FunctionStep(lambda c: (seen.append(c.param("farm.rounds")), ActionResult.success())[1])
        )
        ctx = _ctx(scenario, params={"farm.rounds": 5})
        engine = build_engine(ctx.config, ctx, scenario)
        try:
            engine.run()
        finally:
            ctx.close()

        assert seen == [5]

    def test_default_applies_when_param_absent(self):
        """给了默认值就是"可选参数"。"""
        seen: list[object] = []
        scenario = _scenario(
            FunctionStep(
                lambda c: (seen.append(c.param("farm.rounds", 3)), ActionResult.success())[1]
            )
        )
        ctx = _ctx(scenario)
        engine = build_engine(ctx.config, ctx, scenario)
        try:
            engine.run()
        finally:
            ctx.close()

        assert seen == [3]

    def test_engine_params_are_merged_with_context_ones(self):
        """引擎那儿的参数和上下文里已有的合并，不是覆盖。"""
        seen: list[object] = []
        scenario = _scenario(
            FunctionStep(
                lambda c: (
                    seen.append((c.param("from.ctx"), c.param("from.engine"))),
                    ActionResult.success(),
                )[1]
            )
        )
        ctx = _ctx(scenario, params={"from.ctx": "a"})
        engine = build_engine(ctx.config, ctx, scenario)
        engine.params = {"from.engine": "b"}  # 装配后再补
        try:
            engine.run()
        finally:
            ctx.close()

        assert seen == [("a", "b")]

    def test_params_survive_reset(self):
        """**参数不被 reset 清掉** —— 它是这次运行的输入，不是产物。"""
        scenario = _scenario(FunctionStep(lambda c: ActionResult.success()))
        ctx = _ctx(scenario, params={"keep": 1})
        try:
            ctx.reset()
            assert ctx.param("keep") == 1
        finally:
            ctx.close()

    def test_params_view_is_read_only(self):
        """``ctx.params`` 是只读视图：改它不该悄悄生效。"""
        scenario = _scenario(FunctionStep(lambda c: ActionResult.success()))
        ctx = _ctx(scenario, params={"a": 1})
        try:
            with pytest.raises(TypeError):
                ctx.params["a"] = 2  # type: ignore[index]
        finally:
            ctx.close()

    def test_param_names_can_be_dotted(self):
        """点分层级避免撞名（``"farm.rounds"`` vs ``"rounds"``）。"""
        scenario = _scenario(FunctionStep(lambda c: ActionResult.success()))
        ctx = _ctx(scenario, params={"farm.rounds": 1, "rounds": 2})
        try:
            assert ctx.param("farm.rounds") == 1
            assert ctx.param("rounds") == 2
        finally:
            ctx.close()


class TestRunStateReset:
    """同一个引擎跑第二遍时，**黑板不能带着上一遍的数据**。

    这个问题很难查：第一次跑和第二次跑行为不同，而代码看起来一模一样。
    """

    def test_blackboard_is_cleared_between_runs(self):
        scenario = _scenario(FunctionStep(lambda c: ActionResult.success()))
        ctx = _ctx(scenario)
        engine = build_engine(ctx.config, ctx, scenario)
        try:
            ctx.blackboard.set("leftover", "上一遍留下的")
            engine.run()
            assert ctx.blackboard.get("leftover") is None
        finally:
            ctx.close()

    def test_counter_does_not_leak_between_runs(self):
        """第一次运行写进黑板的计数器，第二次看不到。

        ## 这个用例改过两版，两版的**前提**都是错的，记下来免得再踩

        * 第一版用 ``max_ticks=1``：节点步骤在**首次进入节点**时执行
          （``on_enter`` 语义），整个生命周期只跑一次 —— 什么都验不到；
        * 第二版改 3 轮、断言"第二次也从 1 重新开始"：还是错的，因为
          ``run()`` 现在会 ``ctx.reset()``，它**清掉跟踪器**，而
          ``require_confirmed`` 要求连续几帧确认过才动手 —— 第二次运行的前几轮
          都在"确认中"，3 轮不够它重新确认。

        第二条是**清状态之后的正确行为**，不是 bug。所以别再依赖"步骤跑了几次"
        （那取决于确认需要几帧），直接看黑板的最终内容。
        """

        def bump(ctx):
            ctx.blackboard.bump("rounds")
            return ActionResult.success()

        scenario = _scenario(FunctionStep(bump), max_ticks=3)
        ctx = _ctx(scenario)
        engine = build_engine(ctx.config, ctx, scenario)
        try:
            engine.run()
            assert ctx.blackboard.get("rounds", 0) > 0, "第一次运行应该写下计数"

            engine.run()
            # 上一遍留下的值不该还在：要么第二次自己重新数（=1），要么还没开始数
            assert ctx.blackboard.get("rounds", 0) < 2, (
                f"第二次运行看到 rounds={ctx.blackboard.get('rounds')} —— "
                "黑板带着上一遍的数据"
            )
        finally:
            ctx.close()

    def test_report_does_not_count_previous_runs_steps(self):
        """第二遍报告的步数不能算上第一遍 —— 执行器攒的 outcomes 也要清。

        不清的后果不是报错，而是"跑 3 轮却报了 7 步"，而且越跑越多。
        """
        scenario = _scenario(FunctionStep(lambda c: ActionResult.success()), max_ticks=2)
        ctx = _ctx(scenario)
        engine = build_engine(ctx.config, ctx, scenario)
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
        """``reset`` 清运行期状态，但保住入参。"""
        scenario = _scenario(FunctionStep(lambda c: ActionResult.success()))
        ctx = _ctx(scenario, params={"target": "battle"})
        try:
            ctx.blackboard.set("junk", 1)
            ctx.reset()
            assert ctx.blackboard.get("junk") is None
            assert ctx.param("target") == "battle"
        finally:
            ctx.close()

    def test_reset_clears_the_stop_flag(self):
        """中止标志也要清 —— 否则第二次运行一开始就自己停了。"""
        scenario = _scenario(FunctionStep(lambda c: ActionResult.success()))
        ctx = _ctx(scenario)
        try:
            ctx.request_stop("上一遍点的停止")
            assert ctx.stop_requested is True
            ctx.reset()
            assert ctx.stop_requested is False
        finally:
            ctx.close()
