"""执行层：步骤是函数、执行器不再有策略。

## 这个文件现在测什么

* **步骤就是函数** —— 名字取自 ``__name__``、带参数用 ``partial``；
* **执行器只做三件事** —— 调函数、记账、失败的步骤存帧；
* **某步失败就停在那里**（后续步骤的前提没了，继续跑会在错的状态上乱操作）；
* **空跑在动作下发那一刻被拦**（在原子层，不在执行层判断"像不像动作"）；
* **journal 能序列化**（那是"日志里排查"的依据）。

## 删掉了什么，为什么

原来这里 99 条里 97 条在测 ``StepPolicy`` / ``RetryPolicy`` / ``ErrorMode``
（重试次数、退避、超时预算、``skip_if`` / ``precondition`` / ``on_error`` 四种模式）
以及 ``step_from_dict``（YAML 里的步骤 DSL）。

那些东西**在真实脚本里从来没被用过**：

* ``games/`` 下那两个步骤类只是把 ``policy`` 参数原样转给基类，从没传过有内容的值；
* YAML 步骤 DSL 只有 ``config/flows/example_flow.yaml`` 在用，而它引用的模板
  根本没入库（``gamebot check`` 对它一直是失败的）。

而按新的模型（**流程 = 理想的游戏执行状态**），失败（多半是识图没命中）
应该由**上层拿实测状态去重定位**，而不是在步骤里补重试。
"""

from __future__ import annotations

import json
from functools import partial

import pytest

from gamebot.execution.builtins import click_image, run_all, sleep
from gamebot.execution.executor import Executor, ExecutorHooks, StepOutcome
from gamebot.execution.journal import JsonlJournal, NullJournal
from gamebot.execution.step import describe_step, step_name
from gamebot.types import ActionResult, Point, Region


def _ok(value=None, **meta):
    return ActionResult.success(value, **meta)


def _miss(message="没找到", **meta):
    return ActionResult.not_found(message, **meta)


class TestStepName:
    """步骤名来自 ``__name__`` —— 少一处能写歪的地方。"""

    def test_plain_function(self):
        def click_skill(ctx):
            """点技能。"""
            return _ok()

        assert step_name(click_skill) == "click_skill"
        assert describe_step(click_skill) == "点技能。"

    def test_partial_looks_inside(self):
        """``partial`` 自己没有 ``__name__``，不往里看就会显示成 "partial"。"""

        def click_named(ctx, template):
            return _ok()

        bound = partial(click_named, template="skill.png")
        assert step_name(bound) == "click_named", "partial 的名字要从里面那个函数取"

    def test_no_docstring_falls_back_to_the_name(self):
        def plain(ctx):
            return _ok()

        assert describe_step(plain) == "plain"


class TestExecutorRun:
    def test_run_returns_an_outcome(self, ctx):
        executor = Executor(ctx)

        def step(c):
            return _ok(42, action="click", point="(1, 2)")

        outcome = executor.run(step)
        assert isinstance(outcome, StepOutcome)
        assert outcome.ok is True
        assert outcome.step == "step"
        assert outcome.result.value == 42
        assert outcome.action == {"action": "click", "point": "(1, 2)"}
        assert outcome.elapsed >= 0.0

    def test_failure_is_returned_not_raised(self, ctx):
        """失败是**返回值** —— 流程层要看到它才能去重定位。"""
        executor = Executor(ctx)
        outcome = executor.run(lambda c: _miss("技能没看到"))
        assert outcome.ok is False
        assert outcome.status == "not_found"
        assert "技能没看到" in outcome.message

    def test_cancelled_propagates(self, ctx):
        """唯一会被当成异常的是**中止**：它表示"别再继续了"，不是"失败了"。"""
        from gamebot.exceptions import Cancelled

        def stop_me(c):
            raise Cancelled("用户点了停止")

        with pytest.raises(Cancelled):
            Executor(ctx).run(stop_me)

    def test_hooks_fire_in_order(self, ctx):
        seen: list[str] = []
        executor = Executor(
            ctx,
            hooks=ExecutorHooks(
                before_step=lambda c, s: seen.append("before"),
                after_step=lambda c, o: seen.append("after"),
                on_failure=lambda c, s, o: seen.append("failure"),
            ),
        )
        executor.run(lambda c: _ok())
        assert seen == ["before", "after"], "成功时不该触发 failure"

        seen.clear()
        executor.run(lambda c: _miss())
        assert seen == ["before", "after", "failure"]

    def test_outcomes_accumulate(self, ctx):
        executor = Executor(ctx)
        executor.run(lambda c: _ok())
        executor.run(lambda c: _ok())
        assert len(executor.outcomes) == 2


