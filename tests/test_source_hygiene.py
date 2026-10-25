"""源码卫生 —— 机械的、能"当场指名道姓"的规则。

现在只有一条：**源码与文档不许带 UTF-8 BOM**。

## 为什么值得单独一个文件

BOM 对 Python 解释器是**隐形**的（``import`` 自己会吃掉它），所以带 BOM 的源码
照样能跑、pytest 也全绿 —— 直到某个**按纯文本读源码**的工具碰到它：
``ast.parse(read_text("utf-8"))`` 直接抛
``SyntaxError: invalid non-printable character U+FEFF``，
报错只说"有个非法字符"，不说"就是文件开头那三个字节"。

2026-10 就发生过：``tests/test_structure.py`` 的分层依赖检查崩了，
看起来像"结构测试坏了"，实际是 ``config/schema.py`` 和 ``flow/bindings.py``
被某个编辑器加了 BOM。修的方向完全不同。

所以职责分成两处：

* **能容忍的地方容忍**（检查器一律 ``utf-8-sig``，见 ``test_structure.py``）；
* **该不该有**由这里明确回答 —— 报出具体路径，而不是让下游工具随便崩。

## 为什么不做成 ruff 规则

ruff 没有"禁止 BOM"的规则（BOM 在 UTF-8 规范里是合法的），
而这条约定是**这个仓库**的（源码、文档、配置都走纯 UTF-8），
所以用 pytest 钉住它更直接，也更容易写清理由。
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 要检查的目录（相对仓库根）。业务层和测试也在里面 —— 它们同样是"被读的源码"。
CHECKED_DIRS = ("src", "games", "tests", "docs", "config")

#: 这些后缀按纯文本对待
CHECKED_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".ps1", ".txt"}

#: 这些目录名出现在路径里就跳过（缓存与虚拟环境不是源码）
SKIP_PARTS = {"__pycache__", ".venv", ".git", ".uv-cache", ".ruff_cache", ".pytest_cache"}

_BOM = b"\xef\xbb\xbf"


def _iter_sources() -> list[pathlib.Path]:
    """所有要检查的文件（目录内 + 仓库根的 ``*.md``）。"""
    found: list[pathlib.Path] = []
    for name in CHECKED_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in CHECKED_SUFFIXES:
                continue
            if SKIP_PARTS.intersection(path.parts):
                continue
            found.append(path)
    # 根的 README.md 是入口文件，也在范围内
    found.extend(sorted(ROOT.glob("*.md")))
    return found


def _has_bom(path: pathlib.Path) -> bool:
    return path.read_bytes()[:3] == _BOM


def test_the_scanner_actually_scans_something() -> None:
    """先确认扫描器真的看到了文件。

    空集合也会"全部通过" —— 那正是这个仓库反复警惕的**假绿勾**
    （见 ``games/mingjiangsha/scripts/jingji/README.md`` 关于"没样本也算过"那段）。
    """
    sources = _iter_sources()
    assert len(sources) > 80, f"只扫到 {len(sources)} 个文件，扫描器是不是坏了？"
    suffixes = {p.suffix.lower() for p in sources}
    assert {".py", ".md"} <= suffixes, f"扫到的类型不对: {suffixes}"


def test_no_source_file_starts_with_a_bom() -> None:
    """源码/文档/配置一律纯 UTF-8，不许有 BOM。

    报错里给**全部**路径，而不只是第一个 —— 这种问题是"某个编辑器/脚本一次性
    写了一批"，一次看完再动手，比修一个跑一遍省事。
    """
    offenders = [p.relative_to(ROOT).as_posix() for p in _iter_sources() if _has_bom(p)]
    assert not offenders, (
        "这些文件开头有 UTF-8 BOM（U+FEFF），请存成不带 BOM 的 UTF-8：\n  "
        + "\n  ".join(offenders)
        + "\n（原因：解释器能容忍，但 ast / 其他按文本读源码的工具会直接报"
        "'invalid non-printable character U+FEFF'）"
    )
