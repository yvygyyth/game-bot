"""业务层的**声明契约**：一个功能导出**一个** ``SPEC``。

## 这一组在钉什么

用户的要求是"让编辑器做类型检查，而不是搞个检查按钮"。这条能不能成立，
取决于声明是不是**一个 typed 对象**：

* 散装 ``getattr(module, "TITLE", slug)`` 那种写法，编辑器看不见任何契约 ——
  结果只能靠运行期捞、或靠一个「检查」按钮；
* 一个 ``FeatureSpec`` 则**字段全必选、类型明确**，漏了/拼错/传错类型，
  mypy 在写的时候就报。

所以这里既要验行为（注册表确实按 SPEC 发现脚本），也要验**声明本身是完备的**。
"""

from __future__ import annotations

import pytest

from gamebot.feature import FeatureSpec
from gamebot.params import FormSpec
from games._spec import discovery_errors, get_script, list_scripts, read_spec


class TestShippedScriptsDeclareSpec:
    """现有的脚本必须都按新约定声明。"""

    def test_every_script_is_discovered(self):
        scripts = list_scripts()
        assert scripts, "一个脚本都没发现"
        assert discovery_errors() == [], f"发现过程有错: {discovery_errors()}"

    def test_every_script_has_the_required_fields(self):
        for spec in list_scripts():
            assert spec.key and "/" in spec.key
            assert spec.title.strip(), f"{spec.key} 没有 title"
            assert spec.slug.strip(), f"{spec.key} 没有 slug"
            assert callable(spec.build_config)
            assert callable(spec.build_scenario)
            assert isinstance(spec.form, FormSpec)

    def test_every_script_can_build_its_pieces(self):
        """声明得对还不够 —— 真能造出配置和流程才算。"""
        for spec in list_scripts():
            config = spec.build_config()
            scenario = spec.build_scenario()
            scenario.validate()
            assert config.template_roots(), f"{spec.key} 没有模板根"

    def test_get_script_by_key_and_by_slug(self):
        spec = get_script("mingjiangsha/jingji")
        assert get_script("jingji") is spec, "只给功能名（唯一时）也该认"


class TestFeatureSpecIsTyped:
    """``FeatureSpec`` 本身：必选字段、类型、以及**构造期就报**的那几条。"""

    def _good(self, **overrides):
        from gamebot.config.schema import AppConfig
        from gamebot.flow.scenario import Scenario

        kwargs = dict(
            name="game/feature",
            title="标题",
            slug="feature",
            templates_dir="games/game/feature/templates",
            build_config=AppConfig.defaults,
            build_scenario=Scenario,
        )
        kwargs.update(overrides)
        return kwargs

    def test_good_spec_constructs(self):
        assert FeatureSpec(**self._good()).name == "game/feature"

    def test_form_defaults_to_none(self):
        """表单可选：没有表单的脚本不该被迫写一个空 FormSpec。"""
        assert FeatureSpec(**self._good()).form is None

    def test_name_must_be_game_slash_feature(self):
        from gamebot.exceptions import ConfigError

        with pytest.raises(ConfigError, match="<游戏>/<功能>"):
            FeatureSpec(**self._good(name="mingjiangsha"))

    @pytest.mark.parametrize("field", ["title", "slug", "templates_dir"])
    def test_blank_text_fields_are_rejected(self, field):
        from gamebot.exceptions import ConfigError

        with pytest.raises(ConfigError, match=field):
            FeatureSpec(**self._good(**{field: "   "}))

    def test_builders_must_be_callables_not_values(self):
        """**关键**：传配置对象本身（而不是"造配置的函数"）要报。

        每次运行都要一份新的 —— 共享一个 ``AppConfig`` 会让一次运行改到的东西
        泄漏到下一次。这个错很容易犯（``build_config=some_config`` 看起来挺自然）。
        """
        from gamebot.config.schema import AppConfig
        from gamebot.exceptions import ConfigError

        with pytest.raises(ConfigError, match="可调用对象"):
            FeatureSpec(**self._good(build_config=AppConfig.defaults()))

    def test_form_must_be_a_form_spec(self):
        from gamebot.exceptions import ConfigError

        with pytest.raises(ConfigError, match="FormSpec"):
            FeatureSpec(**self._good(form={"a": 1}))

    def test_missing_required_field_is_a_type_error(self):
        """漏字段在**运行期**也拦得住（dataclass 的必选参数），不只是 mypy。"""
        kwargs = self._good()
        del kwargs["templates_dir"]
        with pytest.raises(TypeError, match="templates_dir"):
            FeatureSpec(**kwargs)

    def test_misspelled_field_is_a_type_error(self):
        with pytest.raises(TypeError, match="from_"):
            FeatureSpec(**self._good(), **{"from_": FormSpec()})


class TestRegistryRejectsScriptsWithoutSpec:
    """没有 ``SPEC`` 的功能目录要被**明确指出**，而不是静默消失。

    "脚本没出现在列表里"是最难查的一类问题 —— 所以发现过程必须出声，
    而且要说清**缺的是什么、约定在哪**。

    这里直接测 ``read_spec``（它就是为了能被直接测才抽出来的）：造一个假模块，
    比骗 importlib 去加载临时目录干净得多（那样测的是 import 机制，
    不是"提示够不够清楚"这件事本身）。
    """

    def test_module_without_spec_is_rejected_with_the_convention(self):
        from types import SimpleNamespace

        from gamebot.exceptions import ConfigError

        module = SimpleNamespace(TITLE="标题", build_config=lambda: None)
        with pytest.raises(ConfigError) as excinfo:
            read_spec(module, "game/feature")

        message = str(excinfo.value)
        assert "SPEC" in message, "要说清缺的是 SPEC"
        assert "FeatureSpec" in message, "要给出准确的类型名，方便去查"
        assert "games/README.md" in message, "要指向约定文档"
        assert "game/feature" in message, "要说清是哪个脚本"

    def test_spec_of_the_wrong_type_says_what_it_actually_is(self):
        """导出错了类型时，提示要带上**现状**，不只是"要有 SPEC"。"""
        from types import SimpleNamespace

        from gamebot.exceptions import ConfigError

        module = SimpleNamespace(SPEC={"name": "game/feature"})
        with pytest.raises(ConfigError, match="dict"):
            read_spec(module, "game/feature")

    def test_a_real_spec_is_returned_as_is(self):
        from types import SimpleNamespace

        from gamebot.config.schema import AppConfig
        from gamebot.flow.scenario import Scenario

        spec = FeatureSpec(
            name="game/feature",
            title="标题",
            slug="feature",
            templates_dir="games/game/feature/templates",
            build_config=AppConfig.defaults,
            build_scenario=Scenario,
        )
        assert read_spec(SimpleNamespace(SPEC=spec), "game/feature") is spec
