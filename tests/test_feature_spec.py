"""业务层的**声明契约**：一个功能导出**一个** ``SPEC``，里面只有数据。

## 这一组在钉什么

用户的要求是"让编辑器做类型检查，而不是搞个检查按钮"，并且要
"重构彻底一点"：**声明是数据，组装是框架的事**。

所以这里验三层：

1. **声明完备** —— 现有脚本都按约定导出、字段齐、真能组装出来；
2. **声明是 typed 的** —— 漏字段/拼错/类型错在编辑器里就报（运行期也有兜底）；
3. **组装在框架里** —— 业务层不该有"建树/加节点/连边"的代码，
   而组装本身（父先子后、边在节点之后、校验）由 ``materialize`` 做对。
"""

from __future__ import annotations

import pathlib

import pytest

from gamebot.atomic.query import ImageQuery
from gamebot.config.schema import AppConfig
from gamebot.exceptions import ConfigError, FlowError, StateError
from gamebot.feature import FeatureSpec
from gamebot.flow import Node
from gamebot.flow.scenario import EngineOptions
from gamebot.params import FormSpec
from gamebot.scenario_spec import ScenarioSpec
from gamebot.state import Page, PageKind
from gamebot.types import Region
from games._spec import discovery_errors, get_script, list_scripts, read_spec


def _page(pid: str, template: str = "x.png", **kwargs) -> Page:
    return Page(pid, queries=(ImageQuery(template),), **kwargs)


def _spec(**overrides) -> FeatureSpec:
    """一份最小可用的声明，用来只测被 override 的那一项。"""
    kwargs = dict(
        name="game/feature",
        title="标题",
        slug="feature",
        templates_dir="games/game/feature/templates",
        scenario=ScenarioSpec(
            initial="home",
            pages=((_page("home"), None),),
            nodes=(Node("home", page="home"),),
        ),
        base_config=AppConfig.defaults,
    )
    kwargs.update(overrides)
    return FeatureSpec(**kwargs)


class TestShippedScriptsDeclareSpec:
    """现有脚本必须都按新约定声明，而且**真能组装出来**。"""

    def test_every_script_is_discovered(self):
        assert list_scripts(), "一个脚本都没发现"
        assert discovery_errors() == [], f"发现过程有错: {discovery_errors()}"

    def test_every_script_has_the_required_fields(self):
        for spec in list_scripts():
            assert spec.key and "/" in spec.key
            assert spec.title.strip()
            assert spec.slug.strip()
            assert isinstance(spec.form, FormSpec)
            assert isinstance(spec.feature, FeatureSpec)

    def test_every_script_materializes(self):
        """声明得对还不够 —— 真能组装出配置和流程才算。"""
        for spec in list_scripts():
            config = spec.build_config()
            scenario = spec.build_scenario()
            scenario.validate()
            assert config.template_roots(), f"{spec.key} 没有模板根"
            assert config.name == spec.key, "配置名该等于脚本 key"
            assert config.vision.extra_template_dirs, "功能级模板根该被填上"
            assert len(scenario.graph.nodes) >= 1
            assert scenario.graph.initial

    def test_building_twice_gives_independent_objects(self):
        """**每次一份新的** —— 共享一个配置对象会让一次运行改到的东西泄漏到下一次。"""
        spec = get_script("mingjiangsha/jingji")
        assert spec.build_config() is not spec.build_config()
        first_scenario, second_scenario = spec.build_scenario(), spec.build_scenario()
        assert first_scenario is not second_scenario
        assert first_scenario.tree is not second_scenario.tree
        assert first_scenario.graph is not second_scenario.graph

    def test_tick_interval_has_one_source(self):
        """引擎节奏只声明一次：``options``。配置里的 tick 是**跟着它填的**。

        两处各写一个值的话（声明 2.0 而配置里 0.4），帧 TTL 会按 0.4 算 ——
        表现是"帧早就过期了"这种怪事。
        """
        spec = get_script("mingjiangsha/jingji")
        config = spec.build_config()
        scenario = spec.build_scenario()
        assert config.timing.tick_interval == scenario.options.tick_interval

    def test_get_script_by_key_and_by_slug(self):
        spec = get_script("mingjiangsha/jingji")
        assert get_script("jingji") is spec, "只给功能名（唯一时）也该认"