class TestRunManyStopsAtFailure:
    """**某步失败就停在那里** —— 后续步骤的前提（"前一步成功了"）已经没了。

    这条以前是反的：默认策略下失败会**继续跑后面的步骤**，
    于是"点技能没看到按钮"之后仍然会去点结算确认 —— 在错的状态上操作。
    """

    def test_all_success(self, ctx):
        executor = Executor(ctx)
        calls: list[str] = []

        def first(c):
            calls.append("first")
            return _ok()

        def second(c):
            calls.append("second")
            return _ok()

        outcomes = executor.run_many([first, second])
        assert calls == ["first", "second"]
        assert all(o.ok for o in outcomes)

    def test_stops_at_the_failing_step(self, ctx):
        executor = Executor(ctx)
        calls: list[str] = []

        def first(c):
            calls.append("first")
            return _ok()

        def second(c):
            calls.append("second")
            return _miss("第二步没认出来")

        def third(c):
            calls.append("third")
            return _ok()

        outcomes = executor.run_many([first, second, third])
        assert calls == ["first", "second"], "第三步不该跑"
        assert [o.ok for o in outcomes] == [True, False]
        assert outcomes[-1].step == "second"

    def test_the_failure_keeps_its_original_status(self, ctx):
        executor = Executor(ctx)
        outcomes = executor.run_many([lambda c: _miss("没命中")])
        assert outcomes[0].status == "not_found", "状态要原样保留，别改写成别的"


class TestRunAllBuiltin:
    """``run_all`` 是同一个语义的内置版本（给步骤内部组合用）。"""

    def test_stops_at_failure_and_marks_where(self, ctx):
        calls: list[str] = []

        def a(c):
            calls.append("a")
            return _ok()

        def b(c):
            calls.append("b")
            return _miss()

        result = run_all(ctx, a, b, lambda c: _ok())
        assert calls == ["a", "b"]
        assert result.ok is False
        assert result.meta["stopped_at"] == "b"
        assert result.meta["stopped_index"] == 1


class TestDryRun:
    """空跑：动作不下发，查询照常。

    拦在**原子层**（``session.dry_run``）而不是执行层判断"这一步像不像动作" ——
    后者要么看类型名、要么维护注册表，两条路都要额外一份元数据，
    漏了就会在空跑时真的去点游戏。
    """

    def test_session_flag_is_set(self, ctx):
        Executor(ctx, dry_run=True)
        assert ctx.session.dry_run is True
        Executor(ctx, dry_run=False)
        assert ctx.session.dry_run is False

    def test_click_does_not_reach_the_backend(self, ctx, input_recorder):
        def click(c):
            from gamebot.atomic import actions

            return actions.click_logic_point(c.session, Point(10, 10))

        outcome = Executor(ctx, dry_run=True).run(click)
        assert outcome.ok is True, "空跑时动作假装成功"
        assert outcome.result.meta.get("dry_run") is True
        assert input_recorder.events == [], "空跑时不能真的下发输入"

    def test_queries_still_run(self, ctx, matcher):
        """空跑要验"流程走不走得通"，那必须看到真实的识别结果。"""
        matcher.matches = {"a.png": (Point(5, 5), 0.99)}
        Executor(ctx, dry_run=True)
        found = ctx.frame().find_image("a.png")
        assert found.ok is True

    def test_sleep_still_works(self, ctx):
        """``sleep`` 不拦 —— 空跑也要能等，否则节奏完全不同。"""
        outcome = Executor(ctx, dry_run=True).run(lambda c: sleep(c, 0.01))
        assert outcome.ok is True


