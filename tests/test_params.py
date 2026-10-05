"""动态表单的声明层（`gamebot.params`）。

这是**唯一的校验配置**：控件层的 range 由它生成，提交时的越界判定走它的
``coerce``，命令行 ``--param`` 也走同一个。所以这里的用例要钉死两件事：

1. **声明写错要在装配期就报**（不是等用户点了开始）；
2. **越界/类型错一律拒绝**，而且界面和命令行看到的是同一套判定。
"""

from __future__ import annotations

import pytest

from gamebot.exceptions import ConfigError
from gamebot.params import TEXT_MAX_LENGTH, FieldKind, FormSpec, ParamField


def _text(name="note", default="", **kwargs):
    return ParamField(name, FieldKind.TEXT, default, **kwargs)


def _int(name="rounds", default=3, **kwargs):
    return ParamField(name, FieldKind.INT, default, **kwargs)


def _float(name="ratio", default=0.5, **kwargs):
    return ParamField(name, FieldKind.FLOAT, default, **kwargs)


def _bool(name="strict", default=False, **kwargs):
    return ParamField(name, FieldKind.BOOL, default, **kwargs)


def _choice(name="team", default="auto", **kwargs):
    kwargs.setdefault("choices", (("auto", "自动"), ("main", "主力队")))
    return ParamField(name, FieldKind.CHOICE, default, **kwargs)


class TestFieldDefaults:
    def test_label_falls_back_to_name(self):
        assert _text("farm.note").display == "farm.note"

    def test_explicit_label_wins(self):
        assert _text("farm.note", label="备注").display == "备注"

    def test_all_kinds_validate_clean(self):
        for item in (_text(), _int(), _float(), _bool(), _choice()):
            item.validate()


class TestDeclarationErrors:
    """声明错误 —— 每一条都必须在**装配期**报，不能拖到运行时。"""

    def test_empty_name(self):
        with pytest.raises(ConfigError, match="name 不能为空"):
            ParamField("", FieldKind.TEXT, "").validate()

    def test_whitespace_name(self):
        with pytest.raises(ConfigError, match="name 不能为空"):
            ParamField("   ", FieldKind.TEXT, "").validate()

    def test_choice_without_choices(self):
        with pytest.raises(ConfigError, match="没给 choices"):
            ParamField("team", FieldKind.CHOICE, "a").validate()

    def test_choice_default_not_in_choices(self):
        with pytest.raises(ConfigError, match="不在 choices 里"):
            _choice(default="nope")

    def test_choice_with_duplicate_values(self):
        with pytest.raises(ConfigError, match="重复的值"):
            ParamField(
                "team", FieldKind.CHOICE, "a", choices=(("a", "甲"), ("a", "乙"))
            ).validate()

    def test_choice_with_empty_display_name(self):
        with pytest.raises(ConfigError, match="空显示名"):
            ParamField("team", FieldKind.CHOICE, "a", choices=(("a", ""),)).validate()

    def test_non_choice_must_not_have_choices(self):
        with pytest.raises(ConfigError, match="不是选择器"):
            ParamField("x", FieldKind.TEXT, "", choices=(("a", "甲"),)).validate()

    def test_non_number_must_not_have_bounds(self):
        with pytest.raises(ConfigError, match="不是数字"):
            ParamField("x", FieldKind.TEXT, "", min=0).validate()

    def test_number_needs_a_default(self):
        with pytest.raises(ConfigError, match="必须有默认值"):
            ParamField("rounds", FieldKind.INT).validate()

    def test_int_default_must_be_int_not_float(self):
        with pytest.raises(ConfigError, match="要小数请用"):
            ParamField("rounds", FieldKind.INT, 1.5).validate()

    def test_bool_default_for_number_is_a_mistake(self):
        with pytest.raises(ConfigError, match="那是复选框"):
            ParamField("rounds", FieldKind.INT, True).validate()

    def test_text_default_must_be_str(self):
        with pytest.raises(ConfigError, match="必须是字符串"):
            ParamField("note", FieldKind.TEXT, 5).validate()

    def test_bool_default_must_be_bool(self):
        with pytest.raises(ConfigError, match="必须是 True/False"):
            ParamField("strict", FieldKind.BOOL, "yes").validate()

    def test_min_greater_than_max(self):
        with pytest.raises(ConfigError, match="比 max"):
            _int(min=10, max=1)

    def test_default_below_min(self):
        with pytest.raises(ConfigError, match="小于 min"):
            _int(default=0, min=1)

    def test_default_above_max(self):
        with pytest.raises(ConfigError, match="大于 max"):
            _int(default=99, max=10)

    def test_negative_step(self):
        with pytest.raises(ConfigError, match="step 必须为正数"):
            _int(step=0)


