"""模板审计 —— **声明过的图**和**磁盘上的图**对一遍。

## 为什么要有它

写识图脚本最容易卡住的一步是"图不对"：路径改了、裁歪了、忘了放。
而这件事的报错时机非常差 —— 现在 `check` 只验证定义和模板**目录在不在**，
真正缺图要等跑起来、`OpenCvMatcher(preload=True)` 那一刻才炸，
报的是装配期的 `TemplateNotFoundError`，离"我改了个路径"很远。

所以 `check` 现在两个方向都查：

* **声明了但磁盘上没有** -> 失败（这是硬错，跑起来必炸）；
* **磁盘上有但没人声明** -> 只是提示（可能是步骤里写的字面量，也可能是旧图）。

## 声明从哪来

1. **状态树的 queries**（`ImageQuery.template`）—— 状态锚点；
2. **`templates/__init__.py` 里的 `T_*` 常量** —— 这是路径的权威出处，
   步骤里写的图基本都从这儿来。

步骤函数体里的字面量**查不到**（那是运行期才走到的字符串），所以第二种来源
才那么重要：**图路径一律走 `T_*` 常量，别在调用点裸写字符串**（games/README.md
里那条约定，这里就是它换来的好处）。

## 跳过什么

`templates/rawMaterial/`（原始截图，供重裁）两边都跳过：它既不是运行期要用的图，
也不该被当成"没人引用的垃圾"报出来。
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["audit", "declared_from_module", "declared_from_tree"]


#: 这些子目录里的 png 不参与审计（原始素材，不是运行期模板）
SKIP_DIRS = ("rawMaterial",)

#: 只审计图片
_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}


def _template_of(query: Any) -> str | None:
    """从查询描述符里取模板路径（函数式查询取不到，返回 None）。"""
    template = getattr(query, "template", None)
    return template if isinstance(template, str) else None


def declared_from_tree(tree: Any) -> dict[str, str]:
    """状态树里声明的模板：``{路径: 谁要它}``。

    ``谁要它`` 写的是状态 id —— 缺图时能直接说清"哪一页认不出来"。
    """
    declared: dict[str, str] = {}
    for page_id, page in getattr(tree, "pages", {}).items():
        queries = getattr(page, "queries", ()) or ()
        for query in queries:
            path = _template_of(query)
            if path:
                declared.setdefault(path, f"状态 {page_id}")
    return declared


def declared_from_module(module_name: str) -> dict[str, str]:
    """模板索引模块里的 ``T_*`` 常量：``{路径: 常量名}``。

    导入失败就返回空 —— 调用方（``check``）已经先验证过脚本定义本身，
    这里不该因为一个可选模块把整条检查弄挂。
    """
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return {}
    return {
        value: f"{module_name}.{name}"
        for name, value in vars(module).items()
        if name.startswith("T_") and isinstance(value, str) and value.strip()
    }


def _iter_templates(directory: Path) -> set[str]:
    """目录下所有模板（相对路径，posix 风格），跳过 ``SKIP_DIRS``。"""
    if not directory.is_dir():
        return set()
    found: set[str] = set()
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _SUFFIXES:
            continue
        relative = path.relative_to(directory).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(directory).parts):
            continue
        found.add(relative)
    return found


def _is_skipped(template: str) -> bool:
    return any(part in SKIP_DIRS for part in Path(template).parts)


def audit(
    templates_dir: Path,
    declared: Mapping[str, str],
) -> tuple[list[str], list[str]]:
    """对一遍。

    :return: ``(缺的, 没被声明的)``，两个都排好序。
        第一个是**硬错**（跑起来必炸），第二个只是提示。
    """
    checked = {path: source for path, source in declared.items() if not _is_skipped(path)}
    missing = sorted(path for path in checked if not (templates_dir / path).is_file())
    on_disk = _iter_templates(templates_dir)
    unused = sorted(on_disk - set(declared))
    return missing, unused
