"""配置加载 —— YAML -> ``AppConfig``。

加载顺序（后面的覆盖前面的）::

    1. 代码里的默认值（AppConfig.defaults()）
    2. config/app.yaml
    3. 命令行覆盖（--dry-run / --window 等）

为什么不支持"多环境配置文件继承"：脚本的配置就一份，真人维护。
搞出 dev/prod/override 三层，最后没人知道生效的是哪个值。
需要临时改，用命令行参数，改完就没了。

未实现的方法见 docstring。``merge_dataclass`` 是通用工具，先实现它，
后面 load_config 只是在它上面套一层 YAML 读取。
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

from ..exceptions import ConfigError
from ..types import Region
from .schema import AppConfig, BackendKind, PathsConfig

__all__ = ["config_to_dict", "load_config", "load_regions", "merge_dataclass"]

T = TypeVar("T")


def load_config(
    path: str | Path = "config/app.yaml",
    *,
    overrides: dict[str, Any] | None = None,
) -> AppConfig:
    """读取配置文件，返回 ``AppConfig``。

    :param overrides: 点号路径的覆盖值，如 ``{"screen.window_title": "原神", "dry_run": True}``。
    :raises ConfigError: 文件缺失 / YAML 语法错误 / 未知字段 / 取值非法。
    """
    file = Path(path)
    if not file.is_file():
        if overrides:
            # 没有配置文件但给了覆盖值：从默认值出发，允许"零配置启动"
            return merge_dataclass(AppConfig.defaults(), overrides)
        raise ConfigError(f"配置文件不存在: {file}（可用 config/app.yaml 作为模板）")

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("缺少 PyYAML，请执行: uv sync") from exc

    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 解析失败: {file} — {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件顶层必须是映射(mapping): {file}")

    config = merge_dataclass(AppConfig.defaults(), raw)
    if overrides:
        config = merge_dataclass(config, overrides)
    return _finalize(config, root=file.parent.parent)


def load_regions(path: str | Path = "config/regions.yaml") -> dict[str, Region]:
    """加载命名区域表。

    期望结构::

        regions:
          hp_bar: [100, 50, 80, 30]        # [x, y, w, h]
          panel:  {x: 0, y: 0, w: 100, h: 50}
    """
    file = Path(path)
    if not file.is_file():
        return {}
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("缺少 PyYAML，请执行: uv sync") from exc

    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"区域文件顶层必须是映射: {file}")

    raw_regions = data.get("regions", data)
    if not isinstance(raw_regions, dict):
        raise ConfigError(f"regions 必须是映射: {file}")

    regions: dict[str, Region] = {}
    for name, value in raw_regions.items():
        try:
            if isinstance(value, dict):
                regions[str(name)] = Region.from_dict(value)
            else:
                regions[str(name)] = Region.from_tuple(tuple(value))
        except Exception as exc:
            raise ConfigError(f"区域 {name!r} 格式错误（应为 [x, y, w, h]）: {exc}") from exc
    return regions


def merge_dataclass(target: T, data: dict[str, Any], *, _prefix: str = "") -> T:
    """把（可能嵌套的）字典合并进 dataclass 实例，返回**新对象**。

    规则：

    * 只认识 dataclass 已声明的字段，未知字段直接抛 ``ConfigError``
      —— 静默忽略拼错的字段名是配置类 bug 的头号来源；
    * 嵌套 dataclass 递归合并；
    * 点号路径的 key（``"screen.window_title"``）会被展开；
    * ``Enum`` 字段接受字符串值；
    * ``None`` 表示"保持默认"，不覆盖（YAML 里一个字段留空是常事）。

    已实现 —— 这是配置层唯一值得现在就写对的东西。
    """
    if not is_dataclass(target):
        raise ConfigError(f"{type(target).__name__} 不是 dataclass，无法合并配置")

    expanded = _expand_dotted(data)
    valid = {f.name: f for f in fields(target)}

    unknown = sorted(set(expanded) - set(valid))
    if unknown:
        where = f"{_prefix}." if _prefix else ""
        raise ConfigError(
            f"未知配置字段: {', '.join(where + name for name in unknown)}"
            f"（可用字段: {', '.join(sorted(valid))}）"
        )

    updates: dict[str, Any] = {}
    for name, value in expanded.items():
        current = getattr(target, name)
        if value is None:
            continue
        if is_dataclass(current) and isinstance(value, dict):
            updates[name] = merge_dataclass(current, value, _prefix=f"{_prefix}{name}")
        else:
            updates[name] = _coerce(current, value, name, declared=valid[name].type)

    for name, value in updates.items():
        object.__setattr__(target, name, value)
    return target


def config_to_dict(config: AppConfig) -> dict[str, Any]:
    """导出为可 JSON/YAML 化的字典（日志"本次生效的配置"时用）。"""
    from dataclasses import asdict

    data = asdict(config)
    data["screen"]["backend"] = config.screen.backend.value
    for key in ("root", "assets", "templates", "logs", "screenshots", "journals"):
        data["paths"][key] = str(data["paths"][key])
    data["vision"]["roi"] = {k: v.to_dict() for k, v in config.vision.roi.items()}
    return data


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _expand_dotted(data: dict[str, Any]) -> dict[str, Any]:
    """``{"screen.window_title": "x"}`` -> ``{"screen": {"window_title": "x"}}``。"""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if "." not in key:
            if isinstance(value, dict):
                nested = _expand_dotted(value)
                existing = result.get(key)
                if isinstance(existing, dict):
                    existing.update(nested)
                else:
                    result[key] = nested
            else:
                result[key] = value
            continue
        head, _, tail = key.partition(".")
        branch = result.setdefault(head, {})
        if isinstance(branch, dict):
            branch.update(_expand_dotted({tail: value}))
    return result


def _coerce(current: Any, value: Any, name: str, *, declared: Any = None) -> Any:
    """把 YAML 的原始值转成字段需要的类型。

    ``declared`` 是字段的类型标注。默认值是 ``None`` 的字段（如 ``logic_size``）
    光看当前值判断不出目标类型，所以需要它 —— YAML 里列表必须变成元组，
    否则 ``(1920, 1080)`` 和 ``[1920, 1080]`` 会在比较与序列化时表现不一致。
    """
    if isinstance(current, BackendKind):
        try:
            return BackendKind(str(value).lower())
        except ValueError as exc:
            options = ", ".join(k.value for k in BackendKind)
            raise ConfigError(f"{name} 取值非法: {value!r}（可选 {options}）") from exc
    if isinstance(current, Path):
        return Path(value)
    if isinstance(value, (list, tuple)) and (
        isinstance(current, tuple) or _declares_tuple(declared)
    ):
        return tuple(value)
    if isinstance(current, Region) and isinstance(value, dict):
        return Region.from_dict(value)
    if isinstance(current, bool) and isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value


def _declares_tuple(declared: Any) -> bool:
    """判断字段类型标注是否（可能）是元组。``from __future__ import annotations``
    让标注变成字符串，所以这里做的是字符串匹配而不是类型判断。"""
    return declared is not None and "tuple[" in str(declared)


def _finalize(config: AppConfig, *, root: Path) -> AppConfig:
    """补全那些依赖其他字段的配置，并做一次校验。"""
    config.paths = PathsConfig(
        root=root,
        assets=Path(config.paths.assets),
        templates=Path(config.vision.templates_dir),
        logs=Path(config.paths.logs),
        screenshots=Path(config.paths.screenshots),
        journals=Path(config.paths.journals),
    )
    problems = config.validate()
    if problems:
        raise ConfigError("配置校验失败:\n  - " + "\n  - ".join(problems))
    return config
