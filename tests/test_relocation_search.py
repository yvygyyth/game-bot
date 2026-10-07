"""重定位：搜索顺序、去重、轮数、前置延迟、以及"全试过了"的判定。

## 用户的要求（逐条对应到这里的测试组）

"加一个当前状态队列，有个常数，比如队列长度固定 5"、
"状态重定位先沿着这个队列向上查，再扩散式查"、
"重定位查的过程记得去重"、
"总共查两轮（这也可以是个常数）"、
"重定位内部有个前置 5 秒延迟"、
"全部查完所有状态都没定位到，还是查不到就脚本结束了"。

| 组 | 钉什么 |
|---|---|
| `TestQueueComesBeforeDiffusion` | 队列里的状态**先于**扩散路径被探到 |
| `TestNoDuplicateProbing` | **一轮内**同一个状态最多探一次 |
| `TestPassBudget` | 轮数是常数、可配；去重**不跨轮** |
| `TestExhaustedFlag` | 全试过时 `PageMatch.exhausted` 为真 |
| `TestTrackerQueue` | 队列本身：最近优先、去重、跳过 unknown |
| `TestRecoverDelay` | **前置延迟**：出问题立刻登记，等够才搜 |
| `TestEngineStopsWhenExhausted` | 等够了、搜两轮都落空 -> 当场停 |

判据尽量落在 **`PageMatch.attempts`**（每次探测一条）和
**匹配调用的先后顺序**上 —— 后者是必须的，因为"最后认成了谁"不足以
验证"顺序"（把队列整个禁用掉，只测结果的断言照样全绿）。
"""

from __future__ import annotations

import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.query import ImageQuery
from gamebot.atomic.session import BaseSession
from gamebot.state.page import PageGroup, PageLeaf, PageTree
from tests.conftest import FakeMatcher

SIZE = (640, 360)


def _tree() -> PageTree:
    """两棵分支，各自两个末梢。

        a            b
        ├── a/1      ├── b/1
        └── a/2      └── b/2

    分支分开是为了验证"队列能跨分支先命中" —— 纯扩散从 `a` 出发要爬回根
    才够到 `b`，而队列一上来就能试 `b/1`。
    """
    tree = PageTree()
    tree.add(
        PageGroup(
            "a",
            children=(
                PageLeaf("a/1", queries=(ImageQuery("a1.png"),)),
                PageLeaf("a/2", queries=(ImageQuery("a2.png"),)),
            ),
        )
    )
    tree.add(
        PageGroup(
            "b",
            children=(
                PageLeaf("b/1", queries=(ImageQuery("b1.png"),)),
                PageLeaf("b/2", queries=(ImageQuery("b2.png"),)),
            ),
        )
    )
    return tree


def _session(matches: dict[str, tuple[object, float]]) -> BaseSession:
    matcher = FakeMatcher(matches=matches)  # type: ignore[arg-type]
    return BaseSession(build_fake_backends(size=SIZE), matcher=matcher)


class _OrderRecorder(FakeMatcher):
    """记录**匹配调用的先后顺序** —— 探测顺序只有在这里才看得见。"""

    def __init__(self, matches: dict[str, tuple[object, float]]):
        super().__init__(matches=matches)  # type: ignore[arg-type]
        self.seen: list[str] = []

    def match(self, image, template, **kwargs):  # type: ignore[override]
        self.seen.append(template)
        return super().match(image, template, **kwargs)


def _ordered_session(
    matches: dict[str, tuple[object, float]],
) -> tuple[BaseSession, _OrderRecorder]:
    matcher = _OrderRecorder(matches)
    return BaseSession(build_fake_backends(size=SIZE), matcher=matcher), matcher


def _probed(match: object) -> list[str]:
    """这次定位试过哪些状态（按顺序）。"""
    return [a.id for a in match.attempts]  # type: ignore[attr-defined]


