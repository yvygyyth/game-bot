"""脚本注册表 —— 把"有哪些脚本"变成可以查询的东西。

按目录约定自动发现，**不维护手写清单**：

* ``games/<游戏>/<功能>/__init__.py`` 里有 ``build_config`` 和 ``build_scenario``
  -> 就是一个脚本；
* 导入失败的包不会静默消失，而是进 :func:`discovery_errors` ——
  一个写坏的脚本必须能被看见，否则"新脚本没出现在列表里"会变成谜题。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gamebot.config.schema import AppConfig
    from gamebot.flow.scenario import Scenario

__all__ = [
    "ScriptSpec",
    "discovery_errors",
    "get_script",
    "iter_feature_dirs",
    "list_scripts",
    "on_page",
]

ROOT = Path(__file__).resolve().parent

#: 一级目录里这些不当作游戏
_SKIP_GAME_DIRS = {"__pycache__", "templates", "assets", "docs", "_archive"}

#: 二级目录里这些不当作功能
_SKIP_FEATURE_DIRS = {"__pycache__", "templates", "assets", "docs"}


@dataclass(frozen=True, slots=True)
class ScriptSpec:
    """一个可运行的脚本。

    :param key: ``"<游戏>/<功能>"``，命令行和 GUI 都用它标识。
    :param module: 完整模块路径，便于定位代码。
    """

    key: str
    game: str
    slug: str
    title: str
    description: str
    module: str
    build_config: Callable[[], AppConfig]
    build_scenario: Callable[[], Scenario]

    def __repr__(self) -> str:
        return f"ScriptSpec({self.key!r}, {self.title!r})"


_SCRIPTS: dict[str, ScriptSpec] | None = None
_ERRORS: list[tuple[str, str]] = []


def iter_feature_dirs() -> Iterator[tuple[str, str, Path]]:
    """遍历所有 ``(游戏, 功能, 目录)`` 三元组。纯目录扫描，不导入。"""
    for game_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        if game_dir.name.startswith((".", "_")) or game_dir.name in _SKIP_GAME_DIRS:
            continue
        for feature_dir in sorted(p for p in game_dir.iterdir() if p.is_dir()):
            if feature_dir.name.startswith((".", "_")) or feature_dir.name in _SKIP_FEATURE_DIRS:
                continue
            if not (feature_dir / "__init__.py").is_file():
                continue
            yield game_dir.name, feature_dir.name, feature_dir


def discovery_errors() -> list[tuple[str, str]]:
    """发现过程中出错的地方，``[(key, 错误说明)]``。先调 :func:`list_scripts` 再读。"""
    list_scripts()
    return list(_ERRORS)


def list_scripts(*, refresh: bool = False) -> list[ScriptSpec]:
    """所有可运行的脚本，按 key 排序。结果会缓存（导入模块有副作用，别反复做）。"""
    global _SCRIPTS
    if _SCRIPTS is not None and not refresh:
        return sorted(_SCRIPTS.values(), key=lambda s: s.key)

    found: dict[str, ScriptSpec] = {}
    errors: list[tuple[str, str]] = []

    for game, slug, _path in iter_feature_dirs():
        key = f"{game}/{slug}"
        module_name = f"games.{game}.{slug}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            errors.append((key, f"{type(exc).__name__}: {exc}"))
            continue

        build_config = getattr(module, "build_config", None)
        build_scenario = getattr(module, "build_scenario", None)
        if not callable(build_config) or not callable(build_scenario):
            errors.append(
                (key, "缺少 build_config() 或 build_scenario() —— 见 games/README.md 的约定")
            )
            continue

        found[key] = ScriptSpec(
            key=key,
            game=game,
            slug=slug,
            title=str(getattr(module, "TITLE", slug)),
            description=str(getattr(module, "DESCRIPTION", "")),
            module=module_name,
            build_config=build_config,
            build_scenario=build_scenario,
        )

    _SCRIPTS = found
    _ERRORS[:] = errors
    return sorted(found.values(), key=lambda s: s.key)


def get_script(key: str) -> ScriptSpec:
    """按 key 取脚本。``"mingjiangsha/qianli"`` 和 ``"mingjiangsha.qianli"`` 都认。

    :raises KeyError: 不存在，message 里会列出可用的 key。
    """
    normalized = key.strip().replace(".", "/").strip("/")
    scripts = {s.key: s for s in list_scripts()}
    if normalized in scripts:
        return scripts[normalized]
    # 只给了功能名时，如果唯一就认它 —— 方便手敲
    matches = [s for s in scripts.values() if s.slug == normalized]
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(sorted(scripts)) or "（一个都没有）"
    raise KeyError(f"找不到脚本 {key!r}。可用的有: {available}")


def on_page(page_id: str) -> Callable[[Any], bool]:
    """边条件：当前页面（或任一叠加层）就是它。

    用来把"页面变了"写成显式的边::

        graph.connect("enter", "ready", condition=on_page("home/qianli"), priority=10)

    用 ``ctx.is_()`` 而不是比 ``ctx.page_id`` —— 后者不看叠加层，
    写成条件时会漏掉"结算页面 + 领奖弹窗"这种共存状态。
    """

    def _condition(ctx: Any) -> bool:
        return bool(ctx.is_(page_id))

    _condition.__name__ = f"on_page({page_id!r})"
    return _condition
