"""日志大框。

用 ``QPlainTextEdit`` 而不是 ``QTextEdit``：前者为"大量追加纯文本"优化过，
而且自带 ``maximumBlockCount``，跑几个小时也不会越吃越多内存。

颜色不用 HTML（每行一次 HTML 解析，量大时明显卡），改成
``QTextCursor`` + ``setCharFormat`` —— 只设置字符格式，不解析。
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...utils.logging import DEFAULT_DATEFMT, DEFAULT_FORMAT
from ..logbridge import LogBridge
from ..theme import color_for_level, monospace

__all__ = ["LogView"]

#: 级别下拉框的选项
_LEVELS: tuple[tuple[str, int], ...] = (
    ("DEBUG", logging.DEBUG),
    ("INFO", logging.INFO),
    ("WARNING", logging.WARNING),
    ("ERROR", logging.ERROR),
)

#: 显示多久的历史。和 LogBridge 的环形缓冲上限对齐。
MAX_BLOCKS = 5000


class LogView(QWidget):
    """日志面板：级别过滤 + 自动滚动 + 清空 + 导出。"""

    def __init__(self, bridge: LogBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._min_level = logging.INFO
        self._formatter = logging.Formatter(DEFAULT_FORMAT, DEFAULT_DATEFMT)

        self._text = QPlainTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(MAX_BLOCKS)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text.setPlaceholderText("日志会出现在这里")
        monospace(self._text)

        self._level = QComboBox(self)
        for name, value in _LEVELS:
            self._level.addItem(name, value)
        self._level.setCurrentIndex(1)  # INFO
        self._level.setToolTip("只显示这个级别及以上")
        self._level.currentIndexChanged.connect(self._on_level_changed)

        self._autoscroll = QCheckBox("自动滚动", self)
        self._autoscroll.setChecked(True)
        self._clear_btn = QPushButton("清空", self)
        self._clear_btn.clicked.connect(self.clear)
        self._export_btn = QPushButton("导出", self)
        self._export_btn.clicked.connect(self._on_export)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(QLabel("级别", self))
        bar.addWidget(self._level)
        bar.addWidget(self._autoscroll)
        bar.addWidget(QLabel(f"最多保留 {MAX_BLOCKS} 行", self))
        bar.addStretch(1)
        bar.addWidget(self._clear_btn)
        bar.addWidget(self._export_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(bar)
        layout.addWidget(self._text, 1)

        bridge.recordArrived.connect(self.append_record)

    # ------------------------------------------------------------------ #
    # 对外
    # ------------------------------------------------------------------ #
    def replay(self) -> None:
        """按当前过滤条件把缓冲里的记录重画一遍。

        界面刚起来、或者用户换了级别时调 —— 这样"过滤"是重新渲染，
        而不是只能影响之后的日志。
        """
        self._text.clear()
        for record in self._bridge.snapshot(level=self._min_level):
            self._append(record, force=True)

    def append_record(self, record: logging.LogRecord) -> None:
        """槽：收到一条日志（已经在界面线程）。"""
        if record.levelno < self._min_level:
            return
        self._append(record)

    def clear(self) -> None:
        self._text.clear()
        self._bridge.clear()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _append(self, record: logging.LogRecord, *, force: bool = False) -> None:
        if not force and record.levelno < self._min_level:
            return

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color_for_level(record.levelno)))
        cursor.setCharFormat(fmt)

        # 同一个 formatter 打出来的行宽稳定：时间 | 级别 | logger | 消息
        cursor.insertText(self._format(record) + "\n")

        if self._autoscroll.isChecked():
            self._text.verticalScrollBar().setValue(self._text.verticalScrollBar().maximum())

    def _format(self, record: logging.LogRecord) -> str:
        line = self._formatter.format(record)
        # "gamebot.flow.engine" -> "flow.engine"：界面上省点横向空间
        return line.replace("| gamebot.", "| ")

    def _on_level_changed(self) -> None:
        self._min_level = int(self._level.currentData())
        self.replay()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", "gamebot.log", "日志 (*.log *.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                for record in self._bridge.snapshot():
                    handle.write(self._format(record) + "\n")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
