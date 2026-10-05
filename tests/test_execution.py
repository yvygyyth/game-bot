"""执行层测试：策略对象 / 步骤构造与执行 / 执行器的四件事 / journal。"""

from __future__ import annotations

import json

import pytest

from gamebot.atomic.query import ImageQuery
from gamebot.exceptions import ConfigError, StepFailed
from gamebot.execution.executor import Executor, ExecutorHooks, StepOutcome
from gamebot.execution.journal import (
    JournalEntry,
    JsonlJournal,
    MemoryJournal,
    NullJournal,
)
from gamebot.execution.policy import NO_RETRY, ErrorMode, RetryPolicy, StepPolicy
from gamebot.execution.step import (
    CaptureStep,
    ClickImageStep,
    ClickStep,
    ClickTextStep,
    CompositeStep,
    ConditionalStep,
    FunctionStep,
    KeyStep,
    QueryStep,
    Step,
    WaitStep,
    step_from_dict,
    step_registry,
)
from gamebot.types import ActionResult, ActionStatus, Point, Region


@pytest.fixture(autouse=True)
def _with_executor(ctx):
    """给本模块的每个用例挂上执行器。

    ``conftest`` 的 ``ctx`` 故意不挂（装配期才由 ``bootstrap`` 挂），
    但这一整个模块测的就是"执行器怎么跑步骤"，所以在这里统一接上。
    用 ``if None`` 而不是无条件覆盖：个别用例会自己造一个（比如带 MemoryJournal）。
    """
    if ctx.executor is None:
        ctx.executor = Executor(ctx)
    return ctx


class TestRetryPolicy:
    def test_single_attempt_is_disabled(self) -> None:
        policy = RetryPolicy()
        assert policy.enabled is False
        assert policy.should_retry(1, ActionStatus.NOT_FOUND) is False

    def test_delay_is_constant_by_default(self) -> None:
        policy = RetryPolicy(max_attempts=3, interval=0.5)
        assert policy.delay_for(1) == 0.5
        assert policy.delay_for(2) == 0.5

    def test_backoff(self) -> None:
        policy = RetryPolicy(max_attempts=4, interval=0.2, backoff=2.0)
        assert policy.delay_for(1) == pytest.approx(0.2)
        assert policy.delay_for(2) == pytest.approx(0.4)
        assert policy.delay_for(3) == pytest.approx(0.8)

    def test_should_retry_respects_max_and_status(self) -> None:
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(1, ActionStatus.NOT_FOUND) is True
        assert policy.should_retry(2, ActionStatus.TIMEOUT) is True
        assert policy.should_retry(3, ActionStatus.NOT_FOUND) is False

    def test_retry_on_filter(self) -> None:
        policy = RetryPolicy(max_attempts=3, retry_on=(ActionStatus.TIMEOUT,))
        assert policy.should_retry(1, ActionStatus.TIMEOUT) is True
        assert policy.should_retry(1, ActionStatus.NOT_FOUND) is False

    def test_no_retry_constant(self) -> None:
        assert NO_RETRY.max_attempts == 1


class TestStepPolicy:
    def test_defaults_are_gentle(self) -> None:
        policy = StepPolicy()
        assert policy.on_error is ErrorMode.CONTINUE
        assert policy.require_success is False
        assert policy.timeout is None
        assert policy.precondition is None

    def test_must_raises_on_failure(self) -> None:
        policy = StepPolicy.must()
        assert policy.on_error is ErrorMode.RAISE
        assert policy.require_success is True

    def test_patient_retries(self) -> None:
        policy = StepPolicy.patient(attempts=5, interval=1.0)
        assert policy.retry.max_attempts == 5
        assert policy.retry.interval == 1.0

    def test_once_is_single_shot(self) -> None:
        assert StepPolicy.once().retry.max_attempts == 1

    def test_error_modes(self) -> None:
        assert {m.value for m in ErrorMode} == {"raise", "continue", "stop_flow", "abort_tick"}


