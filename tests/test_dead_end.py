"""末梢节点"没活儿干了"的判定 —— 流程走完之后必须自己结束。

## 为什么要这块

``StopReason.COMPLETED`` 的语义一直写着"没有可做的事且没有出边"，但**从来没有
代码触发它**。后果实测过：名将杀的竞技场（``jingji`` 没有出边、匹配页还没定义）
在 3 秒里空转了 **193 轮**，每轮失败一次，直到 ``max_runtime`` 才被掐停 ——
用户看到的是"脚本停不下来 / 一直没结束"。

判据刻意收得很窄（见 ``FlowEngine._note_stall``），所以这里**两种方向都要钉**：
该停的要停，**不该停的绝不能停**（把还在干活的流程当成"干完了"是更糟的 bug）。
"""

from __future__ import annotations

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.query import ImageQuery
from gamebot.atomic.session import BaseSession
from gamebot.bootstrap import build_context, build_engine
from gamebot.execution.step import FunctionStep
from gamebot.flow.engine import DEAD_END_STALL_ROUNDS, StopReason
from gamebot.flow.graph import Graph, Node
from gamebot.flow.scenario import Scenario
from gamebot.state.page import Page, PageTree
from gamebot.types import ActionResult, Point

from .conftest import FakeMatcher, FakeReader


def _not_found(*_args, **_kwargs):
    return ActionResult.not_found("三个按钮一个都没看到")


def _ok(*_args, **_kwargs):
    return ActionResult.success("点了")


def _boom(*_args, **_kwargs):
    return ActionResult.error("识别本身坏了")


def _build(
    *,
    steps,
    dead_end: bool = True,
    extra_edge: bool = False,
    dead_end_rounds: int = DEAD_END_STALL_ROUNDS,
    max_ticks: int = 40,
    ctx_config=None,
):
    """造一个"起点 -> 末梢"的场景，末梢要不要有出边由 ``extra_edge`` 决定。"""
    tree = PageTree()
    tree.add(Page("home", queries=(ImageQuery("home.png"),)))
    tree.add(Page("home/leaf", queries=(ImageQuery("leaf.png"),)), parent="home")
    if extra_edge:
        tree.add(Page("home/other", queries=(ImageQuery("other.png"),)), parent="home")

    graph = Graph(initial="home")
    graph.add_node(Node("home", page="home"))
    graph.add_node(Node("leaf", page="home/leaf", steps=steps))
    graph.connect("home", "leaf", condition=ImageQuery("leaf.png"), priority=10)
    if extra_edge:
        graph.add_node(Node("other", page="home/other"))
        graph.connect("leaf", "other", condition=ImageQuery("other.png"), priority=10)

    scenario = Scenario(name="deadend", tree=tree, graph=graph)
    scenario.options.tick_interval = 0.001
    scenario.options.max_ticks = max_ticks
    scenario.options.dead_end_rounds = dead_end_rounds
    scenario.validate()

    from gamebot.config.schema import AppConfig, BackendKind

    config = AppConfig.defaults()
    config.screen.backend = BackendKind.FAKE
    config.vision.record = False
    session = BaseSession(
        build_fake_backends(size=(640, 360)),
        matcher=FakeMatcher(matches={"leaf.png": (Point(1, 1), 0.99)}),
        reader=FakeReader(),
    )
    ctx = build_context(config, scenario=scenario, session=session,
                        scenario_options=scenario.options)
    engine = build_engine(config, ctx, scenario)
    return ctx, engine


def _run(**kwargs):
    ctx, engine = _build(**kwargs)
    try:
        return engine.run()
    finally:
        ctx.close()


class TestStopsWhenOutOfWork:
    def test_dead_end_with_not_found_stops_itself(self):
        """没有出边的末梢 + 一直 not_found = 流程走完了。"""
        report = _run(steps=[FunctionStep(_not_found, name="推进队伍流程")])

        assert report.stop_reason is StopReason.NO_MORE_WORK
        # 关键：**只跑了几轮**，不是空转到 max_ticks
        assert report.ticks <= DEAD_END_STALL_ROUNDS + 2, report.ticks
        assert report.ticks < 40

    def test_stop_message_says_which_node_and_why(self):
        """报告里要说清是哪个节点、最后一步是什么 —— 否则用户不知道去补什么。"""
        report = _run(steps=[FunctionStep(_not_found, name="推进队伍流程")])

        assert "leaf" in report.stop_message
        assert "推进队伍流程" in report.stop_message

    def test_it_is_not_a_failure(self):
        """活儿干完了不是失败：退出码和报告都该算正常。"""
        report = _run(steps=[FunctionStep(_not_found, name="推进队伍流程")])
        assert report.ok is True

    def test_threshold_is_configurable(self):
        """过渡慢的游戏可以把轮数调大。"""
        report = _run(steps=[FunctionStep(_not_found, name="推进")], dead_end_rounds=6)
        assert report.stop_reason is StopReason.NO_MORE_WORK
        assert report.ticks > 6

    def test_zero_disables_the_rule(self):
        """0 = 关掉这条判定（"我就想让它一直转着等"）。"""
        report = _run(
            steps=[FunctionStep(_not_found, name="推进")], dead_end_rounds=0, max_ticks=12
        )
        assert report.stop_reason is StopReason.MAX_TICKS


class TestDoesNotStopWhenThereIsStillWork:
    """**不该停的时候绝不能停** —— 把还在干活的流程当成"干完了"更糟。"""

    def test_node_with_out_edges_keeps_going(self):
        """还有出边 = 还有下一步可走，不能因为"这轮没找到"就收工。"""
        report = _run(
            steps=[FunctionStep(_not_found, name="推进")], extra_edge=True, max_ticks=15
        )
        assert report.stop_reason is StopReason.MAX_TICKS, report.stop_reason

    def test_error_is_not_treated_as_out_of_work(self):
        """``error`` 是识别/配置坏了，不能被"流程正常结束"掩盖掉。"""
        report = _run(steps=[FunctionStep(_boom, name="推进")], max_ticks=12)
        assert report.stop_reason is StopReason.MAX_TICKS, report.stop_reason

    def test_counter_resets_after_a_success(self):
        """中途成功过一次就重新数 —— 否则"偶尔成功、偶尔失败"会被误判成干完了。"""
        calls = {"n": 0}

        def flaky(*_args, **_kwargs):
            calls["n"] += 1
            # 每第 3 次成功一次：永远不会连着 3 轮 not_found
            if calls["n"] % 3 == 0:
                return ActionResult.success("点了")
            return ActionResult.not_found("这轮没找到")

        report = _run(steps=[FunctionStep(flaky, name="推进")], max_ticks=20)
        assert report.stop_reason is StopReason.MAX_TICKS, report.stop_reason
        assert calls["n"] > DEAD_END_STALL_ROUNDS

