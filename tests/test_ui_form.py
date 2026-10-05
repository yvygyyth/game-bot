"""动态表单：控件行为 + 一整套"表单值真的走到步骤里"。

这个文件分两半：

* :class:`TestPanel` —— ``ParamsPanel`` 自己（四种控件、取值范围、重置）；
* :class:`TestEndToEnd` —— **表单值 → FORM.fill() → ctx.params → 步骤里的
  ctx.param()**。这一段是表单存在的全部理由，光测控件还不够：
  值在中间任何一环掉链子，用户看到的就是"我填了但它没生效"。
"""

from __future__ import annotations

import pytest

from gamebot.params import FieldKind, FormSpec, ParamField
from gamebot.ui.panels.params import ParamsPanel

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
)

#: 四种控件各来一个的样例表单。
SAMPLE = FormSpec(
    title="样例参数",
    fields=(
        ParamField("t.flag", FieldKind.BOOL, False, label="开关"),
        ParamField("t.count", FieldKind.INT, 3, label="数量", min=1, max=9),
        ParamField("t.ratio", FieldKind.FLOAT, 0.5, label="比例", min=0.0, max=1.0, step=0.1),
        ParamField("t.name", FieldKind.TEXT, "默认", label="名字"),
        ParamField(
            "t.mode",
            FieldKind.CHOICE,
            "auto",
            label="模式",
            choices=(("auto", "自动"), ("main", "主力")),
        ),
    ),
)


@pytest.fixture
def panel(qt_app):
    widget = ParamsPanel()
    widget.set_form(SAMPLE)
    try:
        yield widget
    finally:
        widget.deleteLater()


class TestPanel:
    def test_every_kind_gets_the_right_widget(self, panel):
        types = {name: type(w) for name, w in panel._editors.items()}
        assert types["t.flag"] is QCheckBox
        assert types["t.count"] is QSpinBox
        assert types["t.ratio"] is QDoubleSpinBox
        assert types["t.name"] is QLineEdit
        assert types["t.mode"] is QComboBox

    def test_initial_values_are_the_declared_defaults(self, panel):
        assert panel.values() == SAMPLE.defaults()

    def test_title_comes_from_the_spec(self, panel):
        assert panel.title() == "样例参数"

    def test_labels_are_shown(self, panel):
        """``addRow("标签", widget)`` 会自己造一个 QLabel —— 用 ``labelForField`` 找它。"""
        labels = [
            panel._fields.labelForField(panel._editors[name]).text()
            for name in ("t.flag", "t.count", "t.ratio", "t.name", "t.mode")
        ]
        assert labels == ["开关", "数量", "比例", "名字", "模式"]

    def test_editing_is_reflected_in_values(self, panel):
        panel._editors["t.flag"].setChecked(True)
        panel._editors["t.count"].setValue(7)
        panel._editors["t.ratio"].setValue(0.25)
        panel._editors["t.name"].setText("改了")
        panel._editors["t.mode"].setCurrentIndex(1)

        assert panel.values() == {
            "t.flag": True,
            "t.count": 7,
            "t.ratio": 0.25,
            "t.name": "改了",
            "t.mode": "main",
        }

    def test_choice_returns_the_value_not_the_label(self, panel):
        """显示名是给人看的，传下去的是值 —— 两者分开就是为了这个。"""
        panel._editors["t.mode"].setCurrentIndex(1)
        assert panel.values()["t.mode"] == "main"

    def test_numbers_are_clamped_by_the_control(self, panel):
        """**控件层就卡住**：用户根本输不进越界值，所以提交时不用再查一遍。"""
        panel._editors["t.count"].setValue(9999)
        panel._editors["t.ratio"].setValue(-5.0)

        assert panel.values()["t.count"] == 9
        assert panel.values()["t.ratio"] == 0.0

    def test_spinbox_range_matches_the_declaration(self, panel):
        assert (panel._editors["t.count"].minimum(), panel._editors["t.count"].maximum()) == (1, 9)
        assert panel._editors["t.count"].singleStep() == 1
        assert panel._editors["t.ratio"].singleStep() == pytest.approx(0.1)

    def test_reset_restores_the_defaults(self, panel):
        panel._editors["t.count"].setValue(9)
        panel._editors["t.flag"].setChecked(True)
        panel._editors["t.name"].setText("乱改的")

        panel.reset()

        assert panel.values() == SAMPLE.defaults()

    def test_text_has_a_length_limit(self, panel):
        """表单值会进日志，无限长的输入是个隐患。"""
        from gamebot.params import TEXT_MAX_LENGTH

        assert panel._editors["t.name"].maxLength() == TEXT_MAX_LENGTH