class TestStepConstruction:
    def test_click_step(self) -> None:
        step = ClickStep(Point(10, 20))
        assert step.point == Point(10, 20)
        assert step.clicks == 1
        assert "点击" in step.describe()

    def test_click_image_step(self) -> None:
        step = ClickImageStep("a.png", region=Region(0, 0, 5, 5), confidence=0.8)
        assert step.template == "a.png"
        assert step.confidence == 0.8
        assert step.region == Region(0, 0, 5, 5)

    def test_click_text_step(self) -> None:
        assert ClickTextStep("开始").text == "开始"

    def test_key_step_accepts_str_or_list(self) -> None:
        assert KeyStep("enter").keys == ["enter"]
        assert KeyStep(["ctrl", "s"]).keys == ["ctrl", "s"]
        assert "ctrl+s" in KeyStep(["ctrl", "s"]).describe()

    def test_wait_step_requires_something(self) -> None:
        with pytest.raises(ValueError):
            WaitStep()
        assert WaitStep(seconds=1.0).seconds == 1.0

    def test_wait_step_disappear_label(self) -> None:
        from gamebot.atomic.query import ImageQuery

        step = WaitStep(query=ImageQuery("a.png"), disappear=True)
        assert "消失" in step.describe()

    def test_query_step(self) -> None:
        from gamebot.atomic.query import ImageQuery

        step = QueryStep(ImageQuery("a.png"), save_as="stamina")
        assert step.save_as == "stamina"
        assert "查询" in step.describe()

    def test_capture_step_needs_fresh_frame(self) -> None:
        assert CaptureStep().needs_fresh_frame is True

    def test_function_step_uses_name(self) -> None:
        step = FunctionStep(lambda ctx: ActionResult.success(1))
        assert step.name == "<lambda>"

    def test_composite_and_conditional(self) -> None:
        inner = ClickStep(Point(1, 1))
        composite = CompositeStep([inner, inner], name="两步")
        assert len(composite.steps) == 2
        conditional = ConditionalStep("cond", [inner], [])
        assert conditional.then_steps == [inner]
        assert conditional.else_steps == []

    def test_policy_can_be_attached(self) -> None:
        step = ClickStep(Point(1, 1), policy=StepPolicy.must(timeout=2.0))
        assert step.policy.require_success is True
        assert step.policy.timeout == 2.0

    def test_all_steps_are_registered(self) -> None:
        registry = step_registry()
        for name in (
            "ClickStep",
            "ClickImageStep",
            "ClickTextStep",
            "KeyStep",
            "WaitStep",
            "QueryStep",
            "CaptureStep",
            "CompositeStep",
            "ConditionalStep",
            "FunctionStep",
        ):
            assert name in registry, f"{name} 未登记到 step_registry"

    def test_click_step_runs_directly(self, ctx, input_recorder) -> None:
        """步骤本体（不经执行器）也能跑：``ClickStep`` 收逻辑坐标、下发源坐标。"""
        result = ClickStep(Point(1, 1)).run(ctx)
        assert result.ok is True
        assert input_recorder.events == [("click", (Point(1, 1), "left", 1))]


class TestStepOutcome:
    def test_success(self) -> None:
        outcome = StepOutcome("a", ActionResult.success(1), elapsed=0.1)
        assert outcome.ok is True
        assert outcome.status == "success"
        assert outcome.message == ""

    def test_failure(self) -> None:
        outcome = StepOutcome("a", ActionResult.not_found("没找到"))
        assert outcome.ok is False
        assert outcome.status == "not_found"
        assert outcome.message == "没找到"

    def test_skip_counts_as_ok(self) -> None:
        outcome = StepOutcome(
            "a", ActionResult.not_found("跳过"), skipped=True, skip_reason="条件不满足"
        )
        assert outcome.ok is True
        assert outcome.status == "skipped"
        assert outcome.message == "条件不满足"

    def test_to_dict_includes_children(self) -> None:
        child = StepOutcome("child", ActionResult.success(1))
        parent = StepOutcome("parent", ActionResult.success(2), children=[child])
        payload = parent.to_dict()
        assert payload["children"][0]["step"] == "child"
        assert payload["elapsed"] == 0.0


class TestExecutorAndJournal:
    def test_executor_attaches_to_context(self, ctx) -> None:
        executor = Executor(ctx, hooks=ExecutorHooks(), journal=MemoryJournal())
        ctx.executor = executor
        assert executor.dry_run is False
        assert executor.outcomes == []
        executor.close()

    def test_executor_run_returns_an_outcome(self, ctx) -> None:
        executor = Executor(ctx)
        outcome = executor.run(ClickStep(Point(1, 1)))
        assert outcome.ok is True
        assert outcome.attempts == 1

    def test_run_many_is_a_plain_loop(self, ctx, input_recorder) -> None:
        executor = Executor(ctx)
        outcomes = executor.run_many([ClickStep(Point(1, 1)), ClickStep(Point(2, 2))])
        assert [o.status for o in outcomes] == ["success", "success"]
        assert len(input_recorder.events) == 2

    def test_journal_entry_to_dict(self) -> None:
        entry = JournalEntry(step="点开始", status="success", ts=1.2345678, tick=5, elapsed=0.01)
        payload = entry.to_dict()
        assert payload["step"] == "点开始"
        assert payload["ts"] == 1.234568
        assert payload["tick"] == 5

    def test_memory_journal_records(self) -> None:
        journal = MemoryJournal()
        journal.record(JournalEntry(step="a", status="success", ts=0.0))
        journal.record(JournalEntry(step="b", status="not_found", ts=1.0))
        assert [e.step for e in journal.entries] == ["a", "b"]
        journal.clear()
        assert journal.entries == []

    def test_null_journal_swallows_everything(self) -> None:
        journal = NullJournal()
        journal.record(JournalEntry(step="a", status="success", ts=0.0))
        journal.close()  # 不应抛异常

    def test_journal_is_a_context_manager(self) -> None:
        with MemoryJournal() as journal:
            journal.record(JournalEntry(step="a", status="success", ts=0.0))
        assert len(journal.entries) == 1


