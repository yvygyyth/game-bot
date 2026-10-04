"""流程层已实现部分的测试：转移规则、节点、蓝图、状态机、报告。"""

from __future__ import annotations

import pytest

from gamebot.exceptions import FlowError
from gamebot.flow.definition import FlowDefinition, UnknownPolicy
from gamebot.flow.engine import EngineOptions, RunReport, StopReason
from gamebot.flow.machine import FlowMachine
from gamebot.flow.node import FlowNode
from gamebot.flow.transition import Transition, TransitionKind
from gamebot.state.definition import StateDefinition
from gamebot.state.snapshot import StateChange
from gamebot.types import ActionResult


@pytest.fixture
def definition() -> FlowDefinition:
    return FlowDefinition(
        name="t",
        initial="menu",
        states=[
            StateDefinition("menu", priority=10),
            StateDefinition("battle", priority=20),
            StateDefinition("result", priority=30),
            StateDefinition("closed", terminal=True),
        ],
        nodes={"menu": FlowNode("menu", description="主界面")},
        transitions=[
            Transition(target="battle", sources=("menu",), priority=10, label="开打"),
            Transition(target="result", sources=("battle",), priority=30, label="结算"),
            Transition(target="closed", sources=("result",), priority=50),
            Transition(target="menu", sources=(), priority=5, kind=TransitionKind.RECOVERY),
        ],
        stop_states=("closed",),
        tick_interval=0.5,
        max_runtime=60.0,
        on_unknown=UnknownPolicy.RECOVERY,
        recovery_state="menu",
    )


class TestTransition:
    def test_applies_to(self) -> None:
        specific = Transition(target="b", sources=("a",))
        assert specific.applies_to("a") is True
        assert specific.applies_to("c") is False
        wildcard = Transition(target="b")
        assert wildcard.applies_to("anything") is True

    def test_display(self) -> None:
        assert Transition(target="b", sources=("a",), label="开打").display == "开打"
        assert Transition(target="b", sources=("a",)).display == "a -> b"
        assert Transition(target="b").display == "* -> b"

    def test_to_dict(self) -> None:
        payload = Transition(target="b", sources=("a",), cooldown=1.0, max_times=3).to_dict()
        assert payload["from"] == ["a"]
        assert payload["to"] == "b"
        assert payload["kind"] == "normal"
        assert payload["cooldown"] == 1.0

    def test_kind_values(self) -> None:
        assert TransitionKind.RECOVERY.value == "recovery"


class TestFlowNode:
    def test_passive(self) -> None:
        assert FlowNode("loading").is_passive is True

    def test_not_passive_with_steps(self) -> None:
        from gamebot.execution.step import ClickStep
        from gamebot.types import Point

        assert FlowNode("a", steps=[ClickStep(Point(1, 1))]).is_passive is False

    def test_to_dict(self) -> None:
        payload = FlowNode("a", max_visits=3, cooldown=0.5).to_dict()
        assert payload["state"] == "a"
        assert payload["steps"] == 0
        assert payload["max_visits"] == 3


class TestFlowDefinition:
    def test_helpers(self, definition: FlowDefinition) -> None:
        assert definition.state_ids == ["menu", "battle", "result", "closed"]
        assert definition.state("battle") is not None
        assert definition.state("nope") is None
        assert definition.node("menu") is not None
        assert definition.node("battle") is None

    def test_transitions_from_filters_by_source_and_sorts(self, definition: FlowDefinition) -> None:
        # battle 状态下：result(30) 与通配的 menu(5) 都适用，按优先级降序
        assert [t.target for t in definition.transitions_from("battle")] == ["result", "menu"]

    def test_transitions_from_prefers_higher_priority(self, definition: FlowDefinition) -> None:
        # menu 状态下：menu->battle(10) 先于通配的 recovery(5)
        assert [t.target for t in definition.transitions_from("menu")] == ["battle", "menu"]

    def test_transitions_from_unknown_state_only_matches_wildcards(
        self, definition: FlowDefinition
    ) -> None:
        assert [t.target for t in definition.transitions_from("不存在的状态")] == ["menu"]

    def test_wildcard_transition_matches_every_state(self, definition: FlowDefinition) -> None:
        assert any(t.target == "menu" for t in definition.transitions_from("result"))

    def test_to_dict(self, definition: FlowDefinition) -> None:
        payload = definition.to_dict()
        assert payload["name"] == "t"
        assert payload["on_unknown"] == "recovery"
        assert len(payload["transitions"]) == 4

    def test_validate_is_not_implemented_yet(self, definition: FlowDefinition) -> None:
        with pytest.raises(NotImplementedError):
            definition.validate()


