"""识图 / OCR 日志面板 —— **每次匹配的痕迹 + 带框的图**。

## 为什么这块取代了"实时画面"

实时画面回答的是"屏幕现在长什么样"，而调脚本时要回答的是另外三个问题：

1. **它认到的是哪一块？** —— 命中框画在图上，一眼就看出圈对了没有；
2. **没命中的时候它在哪块里找？** —— 把搜索范围（ROI）也画出来，
   才能区分"圈错了"和"圈对了但阈值太高"；
3. **分数差多少？** —— 表格里直接给分数，不用猜。

所以上面是**带框的图**（每次换帧存一张，最多留 ``vision.record_keep`` 张），
下面是**结构化日志表格**（查了什么、在哪搜、几分、命中还是没中）。

## 数据从哪来

``ctx.recorder``（``vision/recorder.py``）。它在 Matcher / TextReader 外面包了一层，
所以这个 Session 上的**所有**查询都会被记下来 —— 不用在每个调用点插桩，
也就不会漏掉某个分支。

刷新用 ``QTimer`` 轮询而不是信号：记录发生在引擎线程，而 ``on_record``
回调是在查询线程里同步跑的（那里不能碰控件）。轮询 300ms 一次足够，
也避免"高频信号把界面线程压满"。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import monospace

if TYPE_CHECKING:
    from gamebot.vision.recorder import MatchRecord, RecognitionRecorder

__all__ = ["RecognitionPanel"]

#: 表格里最多显示多少行（新的在最上面）。太多行刷起来会卡。
MAX_ROWS = 200

#: 轮询间隔（毫秒）。记录发生在别的线程，这里只拉快照。
POLL_MS = 300

_COLUMNS = ("#", "时间", "类型", "目标", "结果", "分数", "位置", "搜索范围", "图")

_HIT_COLOR = "#4ec9b0"
_MISS_COLOR = "#e5c07b"


class RecognitionPanel(QWidget):
    """上一次识图匹配的图 + 全部匹配的结构化日志。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._recorder: RecognitionRecorder | None = None
        self._shown = 0

        # ---- 左：最近几张带框的图 ----
        self._shots = QListWidget(self)
        self._shots.setMaximumWidth(240)
        self._shots.currentItemChanged.connect(self._on_shot_selected)

        self._canvas = QLabel("还没有识图记录 —— 跑一次脚本，或点「抓一张」", self)
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setStyleSheet("background:#1e1e1e; color:#7f8c8d; border:1px solid #3d3d40;")
        self._canvas.setMinimumSize(320, 200)
        self._caption = QLabel("—", self)
        monospace(self._caption)

        right = QVBoxLayout()
        right.addWidget(self._canvas, 1)
        right.addWidget(self._caption)

        top = QSplitter(Qt.Orientation.Horizontal, self)
        holder = QWidget(self)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(QLabel("最近带框的图（点一张看大图）", self))
        holder_layout.addWidget(self._shots, 1)
        top.addWidget(holder)
        top_right = QWidget(self)
        top_right.setLayout(right)
        top.addWidget(top_right)
        top.setStretchFactor(0, 0)
        top.setStretchFactor(1, 1)

        # ---- 下：结构化日志 ----
        self._table = QTableWidget(0, len(_COLUMNS), self)
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        monospace(self._table)
        self._table.itemSelectionChanged.connect(self._on_row_selected)

        self._only_miss = QCheckBox("只看未命中", self)
        self._only_miss.toggled.connect(lambda _on: self._rebuild_rows(force=True))
        self._open_dir = QPushButton("打开图目录", self)
        self._open_dir.clicked.connect(self._open_directory)
        self._clear_btn = QPushButton("清空", self)
        self._clear_btn.clicked.connect(self._clear)

        bar = QHBoxLayout()
        bar.addWidget(self._only_miss)
        bar.addStretch(1)
        bar.addWidget(self._clear_btn)
        bar.addWidget(self._open_dir)

        bottom = QWidget(self)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addLayout(bar)
        bottom_layout.addWidget(self._table, 1)

        vertical = QSplitter(Qt.Orientation.Vertical, self)
        vertical.addWidget(top)
        vertical.addWidget(bottom)
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(vertical, 1)

        # 记录在别的线程写，这里轮询拉快照 —— 不用跨线程信号，
        # 也就不会因为"记录太多"把界面线程压满。
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ------------------------------------------------------------------ #
    def set_recorder(self, recorder: RecognitionRecorder | None) -> None:
        """换记录器（换脚本 / 重新装配时调）。"""
        self._recorder = recorder
        self._shown = 0
        self._shots.clear()
        self._table.setRowCount(0)
        self._canvas.setText(
            "还没有识图记录 —— 跑一次脚本，或点「抓一张」"
            if recorder is not None
            else "配置里关掉了识图记录（vision.record = false）"
        )
        self._caption.setText("—")
        self.refresh(force=True)

    @Slot()
    def refresh(self, *, force: bool = False) -> None:
        """拉一次快照。记录条数没变就什么都不做（省掉无谓的重排）。"""
        recorder = self._recorder
        if recorder is None:
            return
        entries = recorder.entries()
        if not force and len(entries) == self._shown:
            return
        self._shown = len(entries)
        self._rebuild_rows(force=True)
        self._rebuild_shots(recorder)

    # ------------------------------------------------------------------ #
    def _rebuild_rows(self, *, force: bool = False) -> None:
        recorder = self._recorder
        if recorder is None:
            return
        entries = recorder.entries()
        if self._only_miss.isChecked():
            entries = [e for e in entries if not e.hit]
        entries = entries[-MAX_ROWS:]
        entries.reverse()  # 新的在最上面

        self._table.setRowCount(len(entries))
        for row, record in enumerate(entries):
            for column, value in enumerate(_cells(record)):
                item = QTableWidgetItem(value)
                if column in (0, 5):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if column == 4:
                    item.setForeground(
                        Qt.GlobalColor.green if record.hit else Qt.GlobalColor.yellow
                    )
                item.setData(Qt.ItemDataRole.UserRole, record.frame_path)
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()

    def _rebuild_shots(self, recorder: RecognitionRecorder) -> None:
        """列出现存的带框图（新的在前）。只在集合变了的时候重建。"""
        files = recorder.latest_frames()
        existing = [
            self._shots.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._shots.count())
        ]
        if files == existing:
            return
        self._shots.blockSignals(True)
        self._shots.clear()
        for path in files:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._shots.addItem(item)
        self._shots.blockSignals(False)
        if files:
            self._shots.setCurrentRow(0)

    # ------------------------------------------------------------------ #
    def _on_shot_selected(self, current: QListWidgetItem | None, _previous: Any) -> None:
        if current is None:
            return
        self._show_image(current.data(Qt.ItemDataRole.UserRole))

    def _on_row_selected(self) -> None:
        """点某一行日志 -> 显示它那一帧的图。

        **这就是"看到它识别的区域"最直接的路径**：从"哪次匹配有问题"直接跳到
        那张画着框的图。
        """
        rows = {index.row() for index in self._table.selectedIndexes()}
        if not rows:
            return
        item = self._table.item(min(rows), 0)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._show_image(path)

    def _show_image(self, path: str) -> None:
        if not path:
            self._canvas.setText("这一次匹配没有对应的图（记录上限为 0？）")
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._canvas.setText(f"读不出来: {path}")
            return
        self._canvas.setPixmap(
            pixmap.scaled(
                self._canvas.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._canvas.setToolTip(path)
        self._caption.setText(f"{Path(path).name}　{pixmap.width()}x{pixmap.height()}")

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        # 放大后重新按新尺寸缩一次，否则图会一直是旧尺寸
        pixmap = self._canvas.pixmap()
        if pixmap is not None and not pixmap.isNull():
            self._show_image(self._canvas.toolTip())

    def _open_directory(self) -> None:
        recorder = self._recorder
        if recorder is None or recorder.directory is None:
            return
        import subprocess
        import sys

        directory = str(recorder.directory)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", directory])
            else:
                subprocess.Popen(["xdg-open", directory])
        except OSError:
            self._caption.setText(f"打不开目录，手动去: {directory}")

    def _clear(self) -> None:
        if self._recorder is not None:
            self._recorder.clear()
        self._shown = -1
        self.refresh(force=True)


def _cells(record: MatchRecord) -> tuple[str, ...]:
    score = "—" if record.score is None else f"{record.score:.3f}"
    point = "—" if record.point is None else f"{record.point[0]},{record.point[1]}"
    roi = "整帧" if record.searched is None else f"{record.searched[0]},{record.searched[1]} " \
        f"{record.searched[2]}x{record.searched[3]}"
    return (
        str(record.seq),
        f"{record.at % 1000:7.3f}",
        record.kind,
        record.target,
        "命中" if record.hit else "未命中",
        score,
        point,
        roi,
        Path(record.frame_path).name if record.frame_path else "—",
    )
