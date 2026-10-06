"""业务层脚本注册表的读取 —— **整个 UI 里唯一碰 ``games`` 的地方**。

## 为什么要单独隔一层

``gamebot`` 是**框架**，不该在导入期依赖业务层（``games/``）。原因不是洁癖：

* 业务层可能没装、可能不在 ``sys.path`` 上（比如从别的目录启动）；
* 这时候界面应该**照常打开**，只是"选脚本"那一栏是空的 + 一句说明，
  而不是启动就 traceback。

所以这里做三件事：延迟导入、把异常变成"说明文本"、把注册表的数据
整理成界面好用的形状。界面其余部分只看 :class:`ScriptEntry` /
:class:`ScriptDetails`，不认识 ``games``。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "NodeEntry",
    "ScriptDetails",
    "ScriptEntry",
    "load_details",
    "load_scripts",
]

#: 业务层的导入说明（列表为空时显示给人看）
_FALLBACK_HINT = (
    "读不到脚本列表。业务层在项目根的 games/ 目录下，"
    "请从项目根目录启动（python -m gamebot ui），或者用 --script 手写 key。"
)


@dataclass(frozen=True, slots=True)
class NodeEntry:
    """流程图里的一个节点，给"起始节点"下拉框和节点详情用。"""

    id: str
    title: str
    state: str | None
    """它关联的状态 —— 来自**关联表**，不是节点自己（节点不知道自己是哪个状态）。"""
    steps: int
    out_edges: int
    is_initial: bool

    @property
    def label(self) -> str:
        mark = "★ " if self.is_initial else ""
        state = self.state or "（不关联状态）"
        return f"{mark}{self.id}  —  {state}"


@dataclass(frozen=True, slots=True)
class ScriptEntry:
    """注册表里的一个脚本。``spec`` 是业务层的 ScriptSpec（界面不碰它的内部）。"""

    key: str
    game: str
    slug: str
    title: str
    description: str
    spec: Any = field(repr=False, default=None)

    @property
    def label(self) -> str:
        return self.title if self.title == self.key else f"{self.title}"


@dataclass(frozen=True, slots=True)
class ScriptDetails:
    """一个脚本的静态信息 —— 全部来自 ``Scenario``，不需要连游戏。"""

    pages: int = 0
    nodes: int = 0
    edges: int = 0
    unclaimed: tuple[str, ...] = ()
    node_list: tuple[NodeEntry, ...] = ()
    tree_text: str = ""
    graph_text: str = ""
    template_roots: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems


def load_scripts() -> tuple[list[ScriptEntry], str]:
    """读业务层的脚本注册表。

    :return: ``(脚本列表, 说明)``。列表为空时说明里写清为什么。
    """
    games, error = _import_games()
    if games is None:
        return [], f"{_FALLBACK_HINT}\n\n（{error}）"

    try:
        scripts = games.list_scripts()
    except Exception as exc:
        return [], f"{_FALLBACK_HINT}\n\n（{type(exc).__name__}: {exc}）"

    entries = [
        ScriptEntry(
            key=s.key,
            game=s.game,
            slug=s.slug,
            title=s.title,
            description=s.description,
            spec=s,
        )
        for s in scripts
    ]
    errors = games.discovery_errors()
    note = ""
    if errors:
        note = "；".join(f"{key}: {msg}" for key, msg in errors)
    return entries, note


def _import_games() -> tuple[Any, str]:
    """导入业务层。返回 ``(模块, 失败说明)``。

    为什么要多试一次：``uv run gamebot ui`` 是通过 console script 启动的，
    那种情况下 ``sys.path[0]`` 是虚拟环境的 ``Scripts/`` 目录，**不是当前目录** ——
    于是项目根下的 ``games/`` 不在导入路径里。补上 cwd 再试一次。

    只做这一次补救、只加 cwd 一个路径：不猜、不乱扫路径。
    """
    try:
        import games

        return games, ""
    except ImportError:
        pass

    root = str(Path.cwd())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import games

        return games, ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def load_details(entry: ScriptEntry) -> ScriptDetails:
    """把一个脚本的静态信息算出来。

    **完全在装配期**：构造 Scenario、校验、数节点数边，都不碰游戏窗口。
    失败时错误进 ``problems``，界面照常显示其它信息 ——
    一个脚本写坏了不该让整个界面变成空白。
    """
    if entry.spec is None:
        return ScriptDetails(problems=("这个脚本没有注册信息",))

    problems: list[str] = []
    try:
        scenario = entry.spec.build_scenario()
    except Exception as exc:
        return ScriptDetails(
            problems=(f"构造 Scenario 失败: {type(exc).__name__}: {exc}",),
        )

    try:
        scenario.validate()
    except Exception as exc:
        problems.append(f"{type(exc).__name__}: {exc}")

    node_list = tuple(
        NodeEntry(
            id=node.id,
            title=node.display,
            state=scenario.bindings.state_of(node.id),
            steps=len(node.steps),
            out_edges=len(scenario.graph.out_edges(node.id)),
            is_initial=(node.id == scenario.graph.initial),
        )
        for node in scenario.graph.nodes.values()
    )

    roots: tuple[str, ...] = ()
    try:
        roots = tuple(str(p) for p in entry.spec.build_config().template_roots())
    except Exception as exc:
        problems.append(f"构造配置失败: {type(exc).__name__}: {exc}")

    return ScriptDetails(
        pages=len(scenario.tree),
        nodes=len(scenario.graph.nodes),
        edges=len(scenario.graph.edges),
        unclaimed=scenario.unclaimed_pages(),
        node_list=node_list,
        tree_text=scenario.tree.describe(),
        graph_text=scenario.graph.describe(),
        template_roots=roots,
        problems=tuple(problems),
    )


def shorten_path(path: str, *, root: Path | None = None) -> str:
    """把绝对路径缩成相对项目根的写法，界面上短一点。"""
    base = root or Path.cwd()
    try:
        return str(Path(path).relative_to(base))
    except ValueError:
        return path