class TestFlowMachine:
    def test_starts_at_initial(self, definition: FlowDefinition) -> None:
        machine = FlowMachine(definition)
        assert machine.current == "menu"
        assert machine.visits_of("menu") == 0

    def test_candidates(self, definition: FlowDefinition) -> None:
        machine = FlowMachine(definition)
        assert [t.target for t in machine.candidates()] == ["battle", "menu"]

    def test_is_terminal(self, definition: FlowDefinition) -> None:
        machine = FlowMachine(definition)
        assert machine.is_terminal("closed") is True
        assert machine.is_terminal("menu") is False

    def test_availability_by_max_times(self, definition: FlowDefinition) -> None:
        machine = FlowMachine(definition)
        transition = definition.transitions[0]
        assert machine.is_available(transition, now=0.0) == (True, "")
        machine.times_fired[0] = 3
        transition_limited = Transition(target="b", sources=("a",), max_times=3)
        machine.definition.transitions.append(transition_limited)
        index = len(machine.definition.transitions) - 1
        machine.times_fired[index] = 3
        available, reason = machine.is_available(transition_limited, now=0.0)
        assert available is False
        assert "最大次数" in reason

    def test_availability_by_cooldown(self, definition: FlowDefinition) -> None:
        machine = FlowMachine(definition)
        cooled = Transition(target="b", sources=("a",), cooldown=2.0)
        machine.definition.transitions.append(cooled)
        index = len(machine.definition.transitions) - 1
        machine.last_fired_at[index] = 100.0
        available, reason = machine.is_available(cooled, now=101.0)
        assert available is False
        assert "冷却" in reason
        assert machine.is_available(cooled, now=103.0)[0] is True

    def test_record_change_updates_current_and_visits(self, definition: FlowDefinition) -> None:
        machine = FlowMachine(definition)
        machine.record_change(StateChange(from_state="menu", to_state="battle", at=1.0))
        assert machine.current == "battle"
        assert machine.visits_of("battle") == 1

    def test_select_and_apply_not_implemented(self, definition: FlowDefinition) -> None:
        machine = FlowMachine(definition)
        with pytest.raises(NotImplementedError):
            machine.select(None, None)  # type: ignore[arg-type]
        with pytest.raises(NotImplementedError):
            machine.apply(definition.transitions[0])

    def test_reset(self, definition: FlowDefinition) -> None:
        machine = FlowMachine(definition)
        machine.times_fired[0] = 2
        machine.current = "battle"
        machine.reset()
        assert machine.current == "menu"
        assert machine.times_fired == {}

    def test_to_dict(self, definition: FlowDefinition) -> None:
        payload = FlowMachine(definition).to_dict()
        assert payload["current"] == "menu"


class TestEngineOptions:
    def test_from_definition(self, definition: FlowDefinition) -> None:
        options = EngineOptions.from_definition(definition)
        assert options.tick_interval == 0.5
        assert options.max_runtime == 60.0
        assert options.on_unknown is UnknownPolicy.RECOVERY
        assert options.recovery_state == "menu"
        assert options.stop_states == ("closed",)


class TestRunReport:
    def test_duration_and_ok(self) -> None:
        report = RunReport(flow="t", started_at=100.0, ended_at=112.5)
        assert report.duration == pytest.approx(12.5)
        report.stop_reason = StopReason.STOP_STATE
        assert report.ok is True
        report.stop_reason = StopReason.ERROR
        assert report.ok is False

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
            flow="demo",
            started_at=0.0,
            ended_at=65.0,
            ticks=10,
            initial_state="menu",
            final_state="closed",
        )
        report.stop_reason = StopReason.STOP_STATE
        summary = report.summary()
        assert "demo" in summary
        assert "stop_state" in summary
        assert "1m05s" in summary

    def test_to_dict(self) -> None:
        payload = RunReport(flow="x").to_dict()
        assert payload["flow"] == "x"
        assert payload["stop_reason"] == "completed"


class TestFlowErrors:
    def test_flow_error_is_gamebot_error(self) -> None:
        from gamebot.exceptions import GameBotError

        assert issubclass(FlowError, GameBotError)
