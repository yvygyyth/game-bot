"""脚本注册表 —— 把"有哪些脚本"变成可以查询的东西。

按目录约定自动发现，**不维护手写清单**：

* ``games/<游戏>/<功能>/__init__.py`` 里有 ``build_config`` 和 ``build_scenario``
  -> 就是一个脚本，key 是 ``"<游戏>/<功能>"``；
* 导入失败的包不会静默消失，而是进 :func:`discovery_errors` ——
  一个写坏的脚本必须能被看见，否则"新脚本没出现在列表里"会变成谜题。

**布局只有一种：``games/<游戏>/<功能>/``。** 游戏目录是容器，脚本永远在功能目录里。
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
    "iter_script_dirs",
    "list_scripts",
    "on_page",
    "within_page",
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


def _game_dirs() -> list[Path]:
    return [
        p
        for p in sorted(ROOT.iterdir())
        if p.is_dir() and not p.name.startswith((".", "_")) and p.name not in _SKIP_GAME_DIRS
    ]


def _feature_dirs(game_dir: Path) -> list[Path]:
    return [
        p
        for p in sorted(game_dir.iterdir())
        if p.is_dir()
        and not p.name.startswith((".", "_"))
        and p.name not in _SKIP_FEATURE_DIRS
        and (p / "__init__.py").is_file()
    ]


def iter_script_dirs() -> Iterator[tuple[str, str, str, Path]]:
    """遍历所有 ``(key, 游戏, 功能, 目录)``。纯目录扫描，不导入。

    布局只有一种：``games/<游戏>/<功能>/``，key 是 ``"<游戏>/<功能>"``。

    游戏目录下**没有**功能子目录时不会产出脚本 —— 那种游戏只是还没写脚本，
    不是错误（新建一个游戏目录、页面和模板先放好，是正常的中间状态）。
    """
    for game_dir in _game_dirs():
        for feature_dir in _feature_dirs(game_dir):
            yield (
                f"{game_dir.name}/{feature_dir.name}",
                game_dir.name,
                feature_dir.name,
                feature_dir,
            )


def _misplaced_scripts() -> list[tuple[str, str]]:
    """找出把脚本函数直接写在游戏目录 ``__init__.py`` 里的地方。

    那是**位置错了**，不是另一种布局 —— 游戏目录是容器，脚本必须有自己的功能目录。
    这种写法不会被 :func:`iter_script_dirs` 扫到，于是表现为"脚本没出现在列表里"，
    很难查；所以这里专门报一条，把该放哪儿说清楚。
    """
    found: list[tuple[str, str]] = []
    for game_dir in _game_dirs():
        if _feature_dirs(game_dir):
            # 有功能目录就说明这是个正常的容器，跳过（不 import，避免副作用）
            continue
        init = game_dir / "__init__.py"
        if not init.is_file():
            continue
        # 文本粗判就够了：这里只为了给一句人话提示，不值得为它 import 一个坏模块
        text = init.read_text(encoding="utf-8", errors="replace")
        if "def build_scenario" in text or "def build_config" in text:
            found.append(
                (
                    game_dir.name,
                    f"games/{game_dir.name}/__init__.py 里有 build_config/build_scenario —— "
                    f"脚本不能直接放在游戏目录下。给它建一个功能目录："
                    f"games/{game_dir.name}/<功能>/，key 就是 "
                    f"'{game_dir.name}/<功能>'",
                )
            )
    return found


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
    errors: list[tuple[str, str]] = _misplaced_scripts()

    for key, game, slug, _path in iter_script_dirs():
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
    """按 key 取脚本。``"mingjiangsha/jingji"`` 和 ``"mingjiangsha.jingji"`` 两种写法都认。

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
    """边条件：当前页面（或任一叠加层）**就是**它。

    用来把"页面变了"写成显式的边::

        graph.connect("enter", "ready", condition=on_page("home/qianli"), priority=10)

    用 ``ctx.is_()`` 而不是比 ``ctx.page_id`` —— 后者不看叠加层，
    写成条件时会漏掉"结算页面 + 领奖弹窗"这种共存状态。

    注意它问的是**精确**的"就是它"，不是"它的 UI 还在不在"。
    要后者用 :func:`within_page`。
    """

    def _condition(ctx: Any) -> bool:
        return bool(ctx.is_(page_id))

    _condition.__name__ = f"on_page({page_id!r})"
    return _condition


def within_page(page_id: str) -> Callable[[Any], bool]:
    """边条件：当前页面是它**或它的后代**（"这棵子树的 UI 还在屏幕上"）。

    和 :func:`on_page` 的区别只在子树里看得出来：页面停在 ``root/menu/list`` 时，
    ``within_page("root")`` 是 True（root 的顶栏底栏确实还画着），
    而 ``on_page("root")`` 是 False。

    什么时候用哪个：

    * **精确转移**（"结算页出现了，去处理结算"）-> :func:`on_page`；
    * **兜底回收**（"不管跑到哪一层了，回顶层重来"）-> :func:`within_page`。

    两者框架级都还没有 —— 现在它们只是"读 ctx 的谓词"，
    因为 :class:`~gamebot.flow.graph.Edge` 本来就允许塞 lambda。
    等这类谓词攒够几个，再考虑收进框架变成可序列化的 Query。
    """

    def _condition(ctx: Any) -> bool:
        match = getattr(ctx, "page", None)
        return bool(match is not None and page_id in match.path)

    _condition.__name__ = f"within_page({page_id!r})"
    return _condition