# --------------------------------------------------------------------------- #
# 步骤本体（在假后端上真跑一遍）
# --------------------------------------------------------------------------- #
class TestStepsRun:
    def test_click_step_uses_source_coordinates(self, ctx, input_recorder) -> None:
        """``ClickStep`` 收的是**逻辑**坐标，但下发的是**源**坐标。

        这个项目最容易搞错的就是这两个基准，所以钉死在测试里：
        坐标来自配置时才换算，来自截图时绝不二次换算。
        """
        outcome = ctx.executor.run(ClickStep(Point(10, 20)))
        assert outcome.ok is True
        assert outcome.attempts == 1
        # 假后端 640x360、没配 logic_size -> 源坐标 == 逻辑坐标
        assert input_recorder.events == [("click", (Point(10, 20), "left", 1))]
        assert outcome.action.get("point") == Point(10, 20)

    def test_image_click_uses_hit_point_as_source(self, ctx, input_recorder, matcher) -> None:
        """命中点（源坐标）直接下发，**不能再换算一次**。"""
        matcher.matches = {"a.png": (Point(100, 50), 0.99)}
        outcome = ctx.executor.run(ClickImageStep("a.png", offset=(5, -5)))
        assert outcome.ok is True
        assert input_recorder.events == [("click", (Point(105, 45), "left", 1))]

    def test_image_click_does_not_click_when_missing(self, ctx, input_recorder) -> None:
        """找不到图就绝不下发 —— 识图脚本最危险的就是"就近点一下试试"。"""
        outcome = ctx.executor.run(ClickImageStep("nope.png"))
        assert outcome.status == "not_found"
        assert input_recorder.events == []

    def test_image_click_invalidates_the_frame(self, ctx) -> None:
        """点完画面就变了：当前帧必须作废，否则后续步骤看的是旧图。"""
        ctx.frame()
        assert ctx.current_frame is not None
        ctx.executor.run(ClickImageStep("a.png"))
        assert ctx.current_frame is None

    def test_query_step_writes_blackboard(self, ctx) -> None:
        outcome = ctx.executor.run(QueryStep(ImageQuery("a.png"), save_as="found"))
        assert outcome.ok is True
        assert ctx.blackboard.get("found") is not None

    def test_query_step_saves_none_when_missing(self, ctx) -> None:
        """没命中也要写黑板：那里存的是"这一轮看到的值"，没看到也是信息。"""
        ctx.executor.run(QueryStep(ImageQuery("nope.png"), save_as="found"))
        assert ctx.blackboard.get("found") is None
        assert "found" in ctx.blackboard

    def test_query_step_is_not_blocked_by_dry_run(self, ctx) -> None:
        """空跑只拦**动作**步骤，查询照跑 —— 否则流程决策就没依据了。"""
        ctx.executor.dry_run = True
        outcome = ctx.executor.run(QueryStep(ImageQuery("a.png"), save_as="v"))
        assert outcome.ok is True
        assert ctx.blackboard.get("v") is not None

    def test_capture_step_forces_a_new_frame(self, ctx) -> None:
        before = ctx.frame()
        captured = ctx.capture_count
        outcome = ctx.executor.run(CaptureStep())
        assert outcome.ok is True
        assert ctx.capture_count == captured + 1
        assert ctx.current_frame is not before

    def test_key_step_single_and_combo(self, ctx, input_recorder) -> None:
        ctx.executor.run(KeyStep("enter"))
        ctx.executor.run(KeyStep(["ctrl", "s"]))
        assert input_recorder.events == [
            ("press_key", ("enter", 1)),
            ("hotkey", ["ctrl", "s"]),
        ]

    def test_wait_step_seconds(self, ctx) -> None:
        assert ctx.executor.run(WaitStep(seconds=0.0)).ok is True

    def test_wait_step_for_query(self, ctx) -> None:
        outcome = ctx.executor.run(
            WaitStep(query=ImageQuery("a.png"), timeout=0.05, interval=0.01)
        )
        assert outcome.ok is True

    def test_wait_step_timeout_is_a_failure(self, ctx) -> None:
        outcome = ctx.executor.run(
            WaitStep(query=ImageQuery("nope.png"), timeout=0.05, interval=0.01)
        )
        assert outcome.status == "timeout"
        assert outcome.ok is False

    def test_wait_step_disappear(self, ctx) -> None:
        outcome = ctx.executor.run(
            WaitStep(query=ImageQuery("nope.png"), disappear=True, timeout=0.05, interval=0.01)
        )
        assert outcome.ok is True, "本来就不在屏幕上，就算已经消失了"

    def test_composite_step_runs_children_through_executor(self, ctx, input_recorder) -> None:
        """子步骤要走 executor：否则它们各自的 policy / 记账全失效。"""
        composite = CompositeStep(
            [ClickStep(Point(1, 1), name="第一下"), ClickStep(Point(2, 2), name="第二下")]
        )
        outcome = ctx.executor.run(composite)
        assert outcome.ok is True
        assert [c.step for c in outcome.children] == ["第一下", "第二下"]
        assert [c.step for c in composite.child_outcomes()] == ["第一下", "第二下"]
        assert len(input_recorder.events) == 2
        assert all(c.attempts == 1 for c in outcome.children)

    def test_composite_aborts_on_failure(self, ctx, input_recorder) -> None:
        composite = CompositeStep([ClickImageStep("nope.png"), ClickStep(Point(1, 1))])
        outcome = ctx.executor.run(composite)
        assert outcome.ok is False
        assert len(outcome.children) == 1, "abort_on_failure 时后面的子步骤不该跑"
        assert input_recorder.events == []

    def test_composite_continues_when_asked(self, ctx, input_recorder) -> None:
        composite = CompositeStep(
            [ClickImageStep("nope.png"), ClickStep(Point(1, 1))], abort_on_failure=False
        )
        outcome = ctx.executor.run(composite)
        assert outcome.ok is False
        assert len(outcome.children) == 2
        assert len(input_recorder.events) == 1

    def test_conditional_step_picks_then(self, ctx, input_recorder) -> None:
        step = ConditionalStep(
            ImageQuery("a.png"), [ClickStep(Point(1, 1))], [ClickStep(Point(9, 9))]
        )
        outcome = ctx.executor.run(step)
        assert outcome.ok is True
        assert outcome.result.meta.get("branch") == "then"
        assert input_recorder.events == [("click", (Point(1, 1), "left", 1))]

    def test_conditional_step_picks_else(self, ctx, input_recorder) -> None:
        step = ConditionalStep(
            ImageQuery("nope.png"), [ClickStep(Point(1, 1))], [ClickStep(Point(9, 9))]
        )
        outcome = ctx.executor.run(step)
        assert outcome.result.meta.get("branch") == "else"
        assert input_recorder.events == [("click", (Point(9, 9), "left", 1))]

    def test_conditional_step_with_empty_branch(self, ctx) -> None:
        outcome = ctx.executor.run(ConditionalStep(ImageQuery("a.png"), []))
        assert outcome.ok is True
        assert "分支为空" in outcome.message

    def test_function_step_receives_context(self, ctx) -> None:
        seen: list[object] = []

        def probe(context):
            seen.append(context)
            return ActionResult.success("ok")

        outcome = ctx.executor.run(FunctionStep(probe, name="探针"))
        assert outcome.ok is True
        assert seen == [ctx]


