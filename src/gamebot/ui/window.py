"""主窗口：把三块（控制栏 / 画面+信息 / 日志）拼起来并接线。

## 线程

窗口是界面线程唯一的"大老板"。它持有：

* 一个 :class:`LogBridge` —— 日志过来（可能来自工作线程的 emit）；
* 一个 ``QThread`` + :class:`EngineWorker` —— 引擎那个阻塞循环在那里跑。

**没有抓帧线程了**：界面上的实时画面已经删掉（看不出问题），
"它认到的是哪一块"由识图日志回答。

两条规矩（见 ``docs/ui.md`` 第四节）：

1. 跨线程只传**值**（``QImage`` / ``str`` / dataclass），绝不传控件；
2. 关窗时先让工作线程收摊（``shutdown`` -> ``quit`` -> ``wait``），
   再摘日志 handler。顺序反了会留下后台线程或悬空引用。
"""

from __future__ import annotations

import contextlib
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..utils.logging import get_logger
from .engine import EngineWorker
from .logbridge import LogBridge
from .panels.controls import ControlsBar
from .panels.diagram import DiagramPanel
from .panels.info import InfoPanel
from .panels.logview import LogView
from .panels.params import ParamsPanel
from .panels.recognition import RecognitionPanel
from .registry import ScriptDetails, ScriptEntry, load_details, load_scripts
from .shortcuts import SHORTCUTS, Keymap
from .theme import monospace

log = get_logger("ui.window")

__all__ = ["MainWindow"]

_WINDOW_TITLE = "gamebot 控制台"