class TestQueueComesBeforeDiffusion:
    """**核心性质**：队列里的状态先被试，扩散路径上的后试。"""

    def test_queue_is_tried_before_the_diffusion_path(self):
        """队列给一个**不命中**的 b/1，真正命中在扩散线上的 a/2。

        探测顺序必须是 ``b1 -> a2``：队列整圈跑在扩散前面。
        把队列那一圈挪到扩散之后（或整个禁掉），这条立刻红 ——
        而"最后认成了谁"那类断言**测不出**这个（扩散最终也能找到 a/2）。
        """
        from gamebot.types import Point

        tree = _tree()
        session, matcher = _ordered_session({"a2.png": (Point(1, 1), 0.99)})
        frame = session.capture()

        result = tree.recover(frame, near="a/1", recent=("b/1",))

        assert result.ok and result.value is not None
        assert result.value.id == "a/2"
        assert "b1.png" in matcher.seen, "队列里的状态压根没被试"
        assert matcher.seen.index("b1.png") < matcher.seen.index("a2.png"), (
            f"队列没先于扩散: {matcher.seen}"
        )

    def test_a_queue_hit_stops_the_whole_search(self):
        """队列里命中就**立刻停手** —— 扩散路上的状态一个都不该被试。"""
        from gamebot.types import Point

        tree = _tree()
        # 只有 b1 命中；a 分支的两个都不命中
        session, matcher = _ordered_session({"b1.png": (Point(1, 1), 0.99)})
        frame = session.capture()

        result = tree.recover(frame, near="a/1", recent=("b/1",))

        assert result.ok and result.value is not None
        assert result.value.id == "b/1"
        assert "b2.png" not in matcher.seen, f"命中之后还在继续试: {matcher.seen}"

    def test_the_queue_is_probed_in_the_order_given(self):
        """队列按**给的顺序**试 —— "最近的排前面"是调用方的责任，这里保证听话。"""
        from gamebot.types import Point

        tree = _tree()
        session, matcher = _ordered_session({"b2.png": (Point(1, 1), 0.99)})
        frame = session.capture()
        result = tree.recover(frame, near="a/1", recent=("b/1", "b/2"))

        assert result.ok and result.value is not None
        assert result.value.id == "b/2"
        assert matcher.seen.index("b1.png") < matcher.seen.index("b2.png")

    def test_empty_queue_falls_back_to_diffusion(self):
        """没给队列就退化成原来的行为 —— 老调用点一个字不用改。"""
        from gamebot.types import Point

        tree = _tree()
        frame = _session({"a2.png": (Point(1, 1), 0.99)}).capture()
        result = tree.recover(frame, near="a/1")

        assert result.ok and result.value is not None
        assert result.value.id == "a/2"


class TestNoDuplicateProbing:
    def test_a_state_is_probed_at_most_once_per_round(self):
        """一轮内同一个状态最多探一次 —— 队列和扩散路径重叠时也一样。"""
        from gamebot.types import Point

        tree = _tree()
        frame = _session({"a2.png": (Point(1, 1), 0.99)}).capture()

        # 队列里塞满"扩散路上也会遇到"的状态，逼出去重问题
        result = tree.recover(frame, near="a/1", recent=("a/1", "a/2", "a/1", "a/2"))
        assert result.ok and result.value is not None

        # 命中就返回了，所以这一轮的探测列表本身就是"试过谁"；
        # 跨轮会有重复（那是设计），这里只查**一轮内**
        first_round = _probed(result.value)
        assert len(first_round) == len(set(first_round)), f"一轮内有重复探测: {first_round}"

    def test_duplicates_in_the_queue_do_not_waste_matches(self):
        """队列里重复的 id 只探一次 —— 不去重的话队列会被它占满。"""
        from gamebot.types import Point

        tree = _tree()
        frame = _session({"a2.png": (Point(1, 1), 0.99)}).capture()
        result = tree.recover(frame, near="a/1", recent=("a/2",) * 10)

        assert result.ok and result.value is not None
        assert _probed(result.value).count("a/2") == 1

    def test_unknown_ids_in_the_queue_are_skipped(self):
        """队列里混进树里没有的 id（比如 unknown）不该崩，也不该记成一次探测。"""
        from gamebot.types import Point

        tree = _tree()
        frame = _session({"b1.png": (Point(1, 1), 0.99)}).capture()
        result = tree.recover(
            frame, near="a/1", recent=("unknown", "根本没这个", "b/1")
        )

        assert result.ok and result.value is not None
        assert result.value.id == "b/1"
        assert "根本没这个" not in _probed(result.value)


