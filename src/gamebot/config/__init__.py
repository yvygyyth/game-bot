"""配置层 —— 把 YAML 变成有类型、有默认值、会校验的 ``AppConfig``。

三件事：

* ``schema.py`` —— 字段定义与默认值（改配置项只改这里）
* ``loader.py`` —— YAML 读取、合并、覆盖、校验
* 命名区域（``config/regions.yaml``）—— 把"坐标"从代码里挪到配置里

为什么要"区域命名"：脚本里写 ``Region(940, 520, 40, 40)`` 是没法维护的，
写 ``cfg.region("confirm_button")`` 才能在一处改、处处生效。
"""

from __future__ import annotations

from .loader import config_to_dict, load_config, load_regions, merge_dataclass
from .schema import (
    AppConfig,
    BackendKind,
    LoggingConfig,
    PathsConfig,
    ScreenConfig,
    TimingConfig,
    VisionConfig,
)

__all__ = [
    "AppConfig",
    "BackendKind",
    "LoggingConfig",
    "PathsConfig",
    "ScreenConfig",
    "TimingConfig",
    "VisionConfig",
    "config_to_dict",
    "load_config",
    "load_regions",
    "merge_dataclass",
]