class TestDeclarationsAreData:
    """**业务层不该有组装代码。** 这条是这轮重构的核心。"""

    def test_feature_init_has_no_assembly_code(self):
        """``__init__.py`` 里不该再出现建树/连边这类调用。

        不是为了教条 —— 那些代码对每个脚本都长一个样，留着就等于把
        "会不会写错"复制到每个脚本里（忘了 ``add_node`` 就连边是运行期事故）。

        **用 AST 而不是字符串搜索**：注释和 docstring 里会**提到**这些名字
        （比如说明"以前这里有 graph.add_node(...)"），字符串搜索会把它误判成代码。
        只看真实的 ``Call`` 节点才准 —— 这个坑我第一次就踩了。
        """
        import ast

        tree = ast.parse(
            pathlib.Path("games/mingjiangsha/jingji/__init__.py").read_text(encoding="utf-8")
        )
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        forbidden = called & {"add_node", "add_edge", "connect", "add", "add_many"}
        assert not forbidden, f"__init__.py 里还有组装调用 {sorted(forbidden)} —— 组装该在框架里"

    def test_scenario_spec_is_only_data(self):
        """``SCENARIO`` 的字段全是数据/对象，没有"怎么组装"的回调。"""
        from games.mingjiangsha.jingji.graph import SCENARIO

        assert isinstance(SCENARIO, ScenarioSpec)
        assert isinstance(SCENARIO.pages, tuple)
        assert all(isinstance(node, Node) for node in SCENARIO.nodes)
        assert all(len(entry) == 3 for entry in SCENARIO.edges)


class TestFeatureSpecIsTyped:
    """``FeatureSpec`` 本身：必选字段、类型、以及构造期就报的那几条。"""

    def test_good_spec_constructs(self):
        assert _spec().name == "game/feature"

    def test_form_defaults_to_none(self):
        """表单可选：没有表单的脚本不该被迫写一个空 FormSpec。"""
        assert _spec().form is None

    def test_name_must_be_game_slash_feature(self):
        with pytest.raises(ConfigError, match="<游戏>/<功能>"):
            _spec(name="mingjiangsha")

    @pytest.mark.parametrize("field", ["title", "slug", "templates_dir"])
    def test_blank_text_fields_are_rejected(self, field):
        with pytest.raises(ConfigError, match=field):
            _spec(**{field: "   "})

    def test_scenario_must_be_a_scenario_spec(self):
        with pytest.raises(ConfigError, match="ScenarioSpec"):
            _spec(scenario={"initial": "home"})  # type: ignore[arg-type]

    def test_base_config_must_be_callable_not_a_value(self):
        """**关键**：传配置对象本身要报。

        每次运行都要一份新的 —— 共享一个 ``AppConfig`` 会让一次运行改到的东西
        泄漏到下一次。这个错很容易犯（``base_config=some_config`` 看着挺自然）。
        """
        with pytest.raises(ConfigError, match="可调用对象"):
            _spec(base_config=AppConfig.defaults())  # type: ignore[arg-type]

    def test_build_config_must_be_callable_or_none(self):
        with pytest.raises(ConfigError, match="可调用对象"):
            _spec(build_config=AppConfig.defaults())  # type: ignore[arg-type]

    def test_form_must_be_a_form_spec(self):
        with pytest.raises(ConfigError, match="FormSpec"):
            _spec(form={"a": 1})  # type: ignore[arg-type]

    def test_missing_required_field_is_a_type_error(self):
        """漏字段在**运行期**也拦得住（dataclass 必选参数），不只是 mypy。"""
        kwargs = dict(
            name="game/feature",
            title="t",
            slug="s",
            scenario=_spec().scenario,
            base_config=AppConfig.defaults,
        )
        with pytest.raises(TypeError, match="templates_dir"):
            FeatureSpec(**kwargs)  # type: ignore[arg-type]

    def test_misspelled_field_is_a_type_error(self):
        kwargs = dict(
            name="game/feature",
            title="t",
            slug="s",
            templates_dir="x",
            scenario=_spec().scenario,
            base_config=AppConfig.defaults,
        )
        with pytest.raises(TypeError, match="formm"):
            FeatureSpec(**kwargs, **{"formm": FormSpec()})  # type: ignore[arg-type]


