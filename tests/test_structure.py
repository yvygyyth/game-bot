"""结构测试 —— 钉住"分层与接口清单"这个契约。

这类测试的价值不在"验证逻辑正确"，而在于：

* 有人（包括未来的我）重构时误删 / 改名某个原子方法，会立刻红；
* 分层依赖被打破（原子层反过来 import 流程层）会立刻红；
* 接口清单可以当文档读 —— 一眼看到 49 个原子方法长什么样。

**如果确实要改接口，改这个文件就是"显式承认接口变了"的动作**，
这正是我们想要的摩擦。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "gamebot"

# --------------------------------------------------------------------------- #
# 契约清单
# --------------------------------------------------------------------------- #
# L1 截图层
L1_METHODS = ["capture", "capture_region", "get_screen_size"]

# L2 Frame 层
L2_METHODS = [
    "find_image",
    "find_all_images",
    "find_text",
    "find_all_texts",
    "read_text",
    "read_number",
    "get_pixel",
    "compare_region",
    "is_image_visible",
    "crop",
    "to_numpy",
    "save",
]

# L3 Query 层
L3_QUERIES = [
    "ImageQuery",
    "AllImagesQuery",
    "TextQuery",
    "AllTextsQuery",
    "NumberQuery",
    "PixelQuery",
    "CompareQuery",
    "VisibleQuery",
    "AndQuery",
    "OrQuery",
    "NotQuery",
]

# L4 组合子层
L4_COMBINATORS = [
    "find_all_of",
    "find_any_of",
    "find_first_of",
    "find_none_of",
    "count_hits",
    "wait_any_of",
    "wait_all_of",
    "wait_until",
    "wait_stable",
    "wait_disappear",
]

# L5 动作层
L5_ACTIONS = [
    "click_point",
    "click_source_point",
    "click_image",
    "click_text",
    "double_click",
    "right_click",
    "move_to",
    "drag",
    "drag_image",
    "scroll",
    "type_text",
    "press_key",
    "hotkey",
    "sleep",
]


class TestAtomicInventory:
    def test_l1_session_methods(self) -> None:
        from gamebot.atomic.session import Session

        for name in L1_METHODS:
            assert hasattr(Session, name), f"Session 缺少 {name}"
        # L1 只该有这三个截图方法 —— 不许往 Session 上挂查询
        assert not hasattr(Session, "find_image"), "查询属于 Frame，不该出现在 Session"

    def test_l2_frame_methods(self) -> None:
        from gamebot.atomic.frame import Frame

        missing = [name for name in L2_METHODS if not hasattr(Frame, name)]
        assert not missing, f"Frame 缺少: {missing}"

    def test_l3_query_types(self) -> None:
        import gamebot.atomic.query as query_module

        missing = [name for name in L3_QUERIES if not hasattr(query_module, name)]
        assert not missing, f"query 模块缺少: {missing}"
        registry = query_module.query_registry()
        assert set(L3_QUERIES) <= set(registry), "注册表必须覆盖所有 Query 类型"

    def test_l4_combinators(self) -> None:
        import gamebot.atomic.combinators as combinators

        missing = [name for name in L4_COMBINATORS if not hasattr(combinators, name)]
        assert not missing, f"combinators 缺少: {missing}"

    def test_l5_actions(self) -> None:
        import gamebot.atomic.actions as actions

        missing = [name for name in L5_ACTIONS if not hasattr(actions, name)]
        assert not missing, f"actions 缺少: {missing}"

    def test_total_atomic_count(self) -> None:
        """50 = 设计稿的 47 + AllTextsQuery + VisibleQuery + click_source_point。"""
        total = (
            len(L1_METHODS)
            + len(L2_METHODS)
            + len(L3_QUERIES)
            + len(L4_COMBINATORS)
            + len(L5_ACTIONS)
        )
        assert total == 50


class TestKeySignatures:
    """签名是接口的一部分。抽查几个最容易被人"顺手改坏"的。"""

    def test_find_image_signature(self) -> None:
        from gamebot.atomic.frame import Frame

        params = list(inspect.signature(Frame.find_image).parameters)
        assert params == ["self", "template", "region", "confidence", "use_pyramid", "grayscale"]

    def test_find_all_images_signature(self) -> None:
        from gamebot.atomic.frame import Frame

        params = list(inspect.signature(Frame.find_all_images).parameters)
        assert params == [
            "self",
            "template",
            "region",
            "confidence",
            "max_count",
            "min_distance",
        ]

    def test_wait_any_of_signature(self) -> None:
        from gamebot.atomic.combinators import wait_any_of

        params = list(inspect.signature(wait_any_of).parameters)
        assert params == ["session", "queries", "timeout", "interval", "short_circuit"]

    def test_action_layer_takes_session_first(self) -> None:
        import gamebot.atomic.actions as actions

        for name in L5_ACTIONS:
            if name == "sleep":
                continue
            params = list(inspect.signature(getattr(actions, name)).parameters)
            assert params[0] == "session", f"{name} 的第一个参数必须是 session"

    def test_query_dataclass_fields(self) -> None:
        from dataclasses import fields

        from gamebot.atomic.query import ImageQuery, NumberQuery, PixelQuery

        assert [f.name for f in fields(ImageQuery)] == [
            "template",
            "region",
            "confidence",
            "use_pyramid",
            "grayscale",
        ]
        assert "comparator" in [f.name for f in fields(NumberQuery)]
        assert [f.name for f in fields(PixelQuery)] == ["point", "expected_color", "tolerance"]


# --------------------------------------------------------------------------- #
# 分层依赖检查
# --------------------------------------------------------------------------- #
LAYER_RULES = {
    # 层目录 -> 禁止导入的上层模块
    "atomic": {"state", "flow", "execution", "context", "bootstrap"},
    "state": {"flow", "execution", "bootstrap"},
    "execution": {"flow", "bootstrap"},
    "flow": {"bootstrap"},
    "config": {"state", "flow", "execution", "context", "bootstrap"},
}


def _iter_modules(layer: str):
    yield from sorted((SRC / layer).rglob("*.py"))


def _resolve_import(path: Path, node: ast.ImportFrom) -> str | None:
    """把相对 import 解析成 ``gamebot.xxx`` 形式。"""
    if node.level == 0:
        return node.module
    package = path.relative_to(SRC.parent).with_suffix("")
    parts = list(package.parts[:-1])  # 去掉文件名，得到包路径
    base_len = len(parts) - (node.level - 1)
    if base_len < 0:
        return None
    base = parts[:base_len]
    if node.module:
        base = base + node.module.split(".")
    return ".".join(base)


def _imported_gamebot_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            resolved = _resolve_import(path, node)
            if resolved and resolved.startswith("gamebot"):
                found.add(resolved)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("gamebot"):
                    found.add(alias.name)
    return found


@pytest.mark.parametrize("layer", sorted(LAYER_RULES))
def test_layer_does_not_import_upward(layer: str) -> None:
    forbidden = LAYER_RULES[layer]
    violations: list[str] = []
    for path in _iter_modules(layer):
        for module in _imported_gamebot_modules(path):
            parts = module.split(".")
            if len(parts) >= 2 and parts[1] in forbidden:
                violations.append(f"{path.name} -> {module}")
    assert not violations, (
        f"{layer} 层出现了向上依赖（分层被打破）:\n  " + "\n  ".join(violations)
    )


def test_types_layer_has_no_internal_dependency() -> None:
    """L0 不许依赖框架内任何东西 —— 它是公共语言。"""
    imports = _imported_gamebot_modules(SRC / "types.py")
    assert not imports, f"types.py 不应导入框架内模块: {imports}"


def test_atomic_imports_without_third_party() -> None:
    """``import gamebot.atomic`` 不该拉起 numpy / cv2 / mss。

    这是"没装依赖也能看结构、也能跑通类型层"的保证。
    """
    import subprocess
    import sys

    code = (
        "import sys;"
        "import gamebot.atomic;"
        "heavy=[m for m in ('numpy','cv2','mss','yaml','PIL') if m in sys.modules];"
        "print(','.join(heavy));"
        "raise SystemExit(1 if heavy else 0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(SRC.parent), "PATH": ""},
        check=False,
    )
    assert completed.returncode == 0, f"原子层导入了重依赖: {completed.stdout} {completed.stderr}"