class TestPanelWithoutForm:
    def test_empty_form_hides_the_body(self, qt_app):
        widget = ParamsPanel()
        widget.set_form(None)
        try:
            assert not widget._body.isVisible()
            assert widget.values() == {}
        finally:
            widget.deleteLater()

    def test_hint_explains_why_it_is_empty(self, qt_app):
        widget = ParamsPanel()
        widget.set_form(FormSpec())
        try:
            assert "没有可调" in widget._hint.text()
        finally:
            widget.deleteLater()


class TestSwitchingScripts:
    def test_switching_rebuilds_the_fields(self, qt_app):
        """换脚本要**重建**，不能把上一个脚本的字段留在界面上。"""
        other = FormSpec(
            title="另一个",
            fields=(ParamField("o.x", FieldKind.BOOL, True, label="X"),),
        )
        widget = ParamsPanel()
        try:
            widget.set_form(SAMPLE)
            assert set(widget.values()) == set(SAMPLE.defaults())

            widget.set_form(other)
            assert set(widget.values()) == {"o.x"}
            assert widget.title() == "另一个"

            widget.set_form(None)
            assert widget.values() == {}
        finally:
            widget.deleteLater()

    def test_old_editors_do_not_pile_up(self, qt_app):
        widget = ParamsPanel()
        try:
            widget.set_form(SAMPLE)
            widget.set_form(SAMPLE)
            assert widget._fields.rowCount() == len(SAMPLE.fields)
        finally:
            widget.deleteLater()


class TestEndToEnd:
    """表单值真的走到步骤里 —— 这一段是表单存在的全部理由。"""

    def _run_with(self, values):
        """用一份表单值跑一次引擎，返回步骤读到的参数。"""
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

        read: list[object] = []

        def step(ctx):
            read.append(ctx.param("t.count"))
            return ActionResult.success()

        tree = PageTree()
        tree.add(Page("home", queries=(ImageQuery("home.png"),)))
        graph = Graph(initial="home")
        graph.add_node(Node("home", page="home", steps=[FunctionStep(step)]))
        scenario = Scenario(name="form", tree=tree, graph=graph)
        scenario.options.tick_interval = 0.001
        scenario.options.max_ticks = 2
        scenario.validate()

        config = AppConfig.defaults()
        config.screen.backend = BackendKind.FAKE
        config.vision.record = False
        session = BaseSession(
            build_fake_backends(size=(640, 360)),
            matcher=FakeMatcher(matches={"home.png": (Point(1, 1), 0.99)}),
            reader=FakeReader(),
        )
        # 这一步就是界面/命令行做的事：把表单值凑齐成一份完整参数
        params = SAMPLE.fill(values)
        ctx = build_context(config, scenario=scenario, session=session, params=params)
        engine = build_engine(config, ctx, scenario)
        try:
            engine.run()
        finally:
            ctx.close()
        return read

    def _read_once(self, values):
        """跑一次，返回**去重后**步骤读到的值。

        场景给了 ``max_ticks=2``，而 ``home`` 的步骤**每轮都跑**（不是 on_enter），
        所以它会读两次 —— 两次当然读到同一个值。用例关心的是"读到了什么"，
        不是"读了几次"，这里收一下免得每条断言都写成 ``[7, 7]``。
        """
        return sorted(set(self._run_with(values)))

    def test_form_value_reaches_the_step(self):
        assert self._read_once({"t.count": 7}) == [7]

    def test_untouched_fields_still_reach_the_step(self):
        """用户只改了一个字段，其它字段**也有值**（来自声明）。

        这是 ``FORM.fill()`` 存在的理由：如果只传用户改过的，步骤里
        ``ctx.param("t.count")`` 就会缺失，于是每个读参数的地方都得再写一遍
        默认值 —— 而那份默认值和 ``FORM`` 里的声明是两处，迟早不一致。
        """
        assert self._read_once({"t.count": 5}) == [5]
        # 没被改过的字段也在传下去的那份里
        assert SAMPLE.fill({"t.count": 5})["t.ratio"] == 0.5

    def test_defaults_used_when_nothing_given(self):
        assert self._read_once({}) == [3]

    def test_cli_style_string_value_is_converted(self):
        """命令行给的是字符串，走同一个 ``fill()`` 也该变成 int。"""
        assert self._read_once({"t.count": "6"}) == [6]

    def test_out_of_range_is_rejected_before_running(self):
        from gamebot.exceptions import ConfigError

        with pytest.raises(ConfigError, match="不能大于"):
            SAMPLE.fill({"t.count": 99})

    def test_extra_keys_pass_through(self):
        """表单没声明的参数（CLI 的自由）不受表单约束。"""
        params = SAMPLE.fill({"t.count": 1, "anything": {"nested": True}})
        assert params["anything"] == {"nested": True}