class TestScenarioSpecAssembles:
    """组装在框架里做 —— 所以可以直接测"组装得对不对"。"""

    def _spec(self, **overrides) -> ScenarioSpec:
        kwargs = dict(
            initial="home",
            pages=((_page("home"), None),),
            nodes=(Node("home", page="home"),),
        )
        kwargs.update(overrides)
        return ScenarioSpec(**kwargs)

    def test_pages_are_added_parent_first(self):
        """页面按声明顺序加，框架从 ``(页面, 父)`` 算出路径 id 与 ROI 继承。

        （节点要认领**每一个**记录信息的状态，所以这里两个页面都得有节点 ——
        那正是 ``validate_binding`` 在管的规矩，声明里漏了它会在组装时报。）
        """
        spec = self._spec(
            initial="root",
            pages=(
                (_page("root", "r.png", roi=Region(0, 0, 200, 200)), None),
                (_page("root/kid", "k.png"), "root"),
            ),
            nodes=(Node("root", page="root"), Node("kid", page="root/kid")),
            # kid 得从 initial 走得到，否则它就是死代码（校验会报）
            edges=(("root", "kid", {}),),
        )
        scenario = spec.materialize(name="x")
        assert scenario.tree.get("root/kid") is not None
        # 子页面没写 roi，于是原样继承父页面的
        assert scenario.tree.effective_roi("root/kid") == Region(0, 0, 200, 200)

    def test_child_roi_is_relative_to_the_parent(self):
        """子页面的 roi 是**相对父页面原点**的 —— 框架叠出绝对值。"""
        spec = self._spec(
            initial="root",
            pages=(
                (_page("root", "r.png", roi=Region(100, 50, 200, 200)), None),
                (_page("root/kid", "k.png", roi=Region(10, 20, 30, 40)), "root"),
            ),
            nodes=(Node("root", page="root"), Node("kid", page="root/kid")),
            edges=(("root", "kid", {}),),
        )
        scenario = spec.materialize(name="x")
        assert scenario.tree.effective_roi("root/kid") == Region(110, 70, 30, 40)

    def test_edges_are_connected_after_all_nodes(self):
        """**边在全部节点加完之后才连** —— 反过来"边指向还没加的节点"会是假错误。"""
        spec = self._spec(
            nodes=(Node("home", page="home"), Node("next", page="home")),
            edges=(("home", "next", {}),),
        )
        scenario = spec.materialize(name="x")
        assert scenario.graph.edges

    def test_dangling_edge_reference_is_caught(self):
        """边指向不存在的节点 —— 组装时报（不是跑到那条边才发现）。"""
        spec = self._spec(edges=(("home", "ghost", {}),))
        with pytest.raises(FlowError, match="ghost"):
            spec.materialize(name="x")

    def test_unreachable_node_is_caught(self):
        """从 initial 走不到的节点（死代码）在组装时报。"""
        spec = self._spec(nodes=(Node("home", page="home"), Node("lonely", page="home")))
        with pytest.raises(FlowError, match="走不到"):
            spec.materialize(name="x")

    def test_duplicate_node_id_is_caught_at_construction(self):
        with pytest.raises(ConfigError, match="重复"):
            self._spec(nodes=(Node("home"), Node("home")))

    def test_initial_must_be_a_declared_node(self):
        with pytest.raises(ConfigError, match="initial"):
            self._spec(initial="nope")

    def test_empty_initial_is_rejected(self):
        with pytest.raises(ConfigError, match="initial"):
            self._spec(initial="  ")

    def test_group_page_with_queries_is_rejected(self):
        group = Page("g", queries=(ImageQuery("g.png"),), kind=PageKind.GROUP)
        with pytest.raises(ConfigError, match="group"):
            self._spec(pages=((group, None),), nodes=(Node("home", page="g"),))

    def test_parent_must_come_before_child(self):
        """声明顺序错了（子在前）要有一句人话，而不是莫名其妙的错。"""
        spec = self._spec(
            pages=((_page("root/kid"), "root"), (_page("root"), None)),
        )
        with pytest.raises(StateError, match="父页面不存在"):
            spec.materialize(name="x")

    def test_options_go_into_the_scenario(self):
        spec = self._spec(options=EngineOptions(max_ticks=7))
        assert spec.materialize(name="x").options.max_ticks == 7

    def test_name_falls_back_to_the_given_one(self):
        assert self._spec().materialize(name="given").name == "given"

    def test_declared_name_wins(self):
        """``ScenarioSpec.name`` 写了就用它 —— 但框架总是传 SPEC 的 name，
        所以正常路径下两者一致（这里验机制本身）。"""
        spec = self._spec(name="declared")
        assert spec.materialize(name="given").name == "declared"


class TestRegistryRejectsScriptsWithoutSpec:
    """没有 ``SPEC`` 的功能目录要被**明确指出**，而不是静默消失。

    "脚本没出现在列表里"是最难查的一类问题 —— 所以发现过程必须出声，
    而且要说清**缺的是什么、约定在哪**。

    这里直接测 ``read_spec``（它就是为了能被直接测才抽出来的）：造一个假模块，
    比骗 importlib 去加载临时目录干净得多。
    """

    def test_module_without_spec_is_rejected_with_the_convention(self):
        from types import SimpleNamespace

        module = SimpleNamespace(TITLE="标题", build_config=lambda: None)
        with pytest.raises(ConfigError) as excinfo:
            read_spec(module, "game/feature")

        message = str(excinfo.value)
        assert "SPEC" in message, "要说清缺的是 SPEC"
        assert "FeatureSpec" in message, "要给出准确的类型名，方便去查"
        assert "games/README.md" in message, "要指向约定文档"
        assert "game/feature" in message, "要说清是哪个脚本"

    def test_spec_of_the_wrong_type_says_what_it_actually_is(self):
        from types import SimpleNamespace

        module = SimpleNamespace(SPEC={"name": "game/feature"})
        with pytest.raises(ConfigError, match="dict"):
            read_spec(module, "game/feature")

    def test_a_real_spec_is_returned_as_is(self):
        from types import SimpleNamespace

        spec = _spec()
        assert read_spec(SimpleNamespace(SPEC=spec), "game/feature") is spec