class MainWindow(QMainWindow):
    """本地控制台。"""

    def __init__(
        self,
        *,
        initial_script: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry: ScriptEntry | None = None
        self._details: ScriptDetails | None = None
        self._engine_running = False
        self._run_ctx: Any = None
        self._run_journal: Any = None
        self._recorder: Any = None
        self._last_report: Any = None
        """最近一次运行的 ``RunReport``。报告本身也写进日志和「检查输出」页，
        这里留一份是给外部（测试、以后的状态栏）读的。"""

        self.setWindowTitle(_WINDOW_TITLE)

        # ---- 日志桥（界面线程唯一持有者）----
        self.bridge = LogBridge(maxlen=2000)
        self.bridge.attach()

        # ---- 面板 ----
        self.controls = ControlsBar(self)
        self.diagram = DiagramPanel(self)
        self.recognition = RecognitionPanel(self)
        self.workspace = self._make_workspace()
        self.params = ParamsPanel(self)
        self.info = InfoPanel(self)
        self.logview = LogView(self.bridge, self)

        self._status = QLabel("就绪", self)
        self._status.setStyleSheet("color:#7f8c8d; padding:2px 6px;")

        self._build_layout()
        self._wire()
        self._start_engine_thread()

        # ---- 首次填充 ----
        # 先枚举窗口、再选脚本：用户的操作顺序是"先选软件、再选游戏、再选脚本"，
        # 界面初始化也照这个顺序，否则第一眼看到的是个空下拉框。
        self.controls.refresh_windows()
        self._load_scripts(initial_script)
        log.info("界面已启动")
        self._warn_about_unimplemented()

    # ------------------------------------------------------------------ #
    # 布局
    # ------------------------------------------------------------------ #
    def _build_layout(self) -> None:
        """上面是"看它怎么想"的标签页，下面是日志大框。

        **没有实时画面了**（用户反馈：实时画面看不出问题）。取而代之的是
        「状态 / 流程」「识图日志」「检查输出」三页 —— 它们回答的是
        "它认到的是哪一块、为什么这么走"，而不是"屏幕现在长什么样"。
        """
        upper = QSplitter(Qt.Orientation.Horizontal, self)
        upper.addWidget(self.workspace)

        # 右栏是**竖着叠的两个面板**（运行参数在上、运行状态在下），整栏当作
        # 横 splitter 的**第二块**。
        #
        # 别把它们直接 addWidget 到这个横 splitter 上：那样是**三块**，而
        # setSizes 只给两个值的话第三块会被压成 0 宽、直接看不见 ——
        # 「运行状态」就这么消失过一次（没有任何报错）。
        side = QSplitter(Qt.Orientation.Vertical, self)
        side.addWidget(self.params)
        side.addWidget(self.info)
        side.setStretchFactor(0, 0)  # 参数块按内容高度，别抢
        side.setStretchFactor(1, 1)  # 多出来的高度都给运行状态
        side.setSizes([260, 520])
        upper.addWidget(side)

        upper.setStretchFactor(0, 3)
        upper.setStretchFactor(1, 2)
        upper.setSizes([760, 430])

        lower = QWidget(self)
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(6, 0, 6, 6)
        lower_layout.addWidget(self.logview)

        vertical = QSplitter(Qt.Orientation.Vertical, self)
        vertical.addWidget(upper)
        vertical.addWidget(lower)
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 2)
        vertical.setSizes([470, 330])

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 0)
        layout.addWidget(self.controls)
        layout.addWidget(self._banner())
        layout.addWidget(vertical, 1)
        layout.addWidget(self._status)
        self.setCentralWidget(central)

    def _make_workspace(self) -> QTabWidget:
        """左上那三页：状态/流程图・识图日志・检查输出。"""
        tabs = QTabWidget(self)
        tabs.addTab(self.diagram, "状态 / 流程")
        tabs.addTab(self.recognition, "识图日志")
        self._check_page = self._check_output_view()
        tabs.addTab(self._check_page, "检查输出")
        tabs.setCurrentIndex(0)
        return tabs

    def _check_output_view(self) -> QWidget:
        """「检查输出」页：把 InfoPanel 的检查结果也在这边放一份大图看。"""
        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(6, 6, 6, 6)
        self._check_view = QPlainTextEdit(holder)
        self._check_view.setReadOnly(True)
        self._check_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        monospace(self._check_view)
        layout.addWidget(self._check_view, 1)
        return holder

    def _banner(self) -> QLabel:
        """一条常驻提示：把"怎么用、现在是什么模式"说在前面。"""
        label = QLabel(
            "① 选软件（右边会显示客户区坐标）→ ② 选游戏 → ③ 选脚本 → 「▶ 开始」。"
            "跑起来后左边看「状态 / 流程」哪一格亮了、「识图日志」里它认到了哪一块"
            "（红框 = 命中，橙框 = 没中，蓝框 = 搜索范围）。",
            self,
        )
        label.setWordWrap(True)
        label.setStyleSheet(
            "background:#2b2f18; color:#e5c07b; border:1px solid #4a4a2a;"
            "border-radius:3px; padding:4px 8px;"
        )
        return label

    def _start_engine_thread(self) -> None:
        """引擎线程：只跑 ``FlowEngine.run()`` 那一个阻塞循环。

        两条连接各有理由：

        * ``run`` 走**队列连接**，由 ``_engineTickRelay`` 触发 —— 这就是"把阻塞
          循环甩到工作线程"的那一步。**这个方向是对的**：发信号时引擎线程还空着
          （事件循环在转），所以事件能立刻被投递；
        * **停止不走信号**（这条以前写错过）：反方向发信号意味着"要等引擎线程回到
          事件循环"，而它正卡在 ``run()`` 里 —— 停止请求会永远排队。所以停止是
          界面线程**直接调** ``engine.stop()``，见 :meth:`_on_stop`。
        """
        self._engine_thread = QThread(self)
        self._engine_worker = EngineWorker()
        self._engine_worker.moveToThread(self._engine_thread)
        self._engineTickRelay = _SignalRelay(self)

        self._engineTickRelay.triggered.connect(self._engine_worker.run)
        self._engine_worker.ticked.connect(self._on_tick)
        self._engine_worker.finished.connect(self._on_engine_finished)
        self._engine_worker.failed.connect(self._on_engine_failed)

        self._engine_thread.start()

    # ------------------------------------------------------------------ #
    # 接线
    # ------------------------------------------------------------------ #
    def _wire(self) -> None:
        self.controls.scriptChanged.connect(self._on_script_changed)
        self.controls.nodeChanged.connect(self._on_node_changed)
        self.controls.windowChanged.connect(self._on_window_changed)
        self.controls.checkRequested.connect(self._run_check)
        self.controls.startRequested.connect(self._on_start)
        self.controls.stopRequested.connect(self._on_stop)

        # 注意：日志信号由 LogView 在它自己的构造里接上（那块归它管）。
        # 这里**不要**再连一次 —— 连两次的话每条日志会被追加两遍。
        # 实时画面已经去掉：用户反馈"看不出问题"，能看出问题的是带框的识图记录。

        self._wire_shortcuts()

    # ------------------------------------------------------------------ #
    # 脚本
    # ------------------------------------------------------------------ #
    def _load_scripts(self, initial_script: str = "") -> None:
        entries, note = load_scripts()
        self.controls.set_scripts(entries, note=note)
        if not entries:
            msg = note or "没有发现任何脚本"
            log.warning(msg)
            self._show_check_output("脚本列表为空", [msg])
            self._status.setText("没有可用脚本")
            return
        if initial_script and not self.controls.select_script(initial_script):
            log.warning("找不到脚本 %r，保持默认选择", initial_script)
        self._status.setText(f"发现 {len(entries)} 个脚本")

    @Slot(object)
    def _on_script_changed(self, entry: ScriptEntry | None) -> None:
        self._entry = entry
        if entry is None:
            self._details = None
            self.params.set_form(None)
            self.info.set_details(None, None)
            self.diagram.set_scenario(None)
            self.recognition.set_recorder(None)
            self.controls.set_nodes(())
            self.controls.set_runnable(False, "先选一个脚本")
            return

        details = load_details(entry)
        self._details = details
        self.params.set_form(entry.spec.form if entry.spec is not None else None)
        self.info.set_details(entry, details)

        # 左边那两个图要的是 Scenario 对象（不是文字），所以在这里真的构造一次。
        # 静态构造不碰游戏窗口，出错也不影响选择 —— 出错就画空白图 + 记日志。
        scenario = None
        try:
            if entry.spec is not None:
                scenario = entry.spec.build_scenario()
        except Exception as exc:
            log.warning("构造 %s 的场景失败，图将画不出来: %s", entry.key, exc)
        self.diagram.set_scenario(scenario)

        # 识别记录器：**界面自己造一个并一直用**（换脚本才换）。
        # 理由是"开始运行"写的就是这份记录（界面只有这一条路了）——
        # 否则每次开始运行都会新建一个记录器，界面上那栏会莫名其妙清空。
        # 构造它只是建目录 + 计数器，不碰游戏窗口。
        try:
            from ..bootstrap import build_recorder

            config_for_recorder = entry.spec.build_config() if entry.spec else None
            self._recorder = (
                build_recorder(config_for_recorder) if config_for_recorder else None
            )
        except Exception as exc:
            log.warning("造识别记录器失败（识图日志将不可用）: %s", exc)
            self._recorder = None
        self.recognition.set_recorder(self._recorder)

        self.controls.set_nodes(
            details.node_list,
            enabled=bool(details.node_list),
        )
        self.controls.set_runnable(True, "开始运行（会操作游戏）")
        if details.problems:
            self._status.setText(f"{entry.key}: 定义有问题（见「检查输出」）")
            log.warning("脚本 %s 的定义有问题: %s", entry.key, details.problems)
        else:
            self._status.setText(
                f"{entry.key}: {details.pages} 状态 / {details.nodes} 节点 / "
                f"{details.edges} 边"
            )

    @Slot(object)
    def _on_window_changed(self, title: str) -> None:
        """换了软件窗口。

        界面不再自己抓屏（没有实时画面），所以这里只是记一条日志 ——
        真正用到窗口的是「开始」那一刻，它会把标题交给引擎的抓屏会话。
        """
        log.debug("目标窗口改为 %r", title)

    # ------------------------------------------------------------------ #
    # 抓屏
    # ------------------------------------------------------------------ #
    @Slot(object)
    def _on_tick(self, event: object) -> None:
        """每轮刷新：状态面板 + **把当前状态/节点在图上点亮**。"""
        self.info.set_run_state(event)
        self.diagram.refresh(
            current_page=getattr(event, "page", ""),
            current_node=getattr(event, "node", ""),
            current_node_page=getattr(event, "expected", ""),
            overlays=tuple(getattr(event, "overlays", ())),
        )

    def _on_node_changed(self, node: object) -> None:
        """换起始节点：右侧显示它的详情，左侧图上**预点亮**它。

        这样点「开始」之前就能看清"我要从哪一格起跑"，而不是跑起来才知道。
        """
        self.info.set_node(node)
        node_id = getattr(node, "node_id", "") or ""
        page = getattr(node, "page", "") or ""
        self.diagram.refresh(current_node=node_id, current_node_page=page)

    # ------------------------------------------------------------------ #
    # 检查 / 自检
    # ------------------------------------------------------------------ #
    def _run_check(self) -> None:
        entry = self._entry
        if entry is None or entry.spec is None:
            return
        from ..bootstrap import check_templates

        lines: list[str] = []
        try:
            config = entry.spec.build_config()
            scenario = entry.spec.build_scenario()
            scenario.validate()
            lines.append(
                f"✓ 定义校验通过：{len(scenario.tree)} 页面 / "
                f"{len(scenario.graph.nodes)} 节点 / {len(scenario.graph.edges)} 边"
            )
            missing = check_templates(config, scenario)
            if missing:
                lines.append(f"✗ 缺 {len(missing)} 个模板文件:")
                lines.extend(f"    - {name}" for name in missing)
            else:
                lines.append("✓ 模板文件齐全")
            for root in config.template_roots():
                exists = "存在" if root.is_dir() else "目录不存在"
                lines.append(f"  模板根: {root}（{exists}）")
        except Exception as exc:
            lines.append(f"✗ {type(exc).__name__}: {exc}")

        self._show_check_output(f"检查 {entry.key}", lines)
        for line in lines:
            log.info("[check] %s", line)

    # ------------------------------------------------------------------ #
    # 开始 / 停止
    # ------------------------------------------------------------------ #
    def _target_window_ok(self, entry: ScriptEntry) -> bool:
        """开跑前确认"要抓的那个窗口**现在**还在"。不在就当场说清楚。

        ## 为什么非要加这一步

        窗口下拉框是**枚举当时**的快照，而窗口会关、会被改名。选完之后窗口没了
        的话，原来那条路的报错是底层异常直接弹出来：

            [装不起来] BackendError: 未找到标题包含 'README.md - game-bot - Cursor' 的窗口

        用户看到的是**自己几十分钟前选过的另一个窗口的标题**，而"它不在了"
        这件事得自己从异常里推出来 —— 报错既没说"是窗口问题"，也没说怎么办。
        （实测踩过：选过 Cursor 的窗口标题，回来点开始时那个标签页已经关了。）

        所以在这里就用**人话**问清楚，并给一个「重新检测」的出口。

        :return: 能不能继续。``False`` 时调用方必须直接 return。
        """
        import contextlib

        from .panels.controls import _list_windows

        chosen = self.controls.window_title
        config_title = ""
        with contextlib.suppress(Exception):
            config_title = entry.spec.build_config().screen.window_title
        wanted = chosen or config_title
        if not wanted:
            # 既没选、配置里也没有 —— 交给后端按整屏抓，不是这里能判断的
            return True

        windows = _list_windows()
        if any(info.title == wanted for info in windows):
            return True

        if not windows:
            # 一个窗口都枚举不到：多半是后端没装或平台不对，别冒充"窗口不在"
            self._info_box(
                "枚举不到任何窗口",
                "现在一个可见窗口都列不出来 —— 这通常是后端不可用"
                "（Windows 需要 pywin32），或者跑在无头环境里。\n\n"
                "先看看日志里有没有 BackendUnavailable。",
            )
            return False

        source = "上面选的软件" if chosen else "配置文件里的 window_title"
        answer = QMessageBox.question(
            self,
            "要操作的窗口不在了",
            f"按{source}要抓的是：\n\n    {wanted}\n\n"
            "但现在枚举不到这个窗口 —— 它可能被关掉了，或者标题变了"
            "（比如编辑器换了标签页）。\n\n"
            "点「Yes」重新枚举一次窗口列表，然后你在上面重新选一个；"
            "点「No」就什么都不做。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.controls.refresh_windows()
        return False

    def _on_start(self) -> None:
        """装配 -> 交给工作线程跑。

        **装配在界面线程做完**（读配置、建 Session、校验定义、检查模板），
        原因是这些步骤失败时要能立刻弹给人看；而 ``run()`` 那个阻塞循环
        才交给工作线程。分成两半的界线就是"会不会长时间阻塞"。
        """
        entry = self._entry
        if entry is None or entry.spec is None:
            self._info_box("先选脚本", "「开始」要知道跑哪份定义。先在上面选一个脚本。")
            return
        if self._engine_running:
            return

        if not self._target_window_ok(entry):
            return

        from ..bootstrap import build_context, build_engine, check_templates

        try:
            config = entry.spec.build_config()
            config.screen.window_title = self.controls.window_title or config.screen.window_title
            scenario = entry.spec.build_scenario()
            scenario.validate()
        except Exception as exc:
            self._info_box("装不起来", f"{type(exc).__name__}: {exc}")
            log.exception("装配失败")
            return

        # 表单值在这里**读一次**（数据单向：表单是唯一的改值处）。
        # fill() 会把"用户没动过的字段"补上声明里的默认值，所以步骤那边
        # ctx.param(...) 一定拿得到值，不必再写一遍默认值 —— 默认值只有
        # FORM 一处出处，两处迟早不一致。
        #
        # 校验失败理论上不该发生（控件层已经卡住范围了）。真失败也只弹框：
        # 那说明声明和控件的行为对不上，是要修的 bug，不该静默拿个错值往下跑。
        try:
            params = entry.spec.form.fill(self.params.values())
        except Exception as exc:
            self._info_box("参数不对", f"{type(exc).__name__}: {exc}")
            log.exception("表单值校验失败")
            return
        if params:
            log.info("运行参数: %s", params)

        missing = check_templates(config, scenario)
        if missing:
            self._info_box(
                "缺模板文件",
                f"缺 {len(missing)} 个：\n  " + "\n  ".join(missing[:8])
                + "\n\n先跑「检查」看看，把图补齐再开始。",
            )
            return

        config.paths.ensure()
        node_id = getattr(self.controls.current_node, "node_id", "") or ""
        from ..execution.journal import JsonlJournal

        journal = JsonlJournal(
            config.paths.resolve(config.paths.journals) / f"{entry.slug}.jsonl"
        )
        try:
            ctx = build_context(
                config,
                scenario=scenario,
                journal=journal,
                recorder=self._recorder,
                scenario_options=scenario.options,
                params=params,
            )
            engine = build_engine(config, ctx, scenario)
        except Exception as exc:
            journal.close()
            self._info_box("装不起来", f"{type(exc).__name__}: {exc}")
            log.exception("装配失败")
            return

        self._run_ctx = ctx
        self._run_journal = journal
        self._engine_running = True
        self.controls.set_running(True)
        self.controls.note_runnable(False)
        self._status.setText(f"运行中：{entry.key}")
        self.info.set_run_state(None)

        self._engine_worker.configure(ctx, engine, node_id)
        # 名字必须和 ``_start_engine_thread`` 里创建的那个一致。
        # 曾经写成 ``_engine_tick_relay``（加下划线那种拼法），点「开始」就
        # AttributeError —— 同一个文件里两种命名风格并存时特别容易犯。
        # 所以 test_ui_run 里有一条用例真的走一遍这条路，而不是只测 _set_running。
        self._engineTickRelay.triggered.emit()
        log.info("开始运行 %s（起始节点 %s）", entry.key, node_id or scenario.graph.initial)

    def _on_stop(self) -> None:
        """请求停止。**直接在界面线程调 ``engine.stop()``**，不走队列信号。

        ## 这里踩过一个坑，别"优化"回去

        原来的写法是 ``self._engineStopRelay.triggered.emit()``，想靠队列连接把
        ``request_stop`` 排到引擎线程去执行。**那是错的，而且是致命的**：

        队列连接的槽要等**目标线程回到事件循环**才会被投递，而引擎线程正卡在
        ``engine.run()`` 那个阻塞循环里，永远回不到事件循环。于是停止请求一直
        排队、永远不执行 —— 表现就是"点了停止，脚本照跑"。

        ``engine.stop()`` 本来就只是设个标志位 + 写 ``Session`` 上的中止事件
        （``threading.Event``），**它本身就是线程安全的**，从任意线程直接调都对。
        绕一层信号不仅没好处，还把唯一能停下来的那条路堵死了。

        以后要加"重试/确认"之类的东西，在这条**直接调用**上加，别改回信号。
        """
        if not self._engine_running:
            log.info("「停止」被点了，当前没有在跑的脚本")
            return
        self.controls.stop_btn.setEnabled(False)
        self.controls.stop_btn.setToolTip("正在等引擎退出这一轮……")
        self._status.setText("正在停止……")
        self._request_engine_stop()

    def _request_engine_stop(self) -> None:
        """请求停止的**唯一入口**：按钮、Esc、关窗都走它。

        直接调而不是发信号 —— 理由见 :meth:`_on_stop` 的 docstring。
        """
        engine = self._engine_worker.engine
        if engine is None:
            return
        engine.stop()

    @Slot(object, str)
    def _on_engine_finished(self, report: object, summary: str) -> None:
        """跑完了：解锁界面、关会话、把结论写出来。"""
        self._engine_running = False
        self._last_report = report
        self.controls.set_running(False)
        self.controls.note_runnable(True)
        self.controls.stop_btn.setToolTip("还没在跑")
        self.recognition.refresh(force=True)
        # 图上把"最后停在哪一格"留着，不清空 —— 停下之后最想看的就是它
        self._status.setText(summary)

        lines = [report.summary()]  # type: ignore[attr-defined]
        recoveries = getattr(report, "recoveries", [])
        if recoveries:
            lines.append("")
            lines.append(f"重定位 {len(recoveries)} 次（画面变了、游标下一轮才跟上，属正常）:")
            lines.extend(f"  {record}" for record in recoveries[:10])
        failed = getattr(report, "failed_steps", [])
        if failed:
            lines.append("")
            lines.append(f"{len(failed)} 个步骤失败:")
            lines.extend(f"  {o.step}: {o.message}" for o in failed[:10])
        errors = getattr(report, "errors", [])
        if errors:
            lines.append("")
            lines.append("错误:")
            lines.extend(f"  {message}" for message in errors[:10])
        self._show_check_output("本次运行", lines)

        self._release_run()
        log.info("运行结束: %s", summary)

    @Slot(str)
    def _on_engine_failed(self, message: str) -> None:
        self._engine_running = False
        self.controls.set_running(False)
        self.controls.note_runnable(True)
        self._status.setText("运行出错")
        self._show_check_output("运行出错", [message])
        self._release_run()
        log.error("引擎出错: %s", message)

    def _release_run(self) -> None:
        """关掉本次运行的 Session 与 journal。

        **必须在这里关，而不是在 closeEvent 里**：每次运行都新建一个 Session
        （它持有 mss 的截屏句柄），不关就会一次次泄漏。而 ``RunContext.close()``
        会连带关掉 executor 与 journal。
        """
        ctx = self._run_ctx
        self._run_ctx = None
        if ctx is not None:
            with contextlib.suppress(Exception):
                ctx.close()
        self._run_journal = None

    def _info_box(self, title: str, body: str) -> None:
        QMessageBox.information(self, title, body)
        log.info("[%s] %s", title, body)

    def _show_check_output(self, title: str, lines: list[str]) -> None:
        """把检查/自检/运行结论写到「检查输出」那一页，并切过去。

        **只在这一处显示**：以前右侧面板里还有一份一模一样的（小的），
        同一份数据两处显示会让人以为是两份不同的东西，而且右边那份还占掉了
        大半屏。现在检查结果只有这一个位置。
        """
        body = "\n".join(lines) if lines else "（无输出）"
        self._check_view.setPlainText(f"== {title} ==\n{body}")
        self.workspace.setCurrentWidget(self._check_page)

    # ------------------------------------------------------------------ #
    # 快捷键
    # ------------------------------------------------------------------ #
    def _wire_shortcuts(self) -> None:
        """按 ``shortcuts.SHORTCUTS`` 绑键，并把键位提示贴到按钮上。

        三个"停止"入口（按钮 / Esc / 关窗）都走 :meth:`_on_stop`，所以
        "没在跑时按 Esc" 是安全的空操作。
        """
        self.keymap = Keymap(
            self,
            {
                "run": self._on_start,
                "stop": self._on_stop,
                "check": self._run_check,
                "detect": self.controls.refresh_windows,
                "page_diagram": lambda: self.workspace.setCurrentIndex(0),
                "page_recognition": lambda: self.workspace.setCurrentIndex(1),
                "page_check": lambda: self.workspace.setCurrentIndex(2),
                "help": self._show_shortcuts,
            },
        )
        self.keymap.add_tooltips(
            {
                "start": self.controls.start_btn,
                "stop": self.controls.stop_btn,
                "check": self.controls.check_btn,
                "detect": self.controls.detect,
            }
        )
        # 再登记一份给控件栏：它那几个按钮的 tooltip 是**动态**的
        # （``set_runnable`` 每次换脚本都重设），只追加一次会被冲掉。
        # 登记之后由 ``ControlsBar._tip`` 统一拼，谁重设都带着键位。
        self.controls.set_shortcut_hints(
            {
                spec.button: spec.hint
                for spec in SHORTCUTS
                if spec.button
            }
        )
        log.info("快捷键已就绪（%d 条，F1 看清单）", len(self.keymap))

    @Slot()
    def _show_shortcuts(self) -> None:
        """F1：把快捷键清单弹出来。

        用对话框而不是常驻的菜单栏：菜单要占一行高度，而这个界面宁愿把高度
        留给日志和带框的图。快捷键本来就该"用熟了不用看"，需要看时按 F1。
        """
        lines = [
            "快捷键",
            "",
            *self.keymap.help_lines(),
            "",
            "两点说明：",
            "  · Esc 只在运行中有效，且下拉框弹窗开着时先由下拉框吃掉（关弹窗）",
            "  · 左边三页也能直接点标签切换；图里可滚轮缩放、拖动平移",
        ]
        box = QMessageBox(self)
        box.setWindowTitle("快捷键")
        box.setText("\n".join(lines))
        box.setIcon(QMessageBox.Icon.Information)
        box.exec()

    def _warn_about_unimplemented(self) -> None:
        log.info("=" * 60)
        log.info("控制台：选软件 -> 选游戏 -> 选脚本 -> 开始 / 停止")
        log.info("「开始」会在工作线程里跑 FlowEngine.run()，界面不会卡")
        log.info("=" * 60)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def closeEvent(self, event: QCloseEvent) -> None:
        """关窗前把引擎线程和日志 handler 收干净。

        顺序很重要：先请求停止、等引擎真的退出，再摘日志 handler。
        反过来的话，工作线程可能还会往一个已经断开的桥上发日志。
        """
        log.info("界面关闭，正在收摊……")
        if self._engine_running:
            # 和按钮走同一个入口（**直接调**，不发信号）—— 发信号的话这里也会
            # 卡住，然后 wait(5000) 超时、窗口"关不掉"。
            self._request_engine_stop()

        # 引擎线程：让它把当前这一轮跑完（ctx.sleep 会被停止请求立刻唤醒）
        self._engine_thread.quit()
        if not self._engine_thread.wait(5000):
            log.warning("引擎线程没能在 5 秒内退出，仍继续关窗")

        self._release_run()
        self.bridge.detach()
        super().closeEvent(event)


class _SignalRelay(QObject):
    """把"发一个值给工作线程"变成信号。

    直接用 ``QMetaObject.invokeMethod`` 也行，但那样要按名字调、
    参数类型写错只有运行时才发现。用信号更直白：连错了 PySide 会报出来。
    """

    triggered = Signal()
    value = Signal(int)
    flag = Signal(bool)
