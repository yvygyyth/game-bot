"""配置碎片 —— 后端种类与运行期路径。

业务脚本的装配见 :func:`gamebot.bootstrap.bootstrap_from_spec`。
"""

from __future__ import annotations

from .schema import BackendKind, RunPaths

__all__ = [
    "BackendKind",
    "RunPaths",
]
