"""配置层测试 —— 重点是 ``merge_dataclass`` 与两个随项目发布的 YAML 样例。

为什么连样例 YAML 也测：配置文件里的错字只会在真正跑脚本时才暴露，
而那时候人已经在游戏前面了。让 CI 把这类错误拦下来。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gamebot.config.loader import (
    config_to_dict,
    load_config,
    load_regions,
    merge_dataclass,
)
from gamebot.config.schema import AppConfig, BackendKind
from gamebot.exceptions import ConfigError
from gamebot.types import Region

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestMergeDataclass:
    def test_simple_field(self) -> None:
        config = merge_dataclass(AppConfig.defaults(), {"name": "my-bot"})
        assert config.name == "my-bot"

    def test_nested_dataclass(self) -> None:
        config = merge_dataclass(AppConfig.defaults(), {"screen": {"window_title": "原神"}})
        assert config.screen.window_title == "原神"
        # 未提到的字段保持默认
        assert config.screen.monitor_index == 1

    def test_dotted_key(self) -> None:
        config = merge_dataclass(AppConfig.defaults(), {"screen.window_title": "崩铁"})
        assert config.screen.window_title == "崩铁"

    def test_dotted_key_deep(self) -> None:
        config = merge_dataclass(AppConfig.defaults(), {"timing.tick_interval": 0.5})
        assert config.timing.tick_interval == 0.5

    def test_unknown_field_raises(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            merge_dataclass(AppConfig.defaults(), {"screeen": {}})
        assert "未知配置字段" in str(excinfo.value)

    def test_unknown_nested_field_raises(self) -> None:
        with pytest.raises(ConfigError):
            merge_dataclass(AppConfig.defaults(), {"screen": {"window_titel": "x"}})

    def test_none_keeps_default(self) -> None:
        config = merge_dataclass(AppConfig.defaults(), {"name": None})
        assert config.name == "game-bot"

    def test_enum_coercion(self) -> None:
        config = merge_dataclass(AppConfig.defaults(), {"screen": {"backend": "android"}})
        assert config.screen.backend is BackendKind.ANDROID

    def test_enum_invalid_raises(self) -> None:
        with pytest.raises(ConfigError) as excinfo:
            merge_dataclass(AppConfig.defaults(), {"screen": {"backend": "linux"}})
        assert "取值非法" in str(excinfo.value)

    def test_list_to_tuple(self) -> None:
        config = merge_dataclass(AppConfig.defaults(), {"screen": {"logic_size": [1920, 1080]}})
        assert config.screen.logic_size == (1920, 1080)

    def test_bool_from_string(self) -> None:
        config = merge_dataclass(AppConfig.defaults(), {"dry_run": "true"})
        assert config.dry_run is True

    def test_top_level_dry_run(self) -> None:
        assert merge_dataclass(AppConfig.defaults(), {"dry_run": True}).dry_run is True

    def test_non_dataclass_raises(self) -> None:
        with pytest.raises(ConfigError):
            merge_dataclass({}, {"a": 1})  # type: ignore[arg-type]


class TestAppConfig:
    def test_defaults_validate(self) -> None:
        assert AppConfig.defaults().validate() == []

    def test_template_path_relative(self) -> None:
        config = AppConfig.defaults()
        config.paths.root = Path("D:/proj")
        path = config.template_path("main/start.png")
        assert path == Path("D:/proj/assets/templates/main/start.png")

    def test_template_path_absolute_passthrough(self) -> None:
        config = AppConfig.defaults()
        assert config.template_path("C:/tpl/a.png") == Path("C:/tpl/a.png")

    def test_region_lookup(self) -> None:
        config = AppConfig.defaults()
        config.vision.roi["hp"] = Region(0, 0, 10, 10)
        assert config.region("hp") == Region(0, 0, 10, 10)
        assert config.region("nope") is None

    def test_validate_catches_bad_confidence(self) -> None:
        config = AppConfig.defaults()
        config.screen.default_confidence = 1.5
        assert any("default_confidence" in p for p in config.validate())

    def test_validate_catches_bad_tick_interval(self) -> None:
        config = AppConfig.defaults()
        config.timing.tick_interval = 0
        assert any("tick_interval" in p for p in config.validate())

    def test_validate_catches_bad_engine(self) -> None:
        config = AppConfig.defaults()
        config.screen.input_engine = "magic"
        assert any("输入引擎" in p for p in config.validate())

    def test_validate_catches_empty_flow_file(self) -> None:
        config = AppConfig.defaults()
        config.flow_file = ""
        assert any("flow_file" in p for p in config.validate())

    def test_paths_ensure_creates_dirs(self, tmp_path) -> None:
        config = AppConfig.defaults()
        config.paths.root = tmp_path
        config.paths.logs = Path("logs")
        config.paths.screenshots = Path("logs/screenshots")
        config.paths.journals = Path("logs/journals")
        config.paths.templates = Path("assets/templates")
        config.paths.ensure()
        assert (tmp_path / "logs" / "screenshots").is_dir()
        assert (tmp_path / "assets" / "templates").is_dir()

    def test_config_to_dict_is_jsonable(self) -> None:
        import json

        payload = config_to_dict(AppConfig.defaults())
        assert payload["screen"]["backend"] == "windows"
        assert isinstance(payload["paths"]["logs"], str)
        json.dumps(payload)


class TestLoaders:
    def test_load_config_from_yaml(self, tmp_path) -> None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "app.yaml").write_text(
            "name: from-yaml\n"
            "dry_run: true\n"
            "screen:\n"
            "  backend: fake\n"
            "  window_title: 测试窗口\n"
            "timing:\n"
            "  tick_interval: 0.4\n",
            encoding="utf-8",
        )
        config = load_config(tmp_path / "config" / "app.yaml")
        assert config.name == "from-yaml"
        assert config.dry_run is True
        assert config.screen.backend is BackendKind.FAKE
        assert config.screen.window_title == "测试窗口"
        assert config.timing.tick_interval == 0.4
        # root 应该被推导成项目根（config/ 的上一级）
        assert config.paths.root == tmp_path

    def test_load_config_overrides(self, tmp_path) -> None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "app.yaml").write_text("name: base\n", encoding="utf-8")
        config = load_config(tmp_path / "config" / "app.yaml", overrides={"name": "override"})
        assert config.name == "override"

    def test_load_config_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(ConfigError):
            load_config(tmp_path / "nope.yaml")

    def test_load_config_missing_file_with_overrides_uses_defaults(self, tmp_path) -> None:
        config = load_config(tmp_path / "nope.yaml", overrides={"name": "zero-config"})
        assert config.name == "zero-config"

    def test_load_config_rejects_bad_yaml(self, tmp_path) -> None:
        path = tmp_path / "app.yaml"
        path.write_text("name: [unclosed\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_load_config_rejects_non_mapping(self, tmp_path) -> None:
        path = tmp_path / "app.yaml"
        path.write_text("- 1\n- 2\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_load_config_empty_file(self, tmp_path) -> None:
        path = tmp_path / "app.yaml"
        path.write_text("", encoding="utf-8")
        assert load_config(path).name == "game-bot"

    def test_load_regions_list_form(self, tmp_path) -> None:
        path = tmp_path / "regions.yaml"
        path.write_text("regions:\n  hp: [1, 2, 3, 4]\n", encoding="utf-8")
        assert load_regions(path) == {"hp": Region(1, 2, 3, 4)}

    def test_load_regions_dict_form(self, tmp_path) -> None:
        path = tmp_path / "regions.yaml"
        path.write_text(
            "regions:\n  hp:\n    x: 1\n    y: 2\n    w: 3\n    h: 4\n", encoding="utf-8"
        )
        assert load_regions(path) == {"hp": Region(1, 2, 3, 4)}

    def test_load_regions_missing_file_is_empty(self, tmp_path) -> None:
        assert load_regions(tmp_path / "nope.yaml") == {}

    def test_load_regions_bad_format(self, tmp_path) -> None:
        path = tmp_path / "regions.yaml"
        path.write_text("regions:\n  hp: [1, 2]\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_regions(path)


class TestShippedSamples:
    """随项目发布的样例配置必须能被解析 —— 它们就是文档。"""

    def test_app_yaml_loads(self) -> None:
        config = load_config(PROJECT_ROOT / "config" / "app.yaml")
        assert config.name == "game-bot"
        assert config.screen.backend is BackendKind.WINDOWS
        assert config.validate() == []

    def test_regions_yaml_loads(self) -> None:
        regions = load_regions(PROJECT_ROOT / "config" / "regions.yaml")
        assert "full" in regions
        assert regions["full"] == Region(0, 0, 1920, 1080)
        assert all(isinstance(r, Region) for r in regions.values())

    def test_example_script_yaml_is_wellformed(self) -> None:
        """示例脚本定义（页面树 + 流程图）必须是自洽的。

        没法用 ``load_scenario`` 检查 —— 它还依赖 ``query_from_dict`` /
        ``step_from_dict`` 两个还没实现的函数。所以这里直接按 schema 逐条校验，
        至少保证"页面 id / 节点 id 对得上"这类问题不会漏到运行期。
        """
        yaml = pytest.importorskip("yaml")

        path = PROJECT_ROOT / "config" / "flows" / "example_flow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["name"] == "example"

        # ① 页面 id 由嵌套位置推导成路径形式
        page_ids: list[str] = []

        def collect(pages: dict, prefix: str = "") -> None:
            for key, page in pages.items():
                page_id = f"{prefix}/{key}" if prefix else key
                page_ids.append(page_id)
                collect(page.get("children", {}) or {}, page_id)

        collect(data["pages"])
        assert "home" in page_ids
        assert "home/qianli/battle/result" in page_ids
        assert "network_error" in page_ids

        # ② 节点的 page 必须在页面树里；没有 page 的节点是允许的（纯观察）
        node_ids = set(data["nodes"])
        for node_id, node in data["nodes"].items():
            if node.get("page"):
                assert node["page"] in page_ids, f"节点 {node_id} 声明了不存在的页面 {node['page']}"

        # ③ initial 和每条边的端点必须在节点表里
        assert data["initial"] in node_ids
        for edge in data["edges"]:
            assert edge["source"] in node_ids, f"边来源未定义: {edge['source']}"
            assert edge["target"] in node_ids, f"边目标未定义: {edge['target']}"

        # ④ stop_pages / recovery_node 也必须存在
        for page_id in data.get("stop_pages", []):
            assert page_id in page_ids
        if data.get("recovery_node"):
            assert data["recovery_node"] in node_ids

        # ⑤ 非组合查询必须给 template；叠加层必须显式声明 kind
        composites = {"AndQuery", "OrQuery", "NotQuery"}

        def check_queries(queries: list, where: str) -> None:
            for query in queries:
                assert "template" in query or query["type"] in composites, (
                    f"{where} 的查询缺少 template"
                )

        def walk_pages(pages: dict, prefix: str = "") -> None:
            for key, page in pages.items():
                page_id = f"{prefix}/{key}" if prefix else key
                check_queries(page.get("queries", []), f"页面 {page_id}")
                walk_pages(page.get("children", {}) or {}, page_id)

        walk_pages(data["pages"])

        # ⑥ 顶层叠加层：有 kind: overlay 的不属于任何父页面
        assert data["pages"]["network_error"]["kind"] == "overlay"
