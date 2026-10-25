"""事件流 —— 引擎把哪些事实报了出现，以及"观测失败不许弄挂脚本"。

事件流是界面状态面板的数据源（[docs/ui.md](../docs/ui.md) 里那条
"状态面板不解析日志"）。所以这里测的是**契约**：

* 一轮跑下来，``run_started`` / ``tick`` / ``step_started`` / ``step_finished`` /
  ``run_finished`` 都在，而且**顺序对**（开始在前、结束在后）；
* 页面/节点**只在变了**的时候才发 ``*_changed``；
* 监听器抛异常只记账，不打断流程；但 ``Cancelled`` 要穿透（它是"停下来"）。

另有一条记账回归（``report.step_count`` 曾经翻倍）——
它不属于事件流，但用的是同一套"跑一轮"的装置，放一起省得再造一遍。
"""

from __future__ import annotations

import json

import pytest

from gamebot.atomic.query import ImageQuery
from gamebot.events import Event, EventBus, EventKind, JsonlEventWriter
from gamebot.exceptions import Cancelled
from gamebot.execution.executor import Executor
from gamebot.flow import NodeBindings
from gamebot.flow.engine import FlowEngine
from gamebot.flow.graph import Graph, Node
from gamebot.flow.scenario import Scenario
from gamebot.state.page import Page, PageTree
from gamebot.state.store import StoreChange
from gamebot.types import ActionResult, Point


def _ok(name: str, seen: list[str] | None = None):
    def step(ctx):
        if seen is not None:
            seen.append(name)
        return ActionResult.success(name)

    step.__name__ = name
    return step


def _reveal_b(ctx):
    """让假 Matcher 从"能看到 b 页"开始 —— 用来模拟"点了按钮换屏"。"""
    ctx.session.matcher.matches["b.png"] = (Point(10, 10), 0.99)
    return ActionResult.success()


def _scenario(*, steps=(), max_ticks: int = 1, two_pages: bool = False) -> Scenario:
    tree = PageTree()
    tree.add(Page("home", queries=(ImageQuery("a.png"),)))
    graph = Graph(initial="home")
    if two_pages:
        tree.add(Page("b", queries=(ImageQuery("b.png"),)))
        graph.add_node(Node("home", steps=list(steps)))
        graph.add_node(Node("next"))
        graph.connect("home", "next", priority=10)
        bindings = NodeBindings.of([("home", "home"), ("next", "b")])
    else:
        graph.add_node(Node("home", steps=list(steps)))
        bindings = NodeBindings.of([("home", "home")])
    scenario = Scenario(name="events", tree=tree, graph=graph, bindings=bindings)
    scenario.options.tick_interval = 0.001
    scenario.options.max_ticks = max_ticks
    scenario.validate()
    return scenario


def _engine(ctx, scenario, bus=None) -> FlowEngine:
    ctx.executor = Executor(ctx)
    return FlowEngine(scenario, ctx, events=bus)


class TestEventBus:
    def test_history_is_bounded(self) -> None:
        bus = EventBus(history=3)
        for index in range(5):
            bus.emit(Event(EventKind.TICK, tick=index))
        assert [e.tick for e in bus.recent()] == [2, 3, 4]
        assert [e.tick for e in bus.recent(1)] == [4]

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        seen: list[Event] = []
        cancel = bus.subscribe(seen.append)
        bus.emit(Event(EventKind.TICK))
        cancel()
        bus.emit(Event(EventKind.TICK))
        assert len(seen) == 1

    def test_listener_error_is_captured_not_raised(self) -> None:
        """观测手段坏了，脚本要照跑 —— 但错误必须留痕。"""
        bus = EventBus()
        later: list[Event] = []

        def broken(_event):
            raise RuntimeError("界面炸了")

        bus.subscribe(broken)
        bus.subscribe(later.append)

        bus.emit(Event(EventKind.TICK))

        assert len(later) == 1, "一个监听器坏了不该影响后面的"
        assert bus.errors and "界面炸了" in bus.errors[0]

    def test_cancelled_propagates(self) -> None:
        """``Cancelled`` 表示"停下来"，不是"出错了" —— 不能被当异常吞掉。"""
        bus = EventBus()

        def cancel(_event):
            raise Cancelled("用户点了停止")

        bus.subscribe(cancel)
        with pytest.raises(Cancelled):
            bus.emit(Event(EventKind.TICK))

    def test_to_dict_is_json_serializable(self) -> None:
        event = Event(EventKind.TICK, at=1.23456, tick=3, data={"page": "home"})
        payload = event.to_dict()
        assert json.loads(json.dumps(payload)) == {
            "kind": "tick",
            "at": 1.2346,
            "tick": 3,
            "data": {"page": "home"},
        }


class TestJsonlWriter:
    def test_one_line_per_event_with_wall_time(self, tmp_path) -> None:
        path = tmp_path / "events.jsonl"
        writer = JsonlEventWriter(path)
        bus = EventBus()
        bus.subscribe(writer)

        bus.emit(Event(EventKind.RUN_STARTED, at=0.5, tick=0, data={"scenario": "t"}))
        bus.emit(Event(EventKind.RUN_FINISHED, at=9.5, tick=2))

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["kind"] == "run_started"
        assert first["data"] == {"scenario": "t"}
        assert "wall" in first, "单调时钟换算不回墙上时间，所以要另记一条"

    def test_writer_can_be_called_directly(self, tmp_path) -> None:
        writer = JsonlEventWriter(tmp_path / "e.jsonl")
        writer.write(Event(EventKind.TICK, tick=1))
        assert json.loads((tmp_path / "e.jsonl").read_text(encoding="utf-8"))["tick"] == 1