# --------------------------------------------------------------------------- #
# 执行器的四件事：跳过 / 重试 / 超时 / 失败处理
# --------------------------------------------------------------------------- #
class TestExecutorPolicy:
    def test_retries_until_success(self, ctx) -> None:
        calls: list[int] = []

        def flaky(context):
            calls.append(1)
            return ActionResult.success(1) if len(calls) >= 3 else ActionResult.not_found("还没好")

        step = FunctionStep(
            flaky, policy=StepPolicy(retry=RetryPolicy(max_attempts=5, interval=0.0))
        )
        outcome = ctx.executor.run(step)
        assert outcome.ok is True
        assert outcome.attempts == 3

    def test_stops_after_max_attempts(self, ctx) -> None:
        calls: list[int] = []

        def always_missing(context):
            calls.append(1)
            return ActionResult.not_found("一直没有")

        step = FunctionStep(
            always_missing, policy=StepPolicy(retry=RetryPolicy(max_attempts=3, interval=0.0))
        )
        outcome = ctx.executor.run(step)
        assert outcome.ok is False
        assert outcome.attempts == 3
        assert len(calls) == 3

    def test_retry_on_filter_is_respected(self, ctx) -> None:
        """``retry_on`` 是枚举而不是"非成功即可重试"：不在名单里的状态不重试。"""
        calls: list[int] = []

        def errored(context):
            calls.append(1)
            return ActionResult.error("后端炸了")

        step = FunctionStep(
            errored,
            policy=StepPolicy(
                retry=RetryPolicy(max_attempts=5, interval=0.0, retry_on=(ActionStatus.TIMEOUT,))
            ),
        )
        outcome = ctx.executor.run(step)
        assert outcome.attempts == 1
        assert len(calls) == 1

    def test_timeout_budget_caps_retries(self, ctx) -> None:
        """``policy.timeout`` 是这一整步（含等待）的总预算。"""
        calls: list[int] = []

        def slow_failure(context):
            calls.append(1)
            context.sleep(0.02)
            return ActionResult.not_found("慢失败")

        step = FunctionStep(
            slow_failure,
            policy=StepPolicy(timeout=0.05, retry=RetryPolicy(max_attempts=99, interval=0.02)),
        )
        outcome = ctx.executor.run(step)
        assert outcome.ok is False
        assert outcome.attempts < 99
        assert len(calls) == outcome.attempts

    def test_precondition_unsatisfied_skips(self, ctx, input_recorder) -> None:
        step = ClickStep(Point(1, 1), policy=StepPolicy(precondition=ImageQuery("nope.png")))
        outcome = ctx.executor.run(step)
        assert outcome.skipped is True
        assert outcome.ok is True
        assert "precondition" in outcome.skip_reason
        assert input_recorder.events == []

    def test_precondition_error_does_not_skip(self, ctx, input_recorder) -> None:
        """条件求值出错时**不跳过**：配置坏了该让它按正常路径失败并留痕，
        而不是静默跳过 —— 跳过在报告里长得像"本来就不需要做"。"""

        class Boom:
            def run(self, frame):
                raise RuntimeError("炸")

        step = ClickStep(Point(1, 1), policy=StepPolicy(precondition=Boom()))
        outcome = ctx.executor.run(step)
        assert outcome.skipped is False
        assert len(input_recorder.events) == 1

    def test_precondition_satisfied_runs(self, ctx, input_recorder) -> None:
        step = ClickStep(Point(1, 1), policy=StepPolicy(precondition=ImageQuery("a.png")))
        assert ctx.executor.run(step).skipped is False
        assert len(input_recorder.events) == 1

    def test_skip_if_satisfied_skips(self, ctx, input_recorder) -> None:
        step = ClickStep(Point(1, 1), policy=StepPolicy(skip_if=ImageQuery("a.png")))
        outcome = ctx.executor.run(step)
        assert outcome.skipped is True
        assert input_recorder.events == []

    def test_skipped_outcomes_are_journalled(self, ctx) -> None:
        """跳过也要留痕：报告里看不到某一步时，"它跑没跑"是最要紧的问题。"""
        journal = MemoryJournal()
        ctx.executor.journal = journal
        ctx.executor.run(ClickStep(Point(1, 1), policy=StepPolicy(skip_if=ImageQuery("a.png"))))
        assert journal.entries[-1].status == "skipped"
        assert "skip_if" in journal.entries[-1].message

    def test_abort_tick_does_not_raise(self, ctx) -> None:
        step = FunctionStep(
            lambda context: ActionResult.not_found("没成"),
            policy=StepPolicy(on_error=ErrorMode.ABORT_TICK),
        )
        outcome = ctx.executor.run(step)
        assert outcome.ok is False
        assert ctx.stop_requested is False

    def test_raise_mode_raises_step_failed(self, ctx) -> None:
        step = FunctionStep(
            lambda context: ActionResult.not_found("没成"), policy=StepPolicy.must()
        )
        with pytest.raises(StepFailed):
            ctx.executor.run(step)

    def test_require_success_upgrades_a_gentle_policy(self, ctx) -> None:
        step = FunctionStep(
            lambda context: ActionResult.not_found("没成"),
            policy=StepPolicy(require_success=True, on_error=ErrorMode.RAISE),
        )
        with pytest.raises(StepFailed):
            ctx.executor.run(step)

    def test_stop_flow_requests_stop(self, ctx) -> None:
        step = FunctionStep(
            lambda context: ActionResult.not_found("没成"),
            policy=StepPolicy(on_error=ErrorMode.STOP_FLOW),
        )
        outcome = ctx.executor.run(step)
        assert outcome.ok is False
        assert ctx.stop_requested is True

    def test_dry_run_blocks_actions_but_not_queries(self, ctx, input_recorder) -> None:
        ctx.executor.dry_run = True
        blocked = ctx.executor.run(ClickStep(Point(1, 1)))
        allowed = ctx.executor.run(QueryStep(ImageQuery("a.png")))
        assert blocked.ok is True
        assert blocked.result.meta.get("dry_run") is True
        assert input_recorder.events == []
        assert allowed.ok is True

    def test_dry_run_treats_unknown_steps_as_actions(self, ctx) -> None:
        """自定义步骤没声明 ``performs_action`` 时默认按"会动手"拦下来 ——
        宁可多拦一个，也不能让空跑真的去点游戏。"""

        class Custom(Step):
            def run(self, context):
                return ActionResult.success("真的执行了")

        ctx.executor.dry_run = True
        outcome = ctx.executor.run(Custom(name="自定义"))
        assert outcome.result.meta.get("dry_run") is True

    def test_hooks_fire_in_order(self, ctx) -> None:
        seen: list[str] = []
        ctx.executor.hooks = ExecutorHooks(
            before_step=lambda c, s: seen.append(f"before:{s.name}"),
            after_step=lambda c, o: seen.append(f"after:{o.step}"),
        )
        ctx.executor.run(ClickStep(Point(1, 1), name="点一下"))
        assert seen == ["before:点一下", "after:点一下"]

    def test_on_failure_hook_only_on_failure(self, ctx) -> None:
        seen: list[str] = []
        ctx.executor.hooks = ExecutorHooks(on_failure=lambda c, s, o: seen.append(o.step))
        ctx.executor.run(ClickImageStep("nope.png", name="找不到"))
        ctx.executor.run(ClickStep(Point(1, 1), name="能找到"))
        assert seen == ["找不到"]

    def test_missing_executor_skips_steps(self, ctx) -> None:
        """没有执行器时不炸、也不假装跑了 —— 这个分支只该出现在临时脚本里。"""
        from gamebot.flow import FlowEngine

        ctx.executor = None
        scenario = _tiny_scenario()
        engine = FlowEngine(scenario, ctx)
        assert engine._run_steps(scenario.graph.nodes["home"].steps, "home") == []