class TestFormSpec:
    def test_duplicate_names_rejected_at_construction(self):
        with pytest.raises(ConfigError, match="重名字段"):
            FormSpec(fields=(_int("a"), _text("a")))

    def test_empty_form_is_falsy(self):
        assert not FormSpec()
        assert len(FormSpec()) == 0

    def test_non_empty_form_is_truthy(self):
        assert FormSpec(fields=(_int(),))

    def test_defaults_are_the_declared_ones(self):
        spec = FormSpec(fields=(_int(default=5), _bool(default=True), _choice()))
        assert spec.defaults() == {"rounds": 5, "strict": True, "team": "auto"}

    def test_a_bad_field_cannot_even_be_constructed(self):
        """坏字段在 `ParamField(...)` 那一行就炸，进不了 FormSpec。

        （早先版本要显式调 `FormSpec.validate()` 才报，那样"声明写错"会被拖到
        装配期之后 —— 这条用例就是被那次改动逼出来的。）
        """
        with pytest.raises(ConfigError, match="没给 choices"):
            ParamField("bad", FieldKind.CHOICE, "x")

    def test_validate_is_idempotent_on_a_good_form(self):
        """`validate()` 保留成公开方法（可以重复调），但正常情况下没人需要调。"""
        spec = FormSpec(fields=(_int("good"), _choice()))
        spec.validate()
        spec.validate()

    def test_get_by_name(self):
        spec = FormSpec(fields=(_int("rounds", min=1, max=9),))
        assert spec.get("rounds").max == 9
        assert spec.get("nope") is None


class TestCoerceNumbers:
    def test_int_from_int(self):
        assert _int(min=0, max=10).coerce(7) == 7

    def test_int_from_string(self):
        """命令行给的一定是字符串。"""
        assert _int(min=0, max=10).coerce("7") == 7

    def test_int_rejects_float_value(self):
        with pytest.raises(ConfigError, match="要整数"):
            _int().coerce(1.5)

    def test_int_accepts_whole_float(self):
        assert _int().coerce(2.0) == 2

    def test_float_from_string(self):
        assert _float(min=0.0, max=1.0).coerce("0.25") == 0.25

    def test_below_min_rejected(self):
        with pytest.raises(ConfigError, match="不能小于"):
            _int(min=1, max=9).coerce(0)

    def test_above_max_rejected(self):
        with pytest.raises(ConfigError, match="不能大于"):
            _int(min=1, max=9).coerce(10)

    def test_boundary_values_accepted(self):
        spec = _int(min=1, max=9)
        assert spec.coerce(1) == 1
        assert spec.coerce(9) == 9

    def test_junk_string_rejected(self):
        with pytest.raises(ConfigError, match="要数字"):
            _int().coerce("abc")

    def test_bool_is_not_a_number(self):
        with pytest.raises(ConfigError, match="要数字"):
            _int().coerce(True)

    def test_none_rejected(self):
        with pytest.raises(ConfigError, match="要数字"):
            _int().coerce(None)


class TestCoerceBool:
    @pytest.mark.parametrize("raw", [True, "true", "True", "1", "yes", "on"])
    def test_truthy_spellings(self, raw):
        assert _bool().coerce(raw) is True

    @pytest.mark.parametrize("raw", [False, "false", "0", "no", "off", ""])
    def test_falsy_spellings(self, raw):
        assert _bool().coerce(raw) is False

    def test_junk_rejected(self):
        with pytest.raises(ConfigError, match="要 True/False"):
            _bool().coerce("maybe")


class TestCoerceText:
    def test_plain(self):
        assert _text().coerce("hello") == "hello"

    def test_empty_allowed(self):
        assert _text().coerce("") == ""

    def test_non_string_rejected(self):
        with pytest.raises(ConfigError, match="要字符串"):
            _text().coerce(5)

    def test_too_long_rejected(self):
        with pytest.raises(ConfigError, match="太长"):
            _text().coerce("x" * (TEXT_MAX_LENGTH + 1))

    def test_exactly_at_limit_allowed(self):
        assert len(_text().coerce("x" * TEXT_MAX_LENGTH)) == TEXT_MAX_LENGTH


class TestCoerceChoice:
    def test_value_from_form(self):
        assert _choice().coerce("main") == "main"

    def test_value_from_cli_is_string(self):
        """命令行给的是字符串，选项值可能是数字 —— 两种都要认。"""
        spec = ParamField(
            "mode", FieldKind.CHOICE, 1, choices=((1, "一"), (2, "二"))
        )
        assert spec.coerce("2") == 2
        assert spec.coerce(2) == 2

    def test_unknown_option_rejected(self):
        with pytest.raises(ConfigError, match="不在选项里"):
            _choice().coerce("nope")

    def test_message_lists_the_options(self):
        """报错要说清可选什么，否则用户得回去翻代码。"""
        with pytest.raises(ConfigError, match="auto"):
            _choice().coerce("nope")


class TestFormCoerce:
    def test_only_declared_fields_are_constrained(self):
        """表单没声明的 key **原样留下** —— 那是代码/CLI 的自由。"""
        spec = FormSpec(fields=(_int("rounds", default=3, min=0, max=9),))
        result = spec.coerce({"rounds": "5", "extra": {"any": "object"}})
        assert result == {"rounds": 5, "extra": {"any": "object"}}

    def test_declared_field_is_checked(self):
        spec = FormSpec(fields=(_int("rounds", default=3, min=0, max=9),))
        with pytest.raises(ConfigError, match="不能大于"):
            spec.coerce({"rounds": "99"})

    def test_values_of_every_kind_round_trip(self):
        spec = FormSpec(
            fields=(
                _bool("a", default=False),
                _int("b", default=1, min=0, max=9),
                _float("c", default=0.5, min=0.0, max=1.0),
                _text("d", default=""),
                _choice("e", default="auto"),
            )
        )
        assert spec.coerce(spec.defaults()) == spec.defaults()