class TestJournal:
    def test_null_journal_swallows_everything(self, ctx):
        executor = Executor(ctx, journal=NullJournal())
        executor.run(lambda c: _ok())
        executor.run(lambda c: _miss())

    def test_jsonl_journal_writes_a_line_per_step(self, tmp_path, ctx):
        path = tmp_path / "run.jsonl"
        with JsonlJournal(path) as journal:
            executor = Executor(ctx, journal=journal)
            executor.run(lambda c: _ok(action="click", point="(1, 2)"))
            executor.run(lambda c: _miss("没命中"))

        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert len(lines) == 2
        assert lines[0]["status"] == "success"
        assert lines[0]["action"] == {"action": "click", "point": "(1, 2)"}
        assert lines[1]["status"] == "not_found"
        assert "没命中" in lines[1]["message"]

    def test_outcome_to_dict_is_json_safe(self, ctx):
        outcome = Executor(ctx).run(lambda c: _ok(1, action="click"))
        json.dumps(outcome.to_dict())  # 不能抛


class TestBuiltins:
    """内置步骤：只是"常用组合"，不是必须用的 API。"""

    def test_click_image_clicks_the_hit_point(self, ctx, matcher, input_recorder):
        matcher.matches = {"skill.png": (Point(100, 50), 0.99)}
        outcome = Executor(ctx).run(
            partial(click_image, template="skill.png", region=Region(0, 0, 200, 200))
        )

        assert outcome.ok is True
        assert input_recorder.events, "该真的点一下"
        assert outcome.action["template"] == "skill.png"

    def test_click_image_returns_not_found_when_missing(self, ctx, matcher, input_recorder):
        matcher.matches = {}
        outcome = Executor(ctx).run(partial(click_image, template="nope.png"))

        assert outcome.status == "not_found"
        assert input_recorder.events == [], "没看到就不能动手"

    def test_click_image_invalidates_the_frame(self, ctx, matcher):
        matcher.matches = {"skill.png": (Point(1, 1), 0.99)}
        before = ctx.frame().frame_id
        Executor(ctx).run(partial(click_image, template="skill.png"))
        assert ctx.frame().frame_id > before, "点完必须作废帧，否则下一步看旧图"


class TestFailureFrames:
    def test_failing_step_saves_a_frame(self, ctx, tmp_path):
        ctx.config.paths.screenshots = tmp_path / "shots"
        executor = Executor(ctx, save_frames_on_error=True)
        outcome = executor.run(lambda c: _miss())

        assert outcome.frame_path, "失败的步骤该存一张当帧"

    def test_success_does_not_save(self, ctx, tmp_path):
        ctx.config.paths.screenshots = tmp_path / "shots"
        executor = Executor(ctx, save_frames_on_error=True)
        outcome = executor.run(lambda c: _ok())
        assert outcome.frame_path == ""

    def test_saving_is_off_by_default(self, ctx, tmp_path):
        ctx.config.paths.screenshots = tmp_path / "shots"
        outcome = Executor(ctx).run(lambda c: _miss())
        assert outcome.frame_path == ""


