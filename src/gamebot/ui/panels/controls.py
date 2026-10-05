"""顶栏：**先选软件、再选游戏、再选脚本** + 动作按钮。

## 三步顺序不是排版好看，是依赖顺序

```
① 选软件   -> 这一步就把"软件坐标"定下来了（客户区位置 + 尺寸）
② 选游戏   -> 换游戏刷新脚本列表
③ 选脚本   -> 换脚本刷新起始节点列表（从流程图的节点里取）
```

为什么"选软件"必须排第一：**坐标是从窗口来的**。截图和点击的坐标原点都是
这个窗口的客户区左上角（``WindowInfo.region``，由 ``GetClientRect`` +
``ClientToScreen`` 算出来）。窗口没定，后面两步选什么都无法换算成屏幕坐标 ——
真正会用这一步结果的不是界面，是引擎里那个 ``offset_provider``。

所以选完之后立刻把坐标**显示出来**（``客户区 (21,49) 1918x1080``）：
看不见的东西没法确认对不对，而它错了的表现是"每次点击都偏一个窗口位置"。

## 按钮置灰要**写明原因**

点了没反应会让人怀疑自己操作错了 —— 那是比"功能没做"更糟的体验。
现在每个置灰的按钮都能在 tooltip 里看到"还缺什么"。
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

#: 软件没选时坐标栏的占位文字（说清"现在按什么抓"，别让人以为坏了）
_NO_WINDOW = "（没选软件 —— 按配置文件抓）"


class ControlsBar(QWidget):
    """顶部控制栏：三步顺序 + 动作按钮。"""

    scriptChanged = Signal(object)  # ScriptEntry | None
    nodeChanged = Signal(object)  # NodeEntry | None
    windowChanged = Signal(str)
    checkRequested = Signal()
    selftestRequested = Signal()
    startRequested = Signal()
    stopRequested = Signal()
    grabRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scripts: list[ScriptEntry] = []
        self._nodes: tuple[NodeEntry, ...] = ()
        self._windows: list[str] = []
        self._runnable = False

        # ---- 第一步：选软件（这一步就把坐标定下来） ----
        self.window = QComboBox(self)
        self.window.setMinimumWidth(300)
        self.window.setEditable(True)
        self.window.setToolTip(
            "要操作的软件窗口。列表来自当前可见窗口（客户区坐标一并列出来），"
            "也可以手打标题关键字。"
        )
        self.window.currentTextChanged.connect(self._on_window_changed)

        self.detect = QPushButton("重新检测", self)
        self.detect.setToolTip("重新枚举当前可见的软件窗口")
        self.detect.clicked.connect(self.refresh_windows)

        self.coords = QLabel(_NO_WINDOW, self)
        self.coords.setStyleSheet("color:#8ab4f8; font-family:Consolas,monospace;")
        self.coords.setToolTip(
            "选定窗口的客户区在屏幕上的位置与尺寸 —— 截图和点击都以它为原点。\n"
            "游戏改分辨率 / 挪动窗口后，这里会跟着变。"
        )

        # ---- 第二步：选游戏 ----
        self.game = QComboBox(self)
        self.game.setMinimumWidth(150)
        self.game.currentIndexChanged.connect(self._on_game_changed)

        # ---- 第三步：选脚本 + 起始节点 ----
        self.script = QComboBox(self)
        self.script.setMinimumWidth(260)
        self.script.currentIndexChanged.connect(self._on_script_changed)

        self.node = QComboBox(self)
        self.node.setMinimumWidth(240)
        self.node.setToolTip("从哪个节点开始跑（不解除状态校验）")
        self.node.currentIndexChanged.connect(self._on_node_changed)

        # ---- 动作 ----
        self.check_btn = QPushButton("检查", self)
        self.check_btn.setToolTip("校验这份定义：状态 id、边的端点、模板文件是否齐全")
        self.check_btn.clicked.connect(self.checkRequested.emit)

        self.selftest_btn = QPushButton("自检", self)
        self.selftest_btn.setToolTip("跑脚本自带的自检（检查定义本身对不对）")
        self.selftest_btn.clicked.connect(self.selftestRequested.emit)

        self.grab_btn = QPushButton("抓一张", self)
        self.grab_btn.setToolTip(
            "截一帧，按当前脚本把每个状态的查询跑一遍，并把命中的区域用红框画出来存下。\n"
            "跑脚本之前用它确认「它到底认的是哪一块」—— 这是调 ROI 和阈值最快的办法。"
        )
        self.grab_btn.clicked.connect(self.grabRequested.emit)

        self.start_btn = QPushButton("▶ 开始", self)
        self.start_btn.clicked.connect(self.startRequested.emit)
        self.stop_btn = QPushButton("■ 停止", self)
        self.stop_btn.clicked.connect(self.stopRequested.emit)
        self.stop_btn.setEnabled(False)

        self._build_layout()
        self.set_runnable(False, "先选软件，再选脚本")
        self.set_stoppable(False)

    # ------------------------------------------------------------------ #
    # 布局：一行一步，顺序就是依赖顺序
    # ------------------------------------------------------------------ #
    def _build_layout(self) -> None:
        step1 = QHBoxLayout()
        step1.addWidget(QLabel("① 软件", self))
        step1.addWidget(self.window, 1)
        step1.addWidget(self.detect)
        step1.addSpacing(6)
        step1.addWidget(self.coords)

        step2 = QHBoxLayout()
        step2.addWidget(QLabel("② 游戏", self))
        step2.addWidget(self.game)
        step2.addSpacing(12)
        step2.addWidget(QLabel("③ 脚本", self))
        step2.addWidget(self.script, 1)
        step2.addSpacing(6)
        step2.addWidget(QLabel("起始节点", self))
        step2.addWidget(self.node, 1)

        actions = QHBoxLayout()
        actions.addWidget(self.grab_btn)
        actions.addWidget(self.check_btn)
        actions.addWidget(self.selftest_btn)
        actions.addStretch(1)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.stop_btn)

        box = QGroupBox("控制", self)
        inner = QVBoxLayout(box)
        inner.addLayout(step1)
        inner.addLayout(step2)
        inner.addWidget(self._separator())
        inner.addLayout(actions)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
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
            self.node.setToolTip("从哪个节点开始跑（FlowEngine(start_node=...) 已支持）")
        self._on_node_changed()

    def refresh_windows(self, keyword: str = "") -> list[str]:
        """枚举可见软件窗口填进下拉框。返回标题列表（枚举不了时返回空）。

        ``WindowInfo.region`` **已经是客户区坐标**（后端用 ``GetClientRect`` +
        ``ClientToScreen`` 算的），所以这里拿到的不只是"窗口有多大"，
        而是"它在屏幕上的哪一块" —— 那正是后面所有坐标换算的原点。

        **填完不自动选中第一项**：自动选中会被下游当成"用户选了它"，
        于是预览立刻切去抓那个窗口 —— 而你刚要看的可能恰恰是整屏。
        留空，等用户真的点一下。
        """
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            infos = _list_windows(keyword)
        finally:
            QGuiApplication.restoreOverrideCursor()

        titles = [f"{info.title}{_SIZE_SUFFIX}{info.region.w}x{info.region.h}" for info in infos]
        self._windows = titles
        current = self.window.currentText()
        self.window.blockSignals(True)
        self.window.clear()
        self.window.addItems(titles)
        self.window.blockSignals(False)
        if current:
            self.window.setCurrentText(current)
        self.detect.setToolTip(
            f"重新枚举软件窗口（找到 {len(titles)} 个）" if titles else "没有找到可见窗口"
        )
        self._refresh_coords()
        return titles

    def _refresh_coords(self) -> None:
        """把当前选中窗口的客户区坐标显示出来。

        显示的是 ``x=… y=… w=… h=…``，也就是 ``Frame`` 收的**源坐标**原点的来源。
        没选或枚举不到时说明"现在按配置抓"，而不是显示一个猜的值。
        """
        info = self.current_window_info
        if info is None:
            self.coords.setText(_NO_WINDOW)
            return
        region = info.region
        self.coords.setText(f"客户区 x={region.x} y={region.y}  {region.w}x{region.h}")

    @property
    def current_window_info(self):
        """当前选中窗口的 ``WindowInfo``（拿不到返回 None）。

        自己**重新枚举一次**而不是缓存：窗口会被挪动、会被改尺寸，
        缓存下来的坐标会悄悄变旧 —— 而这个值错了的表现是"点击每次都偏"。
        枚举一次只要几毫秒，不值得为它冒这个险。
        """
        title = self.window_title
        if not title:
            return None
        for info in _list_windows():
            if info.title == title:
                return info
        return None

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
        """运行中：锁住选择、把开始换成灰的、把停止点亮。

        锁住选择是必须的：跑到一半换脚本 = 引擎还在按旧场景跑，
        而界面上显示的是新脚本的信息，两边对不上。
        """
        for widget in (self.game, self.script, self.node, self.window, self.detect):
            widget.setEnabled(not running)
        self.check_btn.setEnabled(not running)
        self.selftest_btn.setEnabled(not running)
        self.start_btn.setEnabled(not running and self._runnable)
        self.stop_btn.setEnabled(running)

    def note_runnable(self, ok: bool) -> None:
        """记住"能不能跑"，供 :meth:`set_running` 恢复用（别把灰按钮点亮）。"""
        self._runnable = ok

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
    def _on_window_changed(self, _text: str) -> None:
        self._refresh_coords()
        self.windowChanged.emit(self.window_title)

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


def _list_windows(keyword: str = ""):
    """枚举可见窗口，返回 ``WindowInfo`` 列表。失败时返回空列表。

    界面不该因为枚举不到就崩 —— 后端依赖平台（Windows 用 pywin32，
    其它平台抛 ``BackendUnavailable``），这里一律吞掉。
    """
    try:
        from ...atomic.backends.windows import WindowsWindowBackend

        return WindowsWindowBackend().list_windows(keyword)
    except Exception:
        return []