class TestStoreEvents:
    def test_a_store_write_becomes_a_store_changed_event(self) -> None:
        """仓库 -> 事件流的那一段接线（在 ``bootstrap`` 里）要单独钉住。

        接错的症状是"背包确实在变，但事件流里一条都没有" —— 静默缺失。
        """
        from types import SimpleNamespace

        from gamebot.bootstrap import make_store_change_emitter

        bus = EventBus()
        fake_ctx = SimpleNamespace(now=lambda: 12.5, pages=SimpleNamespace(tick=7))
        emitter = make_store_change_emitter(bus, lambda: fake_ctx)

        emitter(StoreChange(store="bag", key="soul", old=0, new=3))

        event = bus.recent()[-1]
        assert event.kind is EventKind.STORE_CHANGED
        assert event.at == 12.5
        assert event.tick == 7
        assert event.data == {"store": "bag", "key": "soul", "old": 0, "new": 3}

    def test_no_context_yet_is_a_no_op(self) -> None:
        """装配期上下文还没造好时不能炸（那时也不会有写入）。"""
        from gamebot.bootstrap import make_store_change_emitter
        from gamebot.state.store import StoreChange

        bus = EventBus()
        make_store_change_emitter(bus, lambda: None)(
            StoreChange(store="bag", key="soul", old=None, new=1)
        )
        assert bus.recent() == []


class TestEngineEmits:
    def test_one_round_emits_the_expected_sequence(self, ctx) -> None:
        seen: list[str] = []
        bus = EventBus()
        engine = _engine(
            ctx, _scenario(steps=[_ok("one", seen), _ok("two", seen)]), bus
        )
        report = engine.run()

        kinds = [event.kind for event in bus.recent()]
        assert kinds[0] is EventKind.RUN_STARTED
        assert kinds[-1] is EventKind.RUN_FINISHED
        assert EventKind.TICK in kinds
        assert kinds.index(EventKind.STEP_STARTED) < kinds.index(EventKind.STEP_FINISHED)

        started = [e for e in bus.recent() if e.kind is EventKind.STEP_STARTED]
        finished = [e for e in bus.recent() if e.kind is EventKind.STEP_FINISHED]
        assert [e.data["step"] for e in started] == ["one", "two"]
        assert [e.data["status"] for e in finished] == ["success", "success"]

        final = bus.recent()[-1]
        assert final.data["steps"] == report.step_count
        assert final.data["stop_reason"] == report.stop_reason.value

    def test_page_and_node_changes_are_emitted_only_when_they_change(self, ctx) -> None:
        bus = EventBus()
        engine = _engine(ctx, _scenario(steps=[_reveal_b], max_ticks=2, two_pages=True), bus)
        engine.run()

        pages = [e for e in bus.recent() if e.kind is EventKind.PAGE_CHANGED]
        nodes = [e for e in bus.recent() if e.kind is EventKind.NODE_CHANGED]

        # 第一条是 ``unknown -> home``：**第一轮才认出自己在首页**，那也是一次
        # "页面变了"（界面靠它把状态面板从"未知"刷成"首页"）。
        assert [(e.data["from_page"], e.data["to_page"]) for e in pages] == [
            ("unknown", "home"),
            ("home", "b"),
        ]
        assert [(e.data["from_node"], e.data["to_node"]) for e in nodes] == [("home", "next")]

        # 每轮都有心跳，但"变化"只发一次 —— 否则事件流会被"还在同一页"淹掉
        ticks = [e for e in bus.recent() if e.kind is EventKind.TICK]
        assert len(ticks) == 2
        assert len(pages) == 2
        assert len(nodes) == 1

    def test_recovery_is_emitted(self, ctx) -> None:
        """重定位是"自动跳"最需要被看见的事，所以它必须进事件流。

        这里直接调内部的记账函数：完整的重定位路径很绕（要造出"认得出、
        但不是预期那一页"的画面），由 ``tests/test_flow.py`` 的
        ``TestEngineRealign`` 覆盖；本用例只钉"记账必发事件"。
        """
        bus = EventBus()
        engine = _engine(ctx, _scenario(), bus)
        engine._note_recovery("home", "home", "other", "other_node", None)

        recovery = [e for e in bus.recent() if e.kind is EventKind.RECOVERY]
        assert len(recovery) == 1
        assert recovery[0].data == {
            "from_node": "home",
            "expected": "home",
            "actual": "other",
            "to_node": "other_node",
            "attempts": 0,
        }

    def test_no_bus_means_no_events_and_no_crash(self, ctx) -> None:
        """老用法（不传总线）必须照常跑 —— 事件是附加物，不是依赖。"""
        engine = _engine(ctx, _scenario(steps=[_ok("one")]))
        assert engine.events is None
        engine.run()
        assert engine.report.stop_reason.value == "max_ticks"


class TestStepAccounting:
    def test_report_counts_each_step_once(self, ctx) -> None:
        """回归：``report.step_count`` 曾经是真实步数的两倍。

        原因是执行器在 ``_record`` 里记了一遍，引擎的 ``_note_outcome`` 又往
        同一个列表里塞了一遍。表现是报告写"2 步"、执行器说"跑了 4 步"，
        而其他数字都对 —— 很容易被当成统计口径不同。
        """
        seen: list[str] = []
        engine = _engine(ctx, _scenario(steps=[_ok("one", seen), _ok("two", seen)]))
        report = engine.run()

        assert seen == ["one", "two"]
        assert report.step_count == 2
        assert len(report.outcomes) == 2
        assert len(ctx.executor.outcomes) == 2
