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

import logging

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

log = logging.getLogger(__name__)

__all__ = ["ControlsBar"]

_ALL_GAMES = "（全部游戏）"
_NO_SCRIPT = "（不选脚本 —— 只用配置文件看画面）"

#: 下拉框里标题和尺寸之间的分隔符（只用于显示，传出去之前会剥掉）
_SIZE_SUFFIX = "  @ "

#: 软件没选时坐标栏的占位文字（说清"现在按什么抓"，别让人以为坏了）
_NO_WINDOW = "（没选软件 —— 按配置文件抓）"

#: 选过、但**现在枚举不到**它时的提示。窗口标题是会变的（浏览器换标签页、
#: 最小化），这时**保留用户的选择**，但必须让人看出来"现在抓不到它" ——
#: 否则开始之后的报错会显得莫名其妙。
_MISSING_WINDOW = "（选的那个现在找不到 —— 标题变了？窗口关了？）"


class ControlsBar(QWidget):
    """顶部控制栏：三步顺序 + 动作按钮。"""

    scriptChanged = Signal(object)  # ScriptEntry | None
    nodeChanged = Signal(object)  # NodeEntry | None
    windowChanged = Signal(str)
    checkRequested = Signal()
    startRequested = Signal()
    stopRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scripts: list[ScriptEntry] = []
        self._nodes: tuple[NodeEntry, ...] = ()
        self._windows: list[str] = []
        self._runnable = False
        #: 有没有选脚本。解锁开始按钮时只看它（见 set_running 的说明）
        self._has_script = False
        #: 现在在不在跑。note_runnable 运行中不生效，靠它判断
        self._running = False
        #: 上次刷新时原来选的窗口不在列表里（只用于日志/提示）
        self._previous_missing = False
        self._hints: dict[str, str] = {}

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
        # **必须吃掉 ``clicked`` 带的那个 ``checked`` 参数**（`lambda` 里那两个
        # 下划线就是干这个的）。
        #
        # 原来直接接 ``self.refresh_windows``：``QPushButton.clicked`` 会传一个
        # ``checked=False``，而 ``refresh_windows(self, keyword="")`` 正好有第二个
        # 位置参数 —— 于是那个 ``False`` 被当成**窗口标题过滤关键字**，
        # ``_list_windows(False)`` 过滤出零个窗口，**下拉框被清空**。
        #
        # 表现："点了重新检测，列表空了、再点也没反应。" 没有任何报错。
        self.detect.clicked.connect(lambda *_: self.refresh_windows())

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
        self.check_btn.clicked.connect(self.checkRequested.emit)

        self.start_btn = QPushButton("▶ 开始", self)
        self.start_btn.clicked.connect(self.startRequested.emit)
        self.stop_btn = QPushButton("■ 停止", self)
        self.stop_btn.clicked.connect(self.stopRequested.emit)
        self.stop_btn.setEnabled(False)

        self._build_layout()
        # 静态按钮的 tooltip 统一在这里设：留在各自的构造点上会和
        # ``set_shortcut_hints`` 的刷新顺序打架（谁会赢取决于调用时机）。
        self._refresh_tips()
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
        actions.addWidget(self.check_btn)
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

    def refresh_windows(self, keyword: str = "", /, *noise: object) -> list[str]:
        """枚举可见软件窗口填进下拉框。返回标题列表（枚举不了时返回空）。

        ``WindowInfo.region`` **已经是客户区坐标**（后端用 ``GetClientRect`` +
        ``ClientToScreen`` 算的），所以这里拿到的不只是"窗口有多大"，
        而是"它在屏幕上的哪一块" —— 那正是后面所有坐标换算的原点。

        ``keyword`` 是给"按标题过滤"用的（现在没有界面入口，留给以后加搜索框）。

        ## 两个防噪声的写法，都是踩出来的

        * ``/`` 把它变成**位置限定参数**：调用方写不了 ``refresh_windows(keyword=x)``，
          于是"有人把这个方法接到信号上"时不会静默变成关键字调用；
        * ``*noise`` **吞掉多余的实参**。Qt 的信号经常带参数
          （``clicked(bool)`` / ``triggered(bool)``），接错一次就可能把一个
          ``False`` 当成过滤关键字。

          实测踩到：``self.detect.clicked.connect(self.refresh_windows)`` ——
          ``clicked`` 传 ``checked=False``，正好落进这个 ``keyword``，
          ``_list_windows(False)`` 过滤出**零个窗口**，下拉框被清空。
          表现是"点了重新检测，列表空了、再点也没反应"，而且**没有任何报错**。

        **填完不自动选中第一项**：``QComboBox.addItems`` 自己会选中第 0 项，
        所以这里**显式撤掉**（``setCurrentIndex(-1)``）。理由：静默选中第一个
        窗口，和你"没选软件就按配置抓"的意图是矛盾的，而且下游会把这次选中
        当成"用户选了它"。宁可留空、让用户点一下。

        ## 原来选中的那个窗口已经不在了怎么办

        下拉框是**可编辑**的（能手打标题），而窗口标题是**会变**的 ——
        浏览器/编辑器换个标签页、最小化，标题就不是原来那个了。
        所以"刷新之后原来的选项不见了"是**常态**，不是异常。

        **曾经的错做法**：把它清空。结果是用户明明选好了、点一下刷新就被抹掉，
        还得重选一遍（实测被抱怨过"点了重新检测，选择就没了"）。

        **现在**：保留用户的选择（不清），但把"现在找不到它"**显示在坐标栏里**
        —— 那是这个控件本来就用来报告"这个窗口现在是什么状态"的地方。
        真正的把关留在「开始」那一刻（:meth:`MainWindow._target_window_ok`），
        那时才有必要拦住。
        """
        if not isinstance(keyword, str):
            # 传进来的不是标题（多半是某个信号的 bool）—— 明确忽略并留证据，
            # 而不是拿它去过滤出一个空列表
            log.warning("refresh_windows 收到非字符串的 keyword=%r，已忽略", keyword)
            keyword = ""

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            infos = _list_windows(keyword)
        finally:
            QGuiApplication.restoreOverrideCursor()

        titles = [f"{info.title}{_SIZE_SUFFIX}{info.region.w}x{info.region.h}" for info in infos]
        self._windows = titles
        previous = self.window.currentText()
        self.window.blockSignals(True)
        self.window.clear()
        self.window.addItems(titles)
        self.window.setCurrentIndex(-1)  # Qt 会在 addItems 时自动选中第一项，撤掉
        if previous:
            # **无论如何都保留用户的选择**（见上面那段说明）：在列表里就选中它，
            # 不在列表里就把它作为"当前文本"留住 —— 可编辑下拉框允许这样。
            # 曾经写成"不在就清空"，结果是"点一下刷新，选好的窗口就没了"。
            self.window.setCurrentText(previous)
        self.window.blockSignals(False)

        self._previous_missing = bool(previous) and previous not in titles
        if self._previous_missing:
            log.info("原来选中的窗口 %r 现在不在枚举结果里（标题变了或最小化了）", previous)
        self.detect.setToolTip(self._detect_tip())
        self._refresh_coords()
        return titles

    def _refresh_coords(self) -> None:
        """把当前选中窗口的客户区坐标显示出来。

        显示的是 ``x=… y=… w=… h=…``，也就是 ``Frame`` 收的**源坐标**原点的来源。
        没选或枚举不到时说明"现在按配置抓"，而不是显示一个猜的值。

        **选过、但现在找不到它**时要说清这一点 —— 窗口标题是会变的
        （浏览器换个标签页、窗口最小化），这时选择保留着（不让用户白选一次），
        但必须让人看出来"现在抓不到它"，否则开始之后的报错会显得莫名其妙。
        """
        info = self.current_window_info
        if info is None:
            if self.window_title:
                self.coords.setText(_MISSING_WINDOW)
                return
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
    def set_shortcut_hints(self, hints: dict[str, str]) -> None:
        """登记"哪个动作的键位提示是什么"，由 :meth:`_tip` 拼到 tooltip 上。

        **不能改成"启动时往 tooltip 后面追加一次"** —— 那几个按钮的 tooltip
        是动态的（``set_runnable`` 每换一次脚本就重设一次），追加的那份会被
        下一次重设冲掉，表现就是"键位提示时有时无"。所以提示统一在
        :meth:`_tip` 里拼，谁设 tooltip 都绕不过它。

        登记完要 :meth:`_refresh_tips` 一次：静态按钮的 tooltip 是在
        ``__init__`` 里设的，那时这张表还是空的 —— 不重设就永远缺个键位提示。
        """
        self._hints = dict(hints)
        self._refresh_tips()

    def _refresh_tips(self) -> None:
        """按当前的键位表重设静态按钮的 tooltip（动态那几个各管各的）。

        **「检查」那条的说明写在这里，不写在构造点上** —— 这里才是唯一生效的
        地方（构造点上设会被 `_refresh_tips` 覆盖，实测踩到：写了一大段说明，
        鼠标悬停显示的却是旧的一行）。和"键位提示会被动态重设冲掉"是同一类坑。
        """
        self.detect.setToolTip(self._detect_tip())
        self.check_btn.setToolTip(
            self._tip(
                "check",
                "检查**这份定义本身**和**它要用的模板图在不在**：\n"
                "  · 定义自洽 —— 每个记录信息的状态都有流程节点认领、父节点是分类节点、\n"
                "    边两头的节点存在、子页面 ROI 没伸出父页面\n"
                "  · 模板文件齐不齐 —— 定义里引用到的每张图去模板根里找一遍\n"
                "  · 模板根都有哪些、在不在（找不到图时最常怀疑这里）\n"
                "不查识别准不准 —— 那是跑起来看「识图日志」的事。\n"
                "选完脚本会自动查一次，这个按钮用来手动重查。",
            )
        )

    def _detect_tip(self) -> str:
        found = len(self._windows)
        text = f"重新枚举软件窗口（找到 {found} 个）" if found else "重新枚举当前可见的软件窗口"
        return self._tip("detect", text)

    def _tip(self, key: str, text: str) -> str:
        hint = self._hints.get(key, "")
        return f"{text} {hint}".strip() if text else hint

    def set_runnable(self, ok: bool, reason: str = "") -> None:
        self.start_btn.setEnabled(ok)
        self.start_btn.setToolTip(self._tip("start", reason or "开始运行"))

    def set_stoppable(self, ok: bool) -> None:
        self.stop_btn.setEnabled(ok)
        self.stop_btn.setToolTip(
            self._tip("stop", "请求停止（毫秒级响应）" if ok else "还没在跑")
        )

    def set_running(self, running: bool) -> None:
        """运行中：锁住选择、把开始换成灰的、把停止点亮。

        锁住选择是必须的：跑到一半换脚本 = 引擎还在按旧场景跑，
        而界面上显示的是新脚本的信息，两边对不上。

        ## 解锁时"能不能开始"**不再**依赖 ``_runnable``（踩过的坑）

        原来最后一行是 ``start_btn.setEnabled(not running and self._runnable)``，
        而 ``_runnable`` 在开跑那一刻被置为 ``False``（防止运行中再点开始）。
        于是解锁时它还是 ``False``，**开始按钮永远点不亮** —— 除非调用方
        记得先 ``note_runnable(True)`` 再调这个方法。

        调用方**没记得**（``_on_engine_finished`` 里那两行正好写反了顺序），
        表现就是"停止之后不能重新开始"。这类"顺序敏感 + 静默错"的接口
        不该存在，所以现在解锁只看**有没有选脚本**（``_has_script``）：
        这个状态和"在不在跑"完全正交，先调后调都一样。
        """
        for widget in (self.game, self.script, self.node, self.window, self.detect):
            widget.setEnabled(not running)
        self.check_btn.setEnabled(not running)
        if running:
            self.start_btn.setEnabled(False)
        else:
            # 解锁：只取决于"有没有选脚本"，不取决于上一次运行留下的记忆
            self.start_btn.setEnabled(self._has_script)
            self.start_btn.setToolTip(
                self._tip("start", "开始运行（会操作游戏）" if self._has_script else "先选一个脚本")
            )
        self.stop_btn.setEnabled(running)
        self._running = running

    def note_script_selected(self, ok: bool) -> None:
        """记住"有没有选脚本"。解锁时用它恢复开始按钮（见 :meth:`set_running`）。"""
        self._has_script = ok

    def note_runnable(self, ok: bool) -> None:
        """记住"现在能不能跑"（比如"先选软件"）。

        和 :meth:`note_script_selected` 的分工：

        * ``_has_script`` —— **有没有选脚本**。稳定的前提，解锁时只看它；
        * ``_runnable`` —— **当前能不能开跑**。换脚本那条路会重设它。

        **运行中不生效**：开跑时 ``_runnable`` 被置 False 只是"不许再点开始"，
        不该写进这个记忆里（否则解锁时就没有正确的值可恢复 —— 那正是
        "停止后不能重新开始"那个 bug 的来源）。
        """
        self._runnable = ok
        if not self._running:
            self.set_runnable(ok, "" if ok else "先选一个脚本")

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
