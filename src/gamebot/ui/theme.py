"""界面外观 —— 深色主题 + 少量排版约定。

深色不是为了好看：调脚本时人会在"游戏画面"和"界面"之间来回看，
浅色界面在暗色游戏旁边刺眼，而且截图预览放在浅底上很难判断亮度对不对。

用 Qt 自带的 Fusion 风格 + 一份手写调色板，不引入任何 qss 资源文件 ——
少一样要打包、要加载、要调试路径的东西。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

__all__ = ["MONO_FAMILIES", "UI_FAMILIES", "apply_dark_theme", "color_for_level", "monospace"]

#: 等宽字体候选。**必须带一个中文字体兜底** —— 只有 Consolas 的话，
#: 日志里的中文会变成方框（Consolas 没有中文字形）。
#: Qt 6 的 ``setFamilies`` 支持按顺序回退，所以这几个是"先试谁"的顺序。
MONO_FAMILIES = ("Consolas", "Cascadia Mono", "Microsoft YaHei UI", "Microsoft YaHei", "monospace")

#: 界面正文字体候选（同样留了中文兜底）
UI_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Segoe UI",
    "PingFang SC",
    "Noto Sans CJK SC",
    "sans-serif",
)

#: 各级别的颜色（深色底上要够亮又不能刺眼）
_LEVEL_COLORS: dict[int, str] = {
    10: "#7f8c8d",  # DEBUG 灰
    20: "#d8dee9",  # INFO 常规前景色
    30: "#e5c07b",  # WARNING 黄
    40: "#e06c75",  # ERROR 红
    50: "#c678dd",  # CRITICAL 紫
}


def apply_dark_theme(app: QApplication) -> None:
    """给整个应用套上深色主题。幂等。"""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e2127"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#d8dee9"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#15181d"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1e2127"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2b303b"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#d8dee9"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#d8dee9"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2b303b"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#d8dee9"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#61afef"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3e4451"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#5c6370"))

    # 禁用态别和启用态一样亮 —— 否则"置灰"这个信息就丢了
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#5c6370"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#5c6370"),
    )

    app.setPalette(palette)
    app.setFont(_ui_font())


def color_for_level(levelno: int) -> str:
    """级别对应的颜色；未知级别返回常规前景色。"""
    return _LEVEL_COLORS.get(levelno, _LEVEL_COLORS[20])


def monospace(widget: object) -> None:
    """把某个控件的字体设成等宽（日志框、树/图视图用）。

    用 ``setFamilies`` 给一串候选而不是单个名字：Qt 会按顺序回退，
    于是"数字用 Consolas 对齐、中文用雅黑显示"两件事同时成立。
    只写 "Consolas" 的话中文会变方框。
    """
    font = QFont()
    font.setFamilies(list(MONO_FAMILIES))
    font.setPointSize(9)
    font.setStyleHint(QFont.StyleHint.Monospace)
    setter = getattr(widget, "setFont", None)
    if callable(setter):
        setter(font)


def _ui_font() -> QFont:
    """界面正文的字体（同样带中文兜底）。"""
    font = QFont()
    font.setFamilies(list(UI_FAMILIES))
    font.setPointSize(9)
    return font
