"""本地控制台界面（可选依赖 PySide6）。

设计见 ``docs/ui.md``。这个包**只依赖框架**，不直接认识任何具体游戏 ——
它通过 :mod:`gamebot.ui.registry` 间接读业务层的脚本注册表，
而那一处是**延迟导入**的，业务层不可用时界面照样能开。

用法::

    from gamebot.ui import run_ui
    run_ui()

或者命令行：``gamebot ui``。
"""

from __future__ import annotations

__all__ = ["QT_HINT", "run_ui", "ui_available"]

QT_HINT = "界面依赖没装。执行: uv sync --extra ui"


def require_qt() -> None:
    """确认 Qt 可用。

    :raises ConfigError: 没装 —— 给的是"怎么装"而不是 traceback。
        可选依赖的特点就是"没装也不该炸得莫名其妙"。
    """
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 取决于环境
        from ..exceptions import ConfigError

        raise ConfigError(QT_HINT) from exc


def run_ui(
    *,
    script_key: str = "",
    snapshot: str = "",
    argv: list[str] | None = None,
) -> int:
    """打开界面并进入事件循环，返回进程退出码。

    :param script_key: 预选的脚本 key（``"mingjiangsha/jingji"``）。
    :param snapshot: 非空时**不开窗口**，渲染一张界面截图存到这个路径就退出。
        用途：无头环境下给文档配图、CI 里验证界面能起来。需要 ``QT_QPA_PLATFORM=offscreen``。
    """
    require_qt()
    from .app import main

    return main(script_key=script_key, snapshot=snapshot, argv=argv)


def ui_available() -> tuple[bool, str]:
    """``(能不能用, 说明)``。给 CLI 和自己检查用，不抛异常。"""
    try:
        require_qt()
    except Exception as exc:
        return False, str(exc)
    return True, ""