class TestPassBudget:
    """轮数是**常数**，而且每一轮都要真的重新探一遍。"""

    def test_one_round_is_enough_when_something_matches(self):
        """第一轮就命中时不该有第二轮 —— 探测量不该翻倍。"""
        from gamebot.types import Point

        tree = _tree()
        frame = _session({"a2.png": (Point(1, 1), 0.99)}).capture()
        result = tree.recover(frame, near="a/1")

        assert result.ok and result.value is not None
        # 树里一共 4 个状态，命中那轮最多探 4 个；翻倍说明跑了两轮
        assert len(_probed(result.value)) <= 4

    def test_passes_is_configurable(self):
        """``passes`` 可传 —— 用户要的"这也可以是个常数"就落在这儿。"""
        tree = _tree()
        frame = _session({}).capture()

        one = tree.recover(frame, near="a/1", passes=1)
        three = tree.recover(frame, near="a/1", passes=3)

        assert one.ok and one.value is not None
        assert three.ok and three.value is not None
        # 4 个状态：1 轮 -> 4 条，3 轮 -> 12 条
        assert len(one.value.attempts) == 4
        assert len(three.value.attempts) == 12

    def test_passes_is_at_least_one(self):
        """配 0 或负数不该变成"不搜" —— 那会让"全试过"这个结论失去意义。"""
        tree = _tree()
        frame = _session({}).capture()
        result = tree.recover(frame, near="a/1", passes=0)

        assert result.ok and result.value is not None
        assert result.value.exhausted is True
        assert len(result.value.attempts) == 4  # 至少搜了一轮

    def test_dedup_does_not_span_rounds(self):
        """**去重不跨轮**：第二轮必须重新探一遍。

        不然两轮等于一轮 —— 而轮数存在的全部意义就是"画面可能在两次之间变了，
        再探一遍"。这个 bug 写出来时就有，被这条断言抓住。
        """
        tree = _tree()
        frame = _session({}).capture()
        result = tree.recover(frame, near="a/1", passes=2)

        assert result.ok and result.value is not None
        probed = _probed(result.value)
        assert len(probed) == 8, f"预期 4 个状态 × 2 轮 = 8 条，实际 {len(probed)}: {probed}"
        # 每一个状态都应该出现两次（每轮一次）
        assert all(probed.count(p) == 2 for p in set(probed)), f"各轮探测不均衡: {probed}"


class TestExhaustedFlag:
    def test_nothing_matches_marks_exhausted(self):
        """一个都不命中 -> ``exhausted`` 为真（上层据此当场结束）。"""
        tree = _tree()
        frame = _session({"别的.png": (object(), 0.99)}).capture()
        result = tree.recover(frame, near="a/1", recent=("b/1",))

        assert result.ok and result.value is not None
        assert result.value.id == "unknown"
        assert result.value.exhausted is True

    def test_a_hit_never_marks_exhausted(self):
        """命中了就不是"全试过" —— 这个标志只在真的找不着时为真。"""
        from gamebot.types import Point

        tree = _tree()
        frame = _session({"b2.png": (Point(1, 1), 0.99)}).capture()
        result = tree.recover(frame, near="a/1", recent=("b/1", "b/2"))

        assert result.ok and result.value is not None
        assert result.value.exhausted is False


class TestTrackerQueue:
    """队列本身：``PageTracker.recent_ids``。"""

    def _tracker(self):
        from gamebot.state.tracker import PageTracker

        return PageTracker(_tree())

    def _observe(self, tracker, page_id: str) -> None:
        from gamebot.state.page import PageMatch

        tracker.update(PageMatch(id=page_id), now=0.0)

    def test_most_recent_first(self):
        tracker = self._tracker()
        for page_id in ("a/1", "a/2", "b/1"):
            self._observe(tracker, page_id)
        assert tracker.recent_ids(3) == ("b/1", "a/2", "a/1")

    def test_deduplicated(self):
        """同一个状态连续观测很多帧，队列里只占一个名额。"""
        tracker = self._tracker()
        for _ in range(20):
            self._observe(tracker, "a/1")
        for _ in range(20):
            self._observe(tracker, "b/1")

        assert tracker.recent_ids(5) == ("b/1", "a/1")

    def test_limit_is_respected(self):
        tracker = self._tracker()
        for page_id in ("a/1", "a/2", "b/1", "b/2"):
            self._observe(tracker, page_id)
        assert tracker.recent_ids(2) == ("b/2", "b/1")

    def test_limit_zero_or_negative_is_empty(self):
        tracker = self._tracker()
        self._observe(tracker, "a/1")
        assert tracker.recent_ids(0) == ()
        assert tracker.recent_ids(-3) == ()

    def test_unknown_is_skipped(self):
        """``unknown`` 不是状态，放进队列只会白费一次匹配。"""
        tracker = self._tracker()
        self._observe(tracker, "a/1")
        self._observe(tracker, "unknown")
        assert tracker.recent_ids(5) == ("a/1",)

    def test_empty_history_is_empty(self):
        assert self._tracker().recent_ids(5) == ()


