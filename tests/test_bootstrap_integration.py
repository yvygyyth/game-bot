"""整条装配链的集成测试 —— **bootstrap 到引擎跑完一轮**。

## 为什么需要它

单元测试把每一层都测过了，但"**它们接起来还能不能用**"是另一件事。真实入口
（``python -m games run`` / 界面上的「开始」）走的都是
:func:`gamebot.bootstrap.bootstrap_from_spec`：

    读 SPEC -> 建路径 -> 建事件总线 -> 建仓库管理器 -> 建 Matcher/Session
            -> 建 RunContext -> 建 Executor -> 建 FlowEngine

这条链上任何一环接错（参数名改了、忘了传、顺序反了），单元测试全是绿的，
**只有真跑起来才发现**。所以这里用假后端把它整条走一遍，并且断言那些
"接线产物"都真的存在：

* 事件总线挂在 ``ctx.events`` 上，``logs/events/<slug>.jsonl`` 有内容；
* 仓库落在 ``data/stores/<游戏>/`` 下，跑完 ``close()`` 真的写盘；
* 执行器的钩子装上了（步骤事件才发得出来）；
* journal 有逐步骤记录；
* ``report.step_count`` 等于真跑了几步。

**全部写在临时目录里**（``root=tmp_path``）—— 装配不该往项目目录里写东西。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.query import ImageQuery
from gamebot.atomic.session import BaseSession
from gamebot.bootstrap import bootstrap_from_spec
from gamebot.execution.journal import JsonlJournal
from gamebot.feature import FeatureSpec
from gamebot.flow import EngineOptions, Node, NodeBindings
from gamebot.scenario_spec import ScenarioSpec
from gamebot.state.page import PageGroup, PageLeaf
from gamebot.state.store import define_store
from gamebot.types import ActionResult, Point

from .conftest import FakeMatcher, FakeReader

#: 集成用例自己的仓库：游戏级 id（没有功能前缀）。
DEMO_RUNS = define_store("demo.runs", title="演示计数", defaults={"n": 0})


def _bump(ctx):
    ctx.store(DEMO_RUNS).bump("n")
    return ActionResult.success("bump")


def _noop(ctx):
    return ActionResult.success("noop")


def _spec() -> FeatureSpec:
    tree = PageGroup(
        "home",
        children=(PageLeaf("home/main", queries=(ImageQuery("a.png"),)),),
    )
    scenario = ScenarioSpec(
        initial="probe",
        tree=tree,
        bindings=NodeBindings.of([("probe", "home/main")]),
        nodes=(Node("probe", steps=[_bump, _noop]),),
        options=EngineOptions(tick_interval=0.001, max_ticks=2),
    )
    return FeatureSpec(
        name="demo/flow",
        title="装配演示",
        slug="flow",
        window_title="演示窗口",
        scenario=scenario,
    )


@pytest.fixture
def wired(tmp_path: Path):
    """装配好但还没跑的一整套（所有写入都在 tmp_path 下）。"""
    feature = _spec()
    # 装配期要求模板目录存在（真实脚本会有图；这里的 Matcher 是假的）
    (tmp_path / "games" / "demo" / "scripts" / "flow" / "templates").mkdir(parents=True)
    session = BaseSession(
        build_fake_backends(size=(320, 200)),
        matcher=FakeMatcher(matches={"a.png": (Point(5, 5), 0.99)}),
        reader=FakeReader(),
    )
    journal = JsonlJournal(tmp_path / "journal.jsonl")
    ctx, engine = bootstrap_from_spec(
        feature,
        session=session,
        journal=journal,
        record=False,
        root=tmp_path,
        ocr="none",
    )
    try:
        yield ctx, engine, tmp_path
    finally:
        ctx.close()
        journal.close()


class TestWiring:
    def test_paths_are_under_the_given_root(self, wired) -> None:
        ctx, _engine, root = wired
        assert ctx.paths.root == root
        assert (root / "logs" / "screenshots").is_dir()
        assert (root / "logs" / "journals").is_dir()

    def test_store_manager_points_at_data_stores(self, wired) -> None:
        ctx, _engine, root = wired
        assert ctx.stores.root == root / "data" / "stores"
        assert ctx.stores.game == "demo"
        # 回调在不在，是"仓库 -> 事件流"那根线有没有断的唯一证据。
        # （回归：`stores or StoreManager(...)` 会把空的管理器换成没回调的新实例，
        #   root/game 都还一样，只有这里能看出来。）
        assert ctx.stores.on_change is not None

    def test_event_bus_is_attached_with_a_writer(self, wired) -> None:
        """总线接上了，而且**已经挂了一个监听器**（JSONL writer）。

        只断言"不是 None"太弱：writer 忘了 subscribe 的话总线照样不是 None，
        但事件一条都不会落盘。
        """
        ctx, _engine, _root = wired
        assert ctx.events is not None
        assert len(ctx.events) == 1, f"期望 1 个监听器（writer），实际 {len(ctx.events)}"

    def test_step_hooks_are_installed(self, wired) -> None:
        """引擎把"步骤开始/结束"挂到了执行器上（事件流靠这对钩子）。"""
        ctx, _engine, _root = wired
        assert ctx.executor is not None
        assert ctx.executor.hooks.before_step is not None
        assert ctx.executor.hooks.after_step is not None


class TestOneRun:
    def test_everything_lands_on_disk(self, wired) -> None:
        ctx, engine, root = wired
        report = engine.run()

        # 1) 报告按真实步数记账（2 轮 × 2 步）
        assert report.ticks == 2
        assert report.step_count == 4

        # 2) 事件流：文件里有这一轮的全套事实
        events_file = root / "logs" / "events" / "flow.jsonl"
        assert events_file.is_file()
        kinds = _kinds(events_file)
        assert kinds[0] == "run_started"
        assert kinds[-1] == "run_finished"
        for expected in (
            "tick",
            "page_changed",
            "step_started",
            "step_finished",
            "store_changed",
        ):
            assert expected in kinds, f"事件流里缺 {expected}"

        # 3) journal：一步一行
        journal_lines = (root / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(journal_lines) == 4

        # 4) 仓库：close() 之后写盘
        ctx.close()
        store_file = root / "data" / "stores" / "demo" / "demo.runs.json"
        assert store_file.is_file()
        assert json.loads(store_file.read_text(encoding="utf-8"))["state"]["n"] == 2

        # 5) 监听器出错会记进 bus.errors —— 这里应当一条都没有
        assert ctx.events is not None
        assert ctx.events.errors == []


def _kinds(path: Path) -> list[str]:
    return [
        json.loads(line)["kind"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
