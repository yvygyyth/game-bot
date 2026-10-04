"""执行层已实现部分的测试：策略对象、步骤构造、结果记录、journal。"""

from __future__ import annotations

import pytest

from gamebot.execution.executor import Executor, ExecutorHooks, StepOutcome
from gamebot.execution.journal import JournalEntry, MemoryJournal, NullJournal
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
    WaitStep,
    step_registry,
)
from gamebot.types import ActionResult, ActionStatus, Point, Region


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

    def test_run_is_not_implemented_for_now(self, ctx) -> None:
        with pytest.raises(NotImplementedError):
            ClickStep(Point(1, 1)).run(ctx)


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

    def test_executor_run_not_implemented(self, ctx) -> None:
        executor = Executor(ctx)
        with pytest.raises(NotImplementedError):
            executor.run(ClickStep(Point(1, 1)))

    def test_run_many_is_a_plain_loop(self, ctx) -> None:
        """run_many 本身已实现，但它调用的 run 还没 —— 所以应当抛异常。"""
        executor = Executor(ctx)
        with pytest.raises(NotImplementedError):
            executor.run_many([ClickStep(Point(1, 1))])

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