# --------------------------------------------------------------------------- #
# 引擎侧：前置延迟 + 延迟结束后的结论
# --------------------------------------------------------------------------- #
def _engine_fixture(*, delay: float, matches: dict):
    """造一个最小可跑的引擎：4 个状态、4 个节点、一条直线。"""
    from gamebot.config.schema import AppConfig, BackendKind
    from gamebot.context import RunContext
    from gamebot.flow.bindings import NodeBindings
    from gamebot.flow.engine import FlowEngine
    from gamebot.flow.graph import Edge, Graph, Node
    from gamebot.flow.scenario import EngineOptions, Scenario

    config = AppConfig.defaults()
    config.screen.backend = BackendKind.FAKE
    config.vision.record = False

    tree = _tree()
    # 节点必须**从 initial 都走得到**，否则装配期校验报死代码
    graph = Graph(initial="a/1")
    for node_id in ("a/1", "a/2", "b/1", "b/2"):
        graph.add_node(Node(node_id))
    for src, dst in (("a/1", "a/2"), ("a/2", "b/1"), ("b/1", "b/2")):
        graph.add_edge(Edge(src, dst))

    scenario = Scenario(
        name="recover-delay",
        tree=tree,
        graph=graph,
        bindings=NodeBindings.of(
            [("a/1", "a/1"), ("a/2", "a/2"), ("b/1", "b/1"), ("b/2", "b/2")]
        ),
        options=EngineOptions(tick_interval=0.01),
    )
    scenario.validate()

    ctx = RunContext(_session(matches), config, tree=tree, frame_ttl=0.0)
    engine = FlowEngine(scenario, ctx)
    engine.RECOVER_DELAY = delay
    return ctx, engine


class TestRecoverDelay:
    """**前置延迟**：出问题立刻登记，等够了才搜。

    这个延迟是"界面在过渡"和"真卡住了"的分界线 —— 过渡会自己恢复，
    那时待办被清掉，一次搜索都不做。

    ⚠️ `tick(now=...)` 里 `now=0.0` 会被当成"没给"而回落到 `ctx.now()`
    （真实单调时钟，通常几十万秒）。所以这里用真实量级的时间轴，
    别拿 0 当起点 —— 那会让延迟看起来永远没到。
    """

    def test_problem_is_registered_immediately_but_not_acted_on(self, qt_app):
        """认不出来时**立刻**登记待办，但**不动手**（哪怕现在已经过了很久）。"""
        ctx, engine = _engine_fixture(delay=5.0, matches={})
        try:
            engine.tick(now=1000.0)
            assert engine._pending_recover is not None, "该登记待办"
            assert engine._pending_recover[0] == pytest.approx(1005.0), "截止时刻 = 现在 + 延迟"
            assert engine.running, "延迟期间不该停"
        finally:
            ctx.close()

    def test_it_waits_until_the_deadline(self, qt_app):
        """没到截止时刻就继续等 —— 不搜、不停。"""
        ctx, engine = _engine_fixture(delay=5.0, matches={})
        try:
            engine.tick(now=1000.0)
            for t in (1001.0, 1002.0, 1004.9):
                engine.tick(now=t)
                assert engine.running, f"t={t} 就停了，延迟没生效"
                assert engine._pending_recover is not None
        finally:
            ctx.close()

    def test_a_recovered_screen_cancels_the_pending_recovery(self, qt_app):
        """延迟期间画面变回可识别的样子 -> 待办被清掉（**这件事就是延迟的用处**）。"""
        from gamebot.types import Point

        ctx, engine = _engine_fixture(delay=5.0, matches={})
        try:
            engine.tick(now=1000.0)  # 认不出来 -> 登记
            assert engine._pending_recover is not None

            # 画面恢复了：现在能认出 a/1（= 当前节点绑定的状态）
            engine.ctx.session.matcher.matches = {"a1.png": (Point(1, 1), 0.99)}  # type: ignore[union-attr]
            engine.ctx.invalidate_frame()
            engine.tick(now=1001.0)

            assert engine._pending_recover is None, "画面恢复了，待办该被清掉"
            assert engine.report.errors == [], "过渡不该记成错误"
        finally:
            ctx.close()

    def test_after_the_deadline_it_searches_and_stops(self, qt_app):
        """等够了、两轮都搜不到 -> 当场停，而且**说明等了多久、搜了几轮**。"""
        ctx, engine = _engine_fixture(delay=5.0, matches={})
        try:
            engine.tick(now=1000.0)  # 登记
            engine.tick(now=1005.0)  # 到点了 -> 搜 -> 落空 -> 停

            assert not engine.running, "搜完落空该停"
            assert engine.report.errors, "该留一条 errors"
            message = engine.report.errors[0]
            assert "所有状态" in message
            assert "2 轮" in message, f"该说清搜了几轮: {message}"
            stop = engine._stop_message
            assert "5s" in stop, f"该说清等了多久: {stop}"
        finally:
            ctx.close()

    def test_delay_is_the_documented_default(self):
        """默认 5 秒 —— 用户明确要的那个数。"""
        from gamebot.flow.engine import FlowEngine

        assert FlowEngine.RECOVER_DELAY == 5.0
        assert FlowEngine.RECOVER_PASSES == 2
        assert FlowEngine.RECENT_STATES == 5