# --------------------------------------------------------------------------- #
# YAML -> Step
# --------------------------------------------------------------------------- #
class TestStepFromDict:
    def test_click_image_step(self) -> None:
        step = step_from_dict(
            {"type": "ClickImageStep", "template": "a.png", "region": [1, 2, 3, 4]}
        )
        assert isinstance(step, ClickImageStep)
        assert step.region == Region(1, 2, 3, 4)

    def test_click_step_point_list(self) -> None:
        assert step_from_dict({"type": "ClickStep", "point": [10, 20]}).point == Point(10, 20)

    def test_policy_subdict(self) -> None:
        step = step_from_dict(
            {
                "type": "ClickStep",
                "point": [1, 1],
                "policy": {
                    "on_error": "stop_flow",
                    "retry": {"max_attempts": 3, "interval": 0.5, "retry_on": ["not_found"]},
                },
            }
        )
        assert step.policy.on_error is ErrorMode.STOP_FLOW
        assert step.policy.retry.max_attempts == 3
        assert step.policy.retry.retry_on == (ActionStatus.NOT_FOUND,)

    def test_precondition_query_subdict(self) -> None:
        step = step_from_dict(
            {
                "type": "ClickStep",
                "point": [1, 1],
                "policy": {"precondition": {"type": "ImageQuery", "template": "a.png"}},
            }
        )
        assert isinstance(step.policy.precondition, ImageQuery)

    def test_composite_nested_steps(self) -> None:
        step = step_from_dict(
            {
                "type": "CompositeStep",
                "steps": [
                    {"type": "KeyStep", "key": "enter"},
                    {"type": "ClickStep", "point": [1, 1]},
                ],
            }
        )
        assert isinstance(step, CompositeStep)
        assert [type(s).__name__ for s in step.steps] == ["KeyStep", "ClickStep"]

    def test_conditional_nested(self) -> None:
        step = step_from_dict(
            {
                "type": "ConditionalStep",
                "when": {"type": "ImageQuery", "template": "a.png"},
                "then_steps": [{"type": "ClickStep", "point": [1, 1]}],
            }
        )
        assert isinstance(step, ConditionalStep)
        assert isinstance(step.when, ImageQuery)
        assert len(step.then_steps) == 1

    def test_wait_step_with_query(self) -> None:
        step = step_from_dict(
            {"type": "WaitStep", "query": {"type": "ImageQuery", "template": "a.png"}}
        )
        assert isinstance(step.query, ImageQuery)

    def test_missing_type_raises(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            step_from_dict({"template": "a.png"})
        assert "缺少 type" in str(excinfo.value)

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            step_from_dict({"type": "NoSuchStep"})
        assert "未登记" in str(excinfo.value)

    def test_unknown_field_raises(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            step_from_dict({"type": "ClickStep", "point": [1, 1], "点点点": 1})
        assert "未知字段" in str(excinfo.value)

    def test_bad_region_raises(self) -> None:
        with pytest.raises(ConfigError):
            step_from_dict({"type": "ClickImageStep", "template": "a.png", "region": [1, 2]})

    def test_bad_on_error_value_raises(self) -> None:
        with pytest.raises(ConfigError):
            step_from_dict({"type": "ClickStep", "point": [1, 1], "policy": {"on_error": "瞎写"}})


# --------------------------------------------------------------------------- #
# 失败帧：上限 + 写进 journal
# --------------------------------------------------------------------------- #
class TestFailureFrames:
    """``save_frames_on_error`` 的两个坑。

    这条路径原来是"存了一堆图但 journal 里没有文件名"（帧在写 journal
    **之后**才存），而且**没有留存上限**（跑一晚上就是几千张全尺寸 PNG）。
    两者都不报错，只是慢慢变难受 —— 所以用测试钉住。
    """

    def _failing(self, ctx):
        return FunctionStep(lambda c: ActionResult.error("故意失败"), name="会失败的步骤")

    def _arm(self, ctx, tmp_path, journal=None):
        """准备好"有当帧 + 开了存帧 + 有 journal"的状态。

        **必须先 ``ctx.capture()`` 造一帧**：``ctx`` 这个 fixture 不抓帧，
        而存失败帧的前提就是"有当前帧"。忘了这一步的话整条路径会静默跳过 ——
        测试会"通过"但什么都没验到，那比失败更糟。
        """
        ctx.config.paths.screenshots = tmp_path
        ctx.capture()
        ctx.executor.journal = journal or MemoryJournal()
        ctx.executor.save_frames_on_error = True

    def test_frame_path_lands_in_the_journal_entry(self, ctx, tmp_path) -> None:
        journal = MemoryJournal()
        self._arm(ctx, tmp_path, journal)

        ctx.executor.run(self._failing(ctx))

        (entry,) = journal.entries
        assert entry.status != "success"
        assert entry.frame_path, "journal 里必须能拿到当帧图的路径"
        assert entry.frame_path.endswith(".png")

    def test_no_frame_when_option_is_off(self, ctx, tmp_path) -> None:
        """默认关：不存图，也不报错。"""
        ctx.config.paths.screenshots = tmp_path
        ctx.capture()
        journal = MemoryJournal()
        ctx.executor.journal = journal
        ctx.executor.save_frames_on_error = False

        ctx.executor.run(self._failing(ctx))

        (entry,) = journal.entries
        assert entry.frame_path == ""
        assert list(tmp_path.glob("*.png")) == []

    def test_successful_steps_do_not_save_frames(self, ctx, tmp_path) -> None:
        """成功的步骤存图没有诊断价值，只会堆盘。"""
        ctx.config.paths.screenshots = tmp_path
        ctx.capture()
        ctx.executor.journal = MemoryJournal()
        ctx.executor.save_frames_on_error = True

        ctx.executor.run(ClickStep(Point(1, 1), name="点一下"))

        assert list(tmp_path.glob("*.png")) == []

    def test_old_failure_frames_are_pruned(self, ctx, tmp_path) -> None:
        """留存上限：留最近的，不无限涨。"""
        self._arm(ctx, tmp_path)

        for _ in range(30):
            ctx.executor.run(self._failing(ctx))

        kept = sorted(tmp_path.glob("fail_*.png"))
        assert 0 < len(kept) <= ctx.executor._frame_keep

    def test_pruning_never_touches_other_files(self, ctx, tmp_path) -> None:
        """**只删自己写的 ``fail_*.png``** —— 同一个目录里还躺着识图记录
        （``match_*.png``）和用户手工截的图。"""
        manual = tmp_path / "manual.png"
        manual.write_bytes(b"x")
        match = tmp_path / "match_00001.png"
        match.write_bytes(b"x")

        self._arm(ctx, tmp_path)
        for _ in range(30):
            ctx.executor.run(self._failing(ctx))

        assert manual.is_file(), "手工截的图不能被删"
        assert match.is_file(), "识图记录不能被删"
        assert len(list(tmp_path.glob("fail_*.png"))) <= ctx.executor._frame_keep

    def test_keep_limit_follows_the_recorder(self, ctx, tmp_path) -> None:
        """失败帧的上限跟着识图记录走，不另加一个要用户理解的旋钮。"""
        ctx.config.paths.screenshots = tmp_path

        class _Recorder:
            keep = 20

        ctx.recorder = _Recorder()
        assert ctx.executor._frame_keep == 100

        ctx.recorder = None
        assert ctx.executor._frame_keep == 20


# --------------------------------------------------------------------------- #
# journal 落盘
# --------------------------------------------------------------------------- #
class TestJournalSerialization:
    def test_record_outcome_maps_fields(self, ctx) -> None:
        journal = MemoryJournal()
        ctx.executor.journal = journal
        ctx.executor.run(ClickStep(Point(3, 4), name="点一下"))
        ctx.executor.run(ClickStep(Point(1, 1), policy=StepPolicy(skip_if=ImageQuery("a.png"))))

        success, skipped = journal.entries
        assert success.step == "点一下"
        assert success.status == "success"
        assert success.attempts == 1
        assert success.action.get("point") == Point(3, 4)
        assert "action" not in success.action, "meta 里的 action 子字典不该被套两层"
        assert skipped.status == "skipped"
        assert skipped.meta.get("skipped") is True

    def test_jsonl_journal_round_trip(self, tmp_path) -> None:
        """``ensure_ascii=False`` —— 中文步骤名不该在文件里变成 \\uXXXX。"""
        path = tmp_path / "logs" / "run.jsonl"
        with JsonlJournal(path) as journal:
            journal.record(JournalEntry(step="点击开始", status="success", ts=1.5))
            journal.record(JournalEntry(step="第二行", status="not_found", ts=2.5, tick=7))

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert "点击开始" in lines[0]
        assert "\\u" not in lines[0]
        payload = json.loads(lines[1])
        assert payload["step"] == "第二行"
        assert payload["tick"] == 7
        assert payload["status"] == "not_found"

    def test_jsonl_journal_appends(self, tmp_path) -> None:
        path = tmp_path / "a.jsonl"
        with JsonlJournal(path) as journal:
            journal.record(JournalEntry(step="一", status="success", ts=1.0))
        with JsonlJournal(path) as journal:
            journal.record(JournalEntry(step="二", status="success", ts=2.0))
        assert len(path.read_text(encoding="utf-8").splitlines()) == 2

    def test_jsonl_journal_serializes_odd_meta(self, tmp_path) -> None:
        """meta 里混进 Point / Path 不该把 journal 弄崩（``default=str``）。"""
        path = tmp_path / "b.jsonl"
        with JsonlJournal(path) as journal:
            journal.record(
                JournalEntry(step="x", status="success", ts=1.0, meta={"point": Point(1, 2)})
            )
        assert "Point" in path.read_text(encoding="utf-8")

    def test_attach_frame_without_directory_is_a_noop(self, ctx) -> None:
        journal = MemoryJournal()
        outcome = StepOutcome("s", ActionResult.success(1))
        assert journal.attach_frame(outcome, ctx.frame()) == ""
        assert outcome.frame_path == ""

    def test_attach_frame_saves_and_records_path(self, ctx, tmp_path) -> None:
        journal = MemoryJournal()
        outcome = StepOutcome("步骤/带斜杠", ActionResult.success(1))
        path = journal.attach_frame(outcome, ctx.frame(), directory=tmp_path / "shots")
        assert path.endswith(".png")
        assert outcome.frame_path == path
        assert (tmp_path / "shots").is_dir()

    def test_step_outcome_to_dict_includes_action_and_frame(self) -> None:
        outcome = StepOutcome("s", ActionResult.success(1), action={"point": [1, 2]})
        outcome.frame_path = "logs/a.png"
        payload = outcome.to_dict()
        assert payload["action"] == {"point": [1, 2]}
        assert payload["frame"] == "logs/a.png"

    def test_step_outcome_of_collects_action_meta(self) -> None:
        result = ActionResult.success(1, template="a.png", score=0.9, point=Point(3, 3))
        outcome = StepOutcome.of("点 a", result)
        assert outcome.action["template"] == "a.png"
        assert outcome.action["point"] == Point(3, 3)
        assert "score" not in outcome.action


def _tiny_scenario():
    """一个只有一个节点的最小场景（给"没有执行器"那条分支用）。"""
    from gamebot.flow import Graph, Node, Scenario
    from gamebot.state import Page, PageTree

    tree = PageTree()
    tree.add(Page("home", queries=(ImageQuery("a.png"),)))
    graph = Graph(initial="home")
    graph.add_node(Node("home", page="home", steps=[ClickStep(Point(1, 1))]))
    return Scenario(name="tiny", tree=tree, graph=graph)
