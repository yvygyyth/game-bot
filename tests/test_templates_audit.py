"""模板审计 —— ``games check`` 说"查缺哪些图"，就得真的查。

## 为什么要单独测

以前 `check` 只验证"模板目录在不在"。目录在、图缺了，它照样打绿勾；
真正炸的时刻是开跑后的 ``OpenCvMatcher(preload=True)``，报的是装配期
``TemplateNotFoundError`` —— 离"我改了个路径"很远，而且中间已经浪费了一次
真机启动。

所以这里钉三件事：

1. **声明从哪来**：状态树的 queries + ``templates/__init__.py`` 的 ``T_*`` 常量；
2. **缺图必须报出来**（硬错），**没人用的图只是提示**（可能是步骤里的字面量）；
3. ``rawMaterial/`` 是原始截图，两边都不能算。
"""

from __future__ import annotations

from pathlib import Path

from gamebot.atomic.query import ImageQuery
from gamebot.state.page import PageGroup, PageLeaf, PageTree
from games._templates import audit, declared_from_module, declared_from_tree


class TestDeclaredFromTree:
    def test_collects_query_templates_with_their_page(self) -> None:
        tree = PageTree()
        tree.add(
            PageGroup(
                "home",
                children=(
                    PageLeaf("home/main", queries=(ImageQuery("home/main.png"),)),
                    PageLeaf("home/other", queries=(ImageQuery("home/other.png"),)),
                ),
            )
        )
        declared = declared_from_tree(tree)
        assert declared == {
            "home/main.png": "状态 home/main",
            "home/other.png": "状态 home/other",
        }

    def test_group_pages_declare_nothing(self) -> None:
        tree = PageTree()
        tree.add(PageGroup("home", children=(PageLeaf("home/a", queries=()),)))
        assert declared_from_tree(tree) == {}

    def test_callable_query_is_ignored(self) -> None:
        """状态允许用函数当判据 —— 那里面有没有图，静态查不到。"""
        tree = PageTree()
        tree.add(PageGroup("home", children=(PageLeaf("home/a", queries=(func_query,)),)))
        assert declared_from_tree(tree) == {}


def func_query(_result):
    return _result


class TestDeclaredFromModule:
    def test_reads_the_real_index(self) -> None:
        declared = declared_from_module("games.mingjiangsha.scripts.jingji.templates")
        assert declared["lobby/lobby.png"].endswith(".T_LOBBY")
        assert "jj/after_add.png" in declared

    def test_missing_module_is_empty_not_fatal(self) -> None:
        assert declared_from_module("games.没有这个包.templates") == {}


class TestAudit:
    def test_missing_is_reported_with_its_source(self, tmp_path: Path) -> None:
        (tmp_path / "home").mkdir()
        (tmp_path / "home" / "present.png").write_bytes(b"x")
        missing, unused = audit(
            tmp_path,
            {"home/present.png": "状态 a", "home/gone.png": "状态 b.T_GONE"},
        )
        assert missing == ["home/gone.png"]
        assert unused == []

    def test_unused_files_are_reported(self, tmp_path: Path) -> None:
        (tmp_path / "old.png").write_bytes(b"x")
        (tmp_path / "clicks").mkdir()
        (tmp_path / "clicks" / "button.png").write_bytes(b"x")
        missing, unused = audit(tmp_path, {})
        assert missing == []
        assert unused == ["clicks/button.png", "old.png"]

    def test_raw_material_is_skipped_on_both_sides(self, tmp_path: Path) -> None:
        raw = tmp_path / "rawMaterial"
        raw.mkdir()
        (raw / "screenshot.png").write_bytes(b"x")
        missing, unused = audit(tmp_path, {"rawMaterial/screenshot.png": "T_RAW"})
        assert (missing, unused) == ([], [])

    def test_non_image_files_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("裁切约定", encoding="utf-8")
        missing, unused = audit(tmp_path, {})
        assert (missing, unused) == ([], [])


class TestJingjiIsClean:
    def test_the_real_script_has_no_missing_templates(self) -> None:
        from gamebot.bootstrap import project_root
        from games import get_script

        spec = get_script("mingjiangsha/jingji")
        scenario = spec.build_scenario()
        declared = declared_from_tree(scenario.tree)
        declared.update(
            declared_from_module("games.mingjiangsha.scripts.jingji.templates")
        )
        templates = project_root() / spec.feature.templates_dir
        missing, _ = audit(templates, declared)
        assert missing == [], f"声明的模板在磁盘上找不到: {missing}"
