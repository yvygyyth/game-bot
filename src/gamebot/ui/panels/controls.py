"""顶栏：选游戏 / 选脚本 / 选起始节点 / 选窗口 + 动作按钮。

## 三个下拉框是联动的

换游戏 -> 刷新脚本列表 -> 换脚本 -> 刷新起始节点列表（从流程图的节点里取）。
联动逻辑放在这里而不是主窗口，因为它是"这一栏自己的事"。

## 未实现的按钮是**置灰 + 写明原因**，不是"点了没反应"

点了没反应会让人怀疑自己操作错了 —— 那是比"功能没做"更糟的体验。
所以「开始」在阶段 2 之前一直是灰的，鼠标悬停能看到
"需要 FlowEngine.tick()，尚未实现"。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..registry import NodeEntry, ScriptEntry

__all__ = ["ControlsBar"]

_ALL_GAMES = "（全部游戏）"
_NO_SCRIPT = "（不选脚本 —— 只用配置文件看画面）"

#: 下拉框里标题和尺寸之间的分隔符（只用于显示，传出去之前会剥掉）
_SIZE_SUFFIX = "  @ "


class ControlsBar(QWidget):
    """顶部控制栏。"""

    scriptChanged = Signal(object)  # ScriptEntry | None
    nodeChanged = Signal(object)  # NodeEntry | None
    windowChanged = Signal(str)
    checkRequested = Signal()
    selftestRequested = Signal()
    startRequested = Signal()
    stopRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scripts: list[ScriptEntry] = []
        self._nodes: tuple[NodeEntry, ...] = ()
        self._windows: list[str] = []

        # ---- 第一行：选什么 ----
        self.game = QComboBox(self)
        self.game.setMinimumWidth(150)
        self.game.currentIndexChanged.connect(self._on_game_changed)

        self.script = QComboBox(self)
        self.script.setMinimumWidth(260)
        self.script.currentIndexChanged.connect(self._on_script_changed)

        self.node = QComboBox(self)
        self.node.setMinimumWidth(240)
        self.node.setToolTip("从哪个节点开始跑（阶段 2 生效）")
        self.node.currentIndexChanged.connect(self._on_node_changed)

        # ---- 第二行：对着谁跑 + 动作 ----
        self.window = QComboBox(self)
        self.window.setMinimumWidth(280)
        self.window.setEditable(True)
        self.window.setToolTip(
            "要操作的窗口。列表来自当前可见窗口，也可以手打标题关键字。"
        )
        self.window.currentTextChanged.connect(self.windowChanged.emit)

        self.detect = QPushButton("重新检测", self)
        self.detect.setToolTip("重新枚举可见窗口")
        self.detect.clicked.connect(self.refresh_windows)

        self.check_btn = QPushButton("检查", self)
        self.check_btn.setToolTip("校验这份定义：页面 id、边的端点、模板文件是否齐全")
        self.check_btn.clicked.connect(self.checkRequested.emit)

        self.selftest_btn = QPushButton("自检", self)
        self.selftest_btn.setToolTip("跑脚本自带的自检（检查定义本身对不对）")
        self.selftest_btn.clicked.connect(self.selftestRequested.emit)

        self.start_btn = QPushButton("▶ 开始", self)
        self.start_btn.clicked.connect(self.startRequested.emit)
        self.stop_btn = QPushButton("■ 停止", self)
        self.stop_btn.clicked.connect(self.stopRequested.emit)
        self.stop_btn.setEnabled(False)

        self._build_layout()
        self.set_runnable(False, "需要 FlowEngine.tick()，尚未实现")
        self.set_stoppable(False)

    # ------------------------------------------------------------------ #
    # 布局
    # ------------------------------------------------------------------ #
    def _build_layout(self) -> None:
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("游戏", self))
        row1.addWidget(self.game)
        row1.addSpacing(8)
        row1.addWidget(QLabel("脚本", self))
        row1.addWidget(self.script, 1)
        row1.addSpacing(8)
        row1.addWidget(QLabel("起始节点", self))
        row1.addWidget(self.node, 1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("窗口", self))
        row2.addWidget(self.window, 1)
        row2.addWidget(self.detect)
        row2.addSpacing(12)
        row2.addWidget(self._separator())
        row2.addSpacing(12)
        row2.addWidget(self.check_btn)
        row2.addWidget(self.selftest_btn)
        row2.addSpacing(12)
        row2.addWidget(self._separator())
        row2.addSpacing(12)
        row2.addWidget(self.start_btn)
        row2.addWidget(self.stop_btn)

        box = QGroupBox("控制", self)
        inner = QVBoxLayout(box)
        inner.addLayout(row1)
        inner.addLayout(row2)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    # ------------------------------------------------------------------ #
    # 数据填充
    # ------------------------------------------------------------------ #
    def set_scripts(self, scripts: list[ScriptEntry], *, note: str = "") -> None:
        """填脚本列表。``note`` 非空时显示在游戏下拉框的提示里。"""
        self._scripts = scripts
        self.game.blockSignals(True)
        self.game.clear()
        self.game.addItem(_ALL_GAMES)
        for name in sorted({s.game for s in scripts}):
            self.game.addItem(name)
        self.game.blockSignals(False)
        if note:
            self.game.setToolTip(note)
        self._refill_scripts()

    def select_script(self, key: str) -> bool:
        """按 key 预选脚本。找不到返回 False。

        ``key`` 是 ``"none"`` / ``"-"`` / 空串时选"不选脚本"那一项 ——
        命令行 ``gamebot ui --script none`` 就是只看画面。
        """
        if key.strip().lower() in ("", "none", "-"):
            self.script.setCurrentIndex(0)
            return True
        for index in range(self.script.count()):
            entry = self.script.itemData(index)
            if entry is not None and entry.key == key:
                self.script.setCurrentIndex(index)
                return True
        return False

    def set_nodes(self, nodes: tuple[NodeEntry, ...], *, enabled: bool = True) -> None:
        """填起始节点列表。"""
        self._nodes = nodes
        self.node.blockSignals(True)
        self.node.clear()
        for entry in nodes:
            self.node.addItem(entry.label, entry)
        self.node.blockSignals(False)
        self.node.setEnabled(enabled and bool(nodes))
        if not enabled:
            self.node.setToolTip("需要 FlowEngine 支持起始节点，尚未实现")
        self._on_node_changed()

    def refresh_windows(self, keyword: str = "") -> list[str]:
        """枚举可见窗口填进下拉框。返回标题列表（枚举不了时返回空）。"""
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            titles = _list_window_titles(keyword)
        finally:
            QGuiApplication.restoreOverrideCursor()

        self._windows = titles
        current = self.window.currentText()
        self.window.blockSignals(True)
        self.window.clear()
        self.window.addItems(titles)
        self.window.blockSignals(False)
        if current:
            self.window.setCurrentText(current)
        self.detect.setToolTip(
            f"重新枚举可见窗口（找到 {len(titles)} 个）" if titles else "没有找到可见窗口"
        )
        return titles

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #
    def set_runnable(self, ok: bool, reason: str = "") -> None:
        self.start_btn.setEnabled(ok)
        self.start_btn.setToolTip(reason or "开始运行")

    def set_stoppable(self, ok: bool) -> None:
        self.stop_btn.setEnabled(ok)
        self.stop_btn.setToolTip("请求停止（毫秒级响应）" if ok else "还没在跑")

    def set_running(self, running: bool) -> None:
        """运行中：锁住选择、把开始换成灰的、把停止点亮。"""
        for widget in (self.game, self.script, self.node, self.window, self.detect):
            widget.setEnabled(not running)
        self.check_btn.setEnabled(not running)
        self.selftest_btn.setEnabled(not running)
        self.start_btn.setEnabled(not running and self.start_btn.isEnabled())
        self.stop_btn.setEnabled(running)

    @property
    def current_script(self) -> ScriptEntry | None:
        return self.script.currentData()

    @property
    def current_node(self) -> NodeEntry | None:
        return self.node.currentData()

    @property
    def window_title(self) -> str:
        """当前窗口**标题本身**（不含下拉框里为了好看加的尺寸后缀）。

        下拉框显示成 ``标题  @ 1280x820``，但传给 ``find_window`` 的必须只有
        标题 —— 带着后缀去匹配永远找不到窗口。用户手打的标题没有后缀，
        所以这里按后缀切一刀就够了，不做别的猜测。
        """
        return _clean_title(self.window.currentText())

    # ------------------------------------------------------------------ #
    # 联动
    # ------------------------------------------------------------------ #
    def _on_game_changed(self) -> None:
        self._refill_scripts()

    def _refill_scripts(self) -> None:
        game = self.game.currentText()
        entries = [s for s in self._scripts if game in (_ALL_GAMES, "") or s.game == game]
        self.script.blockSignals(True)
        self.script.clear()
        # 第一项是"不选脚本"：这时预览用配置文件（config/app.yaml）里的设置，
        # 于是可以"先确认能看到窗口、能截到图"，再去写脚本。
        self.script.addItem(_NO_SCRIPT, None)
        for entry in entries:
            self.script.addItem(entry.label, entry)
        # setCurrentIndex 必须在阻塞期间调 —— 放到 unblock 之后会多 emit 一次
        # currentIndexChanged，于是抓屏会话白建一遍（先建后立刻被替换）。
        self.script.setCurrentIndex(1 if entries else 0)
        self.script.blockSignals(False)
        self._on_script_changed()

    def _on_script_changed(self) -> None:
        self.scriptChanged.emit(self.current_script)

    def _on_node_changed(self) -> None:
        self.nodeChanged.emit(self.current_node)


def _clean_title(text: str) -> str:
    """剥掉下拉框里显示用的 ``  @ WxH`` 后缀。"""
    return text.split(_SIZE_SUFFIX)[0].strip()


def _list_window_titles(keyword: str = "") -> list[str]:
    """枚举可见窗口标题。失败时返回空列表 —— 界面不该因为枚举不到就崩。

    后端依赖平台：Windows 用 pywin32，其它平台会抛 ``BackendUnavailable``，
    这里一律吞掉并返回空。
    """
    try:
        from ...atomic.backends.windows import WindowsWindowBackend

        backend = WindowsWindowBackend()
        windows = backend.list_windows(keyword)
    except Exception:
        return []
    return [f"{w.title}{_SIZE_SUFFIX}{w.region.w}x{w.region.h}" for w in windows]