class TestJingjiStepsUseTheSharedHelpers:
    """竞技场的步骤**别再重写"找到 → 点 → 作废帧"**。

    那三个动作 :func:`click_image` 里已经各有一份实现，重写一遍就会各错各的。

    ## 为什么这几条不用 ``ctx`` 装置

    竞技场的 roi 是**真实客户区尺寸**下的位置（2560×1369），而 ``ctx`` 装置的
    假后端只有 640×360 —— 那些框完全落在帧外，于是每次都得到"搜索区域为空"。
    那是**校验在正确工作**（框和帧不重叠 = 这个状态永远认不出来），
    不是被测代码有问题。所以这里自己建一个真实尺寸的帧。

    顺带说明一件事：**假后端的尺寸必须和脚本声明的分辨率一致**，
    否则会得到一堆"永远找不到"的假失败。
    """

    SIZE = (2560, 1369)

    def _make_ctx(self, tmp_path, matcher):
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession
        from gamebot.config.schema import AppConfig, BackendKind
        from gamebot.context import RunContext

        config = AppConfig.defaults()
        config.screen.backend = BackendKind.FAKE
        config.paths.root = tmp_path
        config.paths.logs = tmp_path / "logs"
        config.paths.screenshots = tmp_path / "logs" / "screenshots"
        config.paths.journals = tmp_path / "logs" / "journals"
        config.vision.record = False
        session = BaseSession(build_fake_backends(size=self.SIZE), matcher=matcher)
        return RunContext(session, config, frame_ttl=0.5)

    def test_create_team_clicks_through_the_shared_helper(self, tmp_path, matcher):
        """``create_team`` 命中就点、并把模板名带进 meta（journal 靠它）。"""
        from games.mingjiangsha.jingji.steps import create_team
        from games.mingjiangsha.jingji.templates import T_BEFORE_CREATE

        matcher.matches = {T_BEFORE_CREATE: (Point(2300, 880), 0.95)}
        run_ctx = self._make_ctx(tmp_path, matcher)
        try:
            outcome = Executor(run_ctx).run(create_team)
        finally:
            run_ctx.close()

        assert outcome.ok is True, outcome.message
        assert outcome.action["template"] == T_BEFORE_CREATE

    def test_create_team_reports_not_found_when_missing(self, tmp_path, matcher):
        """没命中就如实 ``not_found`` —— 上层会拿实测状态去重定位，不在这里重试。"""
        from games.mingjiangsha.jingji.steps import create_team

        matcher.matches = {}
        run_ctx = self._make_ctx(tmp_path, matcher)
        try:
            outcome = Executor(run_ctx).run(create_team)
        finally:
            run_ctx.close()

        assert outcome.ok is False
        assert outcome.status == "not_found"


class TestEnterJingjiHoversBeforeItClicks:
    """首页那一步是**移动 → 等 → 点**，不是"找到再点"。

    玩家说明：鼠标不在卡上时熊猫头**不完整**，所以"先找图"会失败；
    而这个位置即使不完整也点得中。所以这一步必须用固定坐标，
    而且必须先移动过去（让熊猫头完整显示）。
    """

    def _run(self, tmp_path):
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession
        from gamebot.config.schema import AppConfig, BackendKind
        from gamebot.context import RunContext
        from games.mingjiangsha.game import CLIENT_SIZE
        from games.mingjiangsha.jingji.steps import enter_jingji

        config = AppConfig.defaults()
        config.screen.backend = BackendKind.FAKE
        config.paths.root = tmp_path
        config.paths.logs = tmp_path / "logs"
        config.paths.screenshots = tmp_path / "logs" / "shots"
        config.vision.record = False
        from tests.conftest import FakeMatcher

        session = BaseSession(
            build_fake_backends(size=CLIENT_SIZE), matcher=FakeMatcher()
        )
        run_ctx = RunContext(session, config, frame_ttl=0.5)
        try:
            outcome = Executor(run_ctx).run(enter_jingji)
        finally:
            run_ctx.close()
        return outcome

    def test_it_moves_then_clicks(self, tmp_path):
        """**不靠识图**也能成功 —— 这正是这一步用固定坐标的意义。"""
        outcome = self._run(tmp_path)
        assert outcome.ok is True, outcome.message
        assert outcome.action["action"] == "click"

    def test_it_uses_the_coordinate_from_step(self, tmp_path):
        """坐标只有一个出处（``enter_jingji.JINGJI_ENTRY``），别处不再写一遍。"""
        from games.mingjiangsha.jingji.steps.enter_jingji import JINGJI_ENTRY

        # 有值、落在客户区内 —— 具体数字改了不用改测试
        assert 0 < JINGJI_ENTRY.x < 2560
        assert 0 < JINGJI_ENTRY.y < 1369

