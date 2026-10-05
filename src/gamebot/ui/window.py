"""主窗口：把三块（控制栏 / 画面+信息 / 日志）拼起来并接线。

## 线程

窗口是界面线程唯一的"大老板"。它持有：

* 一个 :class:`LogBridge` —— 日志过来（可能来自工作线程的 emit）；
* 一个 ``QThread`` + :class:`CaptureWorker` —— 抓帧在那里跑。

两条规矩（见 ``docs/ui.md`` 第四节）：

1. 跨线程只传**值**（``QImage`` / ``str`` / dataclass），绝不传控件；
2. 关窗时先让工作线程收摊（``shutdown`` -> ``quit`` -> ``wait``），
   再摘日志 handler。顺序反了会留下后台线程或悬空引用。
"""

from __future__ import annotations

import contextlib
from typing import Any

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..config.loader import load_config
from ..exceptions import GameBotError
from ..utils.logging import get_logger
from .engine import EngineWorker
from .logbridge import LogBridge
from .panels.controls import ControlsBar
from .panels.info import InfoPanel
from .panels.logview import LogView
from .panels.preview import CaptureWorker, PreviewPanel
from .registry import ScriptDetails, ScriptEntry, load_details, load_scripts

log = get_logger("ui.window")

__all__ = ["MainWindow"]

_WINDOW_TITLE = "gamebot 控制台"


class MainWindow(QMainWindow):
    """本地控制台。"""

    #: 请求工作线程重建抓屏会话（跨线程，所以走信号）
    configureSource = Signal(object, str)

    def __init__(
        self,
        config_path: str = "config/app.yaml",
        *,
        initial_script: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_path = config_path
        self._entry: ScriptEntry | None = None
        self._details: ScriptDetails | None = None
        self._engine_running = False
        self._run_ctx: Any = None
        self._run_journal: Any = None

        self.setWindowTitle(_WINDOW_TITLE)

        # ---- 日志桥（界面线程唯一持有者）----
        self.bridge = LogBridge(maxlen=2000)
        self.bridge.attach()

        # ---- 三块面板 ----
        self.controls = ControlsBar(self)
        self.preview = PreviewPanel(self)
        self.info = InfoPanel(self)
        self.logview = LogView(self.bridge, self)

        self._status = QLabel("就绪", self)
        self._status.setStyleSheet("color:#7f8c8d; padding:2px 6px;")

        self._build_layout()
        self._make_capture_thread()
        self._wire()
        self._start_capture_thread()
        self._start_engine_thread()

        # ---- 首次填充 ----
        # 先枚举窗口、再选脚本：用户的操作顺序是"先选软件、再选游戏、再选脚本"，
        # 界面初始化也照这个顺序，否则第一眼看到的是个空下拉框。
        self.controls.refresh_windows()
        self._load_scripts(initial_script)
        log.info("界面已启动（配置文件: %s）", config_path)
        self._warn_about_unimplemented()

    # ------------------------------------------------------------------ #
    # 布局
    # ------------------------------------------------------------------ #
    def _build_layout(self) -> None:
        upper = QSplitter(Qt.Orientation.Horizontal, self)
        upper.addWidget(self.preview)
        upper.addWidget(self.info)
        upper.setStretchFactor(0, 3)
        upper.setStretchFactor(1, 2)
        upper.setSizes([700, 460])

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

    def _banner(self) -> QLabel:
        """一条常驻提示：把"哪些按钮现在还不能用"说在前面。

        比让用户逐个去试要好 —— 阶段 1 的界面上确实有灰按钮，
        与其让人以为是 bug，不如直接说清。
        """
        label = QLabel(
            "阶段 1：选脚本 / 看画面 / 看日志已可用；"
            "「开始」还没接线 —— 引擎侧（状态定位 + 主循环 + 执行器）已经就绪，"
            "但界面还没把「开始」接到 FlowEngine.run() 上（阶段 2）。",
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

        三条连接各有理由：

        * ``configure`` **直连**（不是队列连接）—— 它只是赋值，必须在界面线程
          执行完再去触发 ``run``。走队列的话"配置好了没"和"开始跑"会变成两个
          互不知情的异步事件，偶发地先跑后配；
        * ``run`` 走**队列连接**，由 ``_engineTickRelay`` 触发 ——
          这就是"把阻塞循环甩到工作线程"的那一步；
        * ``request_stop`` 也走队列，但即使它被直接调用也是安全的：
          它只设一个标志位。
        """
        self._engine_thread = QThread(self)
        self._engine_worker = EngineWorker()
        self._engine_worker.moveToThread(self._engine_thread)
        self._engineTickRelay = _SignalRelay(self)
        self._engineStopRelay = _SignalRelay(self)

        self._engineTickRelay.triggered.connect(self._engine_worker.run)
        self._engineStopRelay.triggered.connect(self._engine_worker.request_stop)
        self._engine_worker.frameReady.connect(self._on_engine_frame)
        self._engine_worker.ticked.connect(self.info.set_run_state)
        self._engine_worker.finished.connect(self._on_engine_finished)
        self._engine_worker.failed.connect(self._on_engine_failed)

        self._engine_thread.start()

    # ------------------------------------------------------------------ #
    # 接线
    # ------------------------------------------------------------------ #
    def _wire(self) -> None:
        self.controls.scriptChanged.connect(self._on_script_changed)
        self.controls.nodeChanged.connect(self.info.set_node)
        self.controls.windowChanged.connect(self._on_window_changed)
        self.controls.checkRequested.connect(self._run_check)
        self.controls.selftestRequested.connect(self._run_selftest)
        self.controls.startRequested.connect(self._on_start)
        self.controls.stopRequested.connect(self._on_stop)

        self.preview.intervalChanged.connect(self._on_interval_changed)
        self.preview.liveChanged.connect(self._on_live_changed)
        self.preview.grabRequested.connect(self._request_grab)

        # 注意：日志信号由 LogView 在它自己的构造里接上（那块归它管）。
        # 这里**不要**再连一次 —— 连两次的话每条日志会被追加两遍。

        # 跨线程：窗口 -> 抓帧线程 / 引擎线程
        self.configureSource.connect(self._worker.configure)

    def _make_capture_thread(self) -> None:
        """造工作线程与三个"把值发给它"的中继信号。

        中继先建、后接线：``PreviewPanel`` 在构造时就会发一次
        ``intervalChanged``（它把下拉框设成默认值），那时中继必须已经存在。
        """
        self._thread = QThread(self)
        self._worker = CaptureWorker(interval_ms=self.preview.interval_ms)
        self._worker.moveToThread(self._thread)
        self._grabRelay = _SignalRelay(self)
        self._intervalRelay = _SignalRelay(self)
        self._liveRelay = _SignalRelay(self)

    def _start_capture_thread(self) -> None:
        self._thread.started.connect(self._worker.start)
        self._worker.frameReady.connect(self._on_frame)
        self._worker.failed.connect(self._on_capture_failed)
        self._worker.sourceReady.connect(self.preview.set_source_label)

        self._grabRelay.triggered.connect(self._worker.grab_once)
        self._intervalRelay.value.connect(self._worker.set_interval)
        self._liveRelay.flag.connect(self._worker.set_live)

        self._thread.start()

    # ------------------------------------------------------------------ #
    # 脚本
    # ------------------------------------------------------------------ #
    def _load_scripts(self, initial_script: str = "") -> None:
        entries, note = load_scripts()
        self.controls.set_scripts(entries, note=note)
        if not entries:
            msg = note or "没有发现任何脚本"
            log.warning(msg)
            self.info.show_report("脚本列表为空", [msg])
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
            self.info.set_details(None, None)
            self.controls.set_nodes(())
            self.controls.set_runnable(False, "先选一个脚本")
            # 也要重建抓屏会话：这时改用配置文件里的设置（通常是真后端），
            # 于是"不选脚本"就能单纯看画面。忘了这一句的话预览会一直
            # 停留在上一个脚本的后端上（表现是"切了脚本画面没变"）。
            self._request_source()
            return

        details = load_details(entry)
        self._details = details
        self.info.set_details(entry, details)
        self.controls.set_nodes(
            details.node_list,
            enabled=bool(details.node_list),
        )
        self.controls.set_runnable(False, "界面还没接到 FlowEngine.run()（阶段 2）")
        if details.problems:
            self._status.setText(f"{entry.key}: 定义有问题（见「检查输出」）")
            log.warning("脚本 %s 的定义有问题: %s", entry.key, details.problems)
        else:
            self._status.setText(
                f"{entry.key}: {details.pages} 页面 / {details.nodes} 节点 / "
                f"{details.edges} 边"
            )
        self._request_source()

    @Slot(object)
    def _on_window_changed(self, title: str) -> None:
        self._request_source(title)

    # ------------------------------------------------------------------ #
    # 抓屏
    # ------------------------------------------------------------------ #
    def _current_config(self) -> Any:
        """当前该用哪份配置：优先脚本自己的，退回配置文件。"""
        if self._entry is not None and self._entry.spec is not None:
            try:
                return self._entry.spec.build_config()
            except Exception as exc:
                log.warning("用脚本的配置失败，改为读配置文件: %s", exc)
        try:
            return load_config(self._config_path)
        except GameBotError as exc:
            log.error("读配置失败: %s", exc)
            return None

    def _request_source(self, title: str = "") -> None:
        """让工作线程重建抓屏会话。

        ``title`` 为空表示"没有明确选软件" —— 这时**不要**用下拉框里那一项
        （它可能只是枚举出来的第一个），而是让配置里的 ``window_title`` 生效。
        否则界面会一启动就去抓某个恰好排在第一的窗口，而你想要的是整屏。
        """
        config = self._current_config()
        if config is None:
            self.preview.show_error("没有可用的配置")
            return
        self.configureSource.emit(config, title or self.controls.window_title)

    @Slot(QImage, float, tuple, int)
    def _on_frame(self, image: QImage, elapsed: float, size: tuple, seq: int) -> None:
        self.preview.show_frame(image, elapsed, size, seq)

    @Slot(object, tuple)
    def _on_engine_frame(self, image: QImage, size: tuple) -> None:
        """引擎那一帧也送去预览。

        引擎跑起来时抓帧线程已经被静音（``_liveRelay.flag.emit(False)``），
        所以不会两边同时往预览里塞画面 —— 那会让人看到画面在"闪两套图"。

        耗时填 0：这一帧是引擎**已经截好并用过**的，量它的抓帧耗时没有意义，
        预览那行文字留着显示尺寸和计数。
        """
        self.preview.show_frame(image, 0.0, size, 0)

    @Slot(str)
    def _on_capture_failed(self, message: str) -> None:
        self.preview.show_error(message)
        log.error(message)

    @Slot(int)
    def _on_interval_changed(self, interval_ms: int) -> None:
        self._intervalRelay.value.emit(interval_ms)

    @Slot(bool)
    def _on_live_changed(self, on: bool) -> None:
        self._liveRelay.flag.emit(on)

    def _request_grab(self) -> None:
        self._grabRelay.triggered.emit()

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

        self.info.show_report(f"检查 {entry.key}", lines)
        for line in lines:
            log.info("[check] %s", line)

    def _run_selftest(self) -> None:
        entry = self._entry
        if entry is None or entry.spec is None:
            return
        if entry.spec.selftest is None:
            self.info.show_report(f"自检 {entry.key}", ["· 这个脚本没有 selftest()"])
            return
        lines: list[str] = []
        try:
            if entry.spec.prepare is not None:
                written = entry.spec.prepare()
                lines.append(f"· 准备资源：生成/更新 {written} 个文件")
            failures = entry.spec.selftest()
            if failures:
                lines.append(f"✗ {len(failures)} 项失败")
                lines.extend(f"    - {item}" for item in failures)
            else:
                lines.append("✓ 全部通过")
        except Exception as exc:
            lines.append(f"✗ {type(exc).__name__}: {exc}")

        self.info.show_report(f"自检 {entry.key}", lines)
        for line in lines:
            log.info("[selftest] %s", line)

    # ------------------------------------------------------------------ #
    # 开始 / 停止
    # ------------------------------------------------------------------ #
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
            ctx = build_context(config, scenario=scenario, journal=journal)
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

        # 预览交给引擎（它自己抓帧），别再让 CaptureWorker 抢同一个后端
        self._liveRelay.flag.emit(False)
        self._engine_worker.configure(ctx, engine, node_id)
        self._engine_tick_relay.triggered.emit()
        log.info("开始运行 %s（起始节点 %s）", entry.key, node_id or scenario.graph.initial)

    def _on_stop(self) -> None:
        """请求停止。引擎在下一次 sleep 时被唤醒（毫秒级），不杀线程。"""
        if not self._engine_running:
            log.info("「停止」被点了，当前没有在跑的脚本")
            return
        self.controls.stop_btn.setEnabled(False)
        self.controls.stop_btn.setToolTip("正在等引擎退出这一轮……")
        self._status.setText("正在停止……")
        self._engine_stop_relay.triggered.emit()

    @Slot(object, str)
    def _on_engine_finished(self, report: object, summary: str) -> None:
        """跑完了：解锁界面、关会话、把结论写出来。"""
        self._engine_running = False
        self.controls.set_running(False)
        self.controls.note_runnable(True)
        self.controls.stop_btn.setToolTip("还没在跑")
        self.preview.set_live_enabled(True)
        self._liveRelay.flag.emit(self.preview.live)

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
        self.info.show_report("本次运行", lines)

        self._release_run()
        log.info("运行结束: %s", summary)

    @Slot(str)
    def _on_engine_failed(self, message: str) -> None:
        self._engine_running = False
        self.controls.set_running(False)
        self.controls.note_runnable(True)
        self.preview.set_live_enabled(True)
        self._liveRelay.flag.emit(self.preview.live)
        self._status.setText("运行出错")
        self.info.show_report("运行出错", [message])
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

    def _warn_about_unimplemented(self) -> None:
        log.info("=" * 60)
        log.info("控制台：选软件 -> 选游戏 -> 选脚本 -> 开始 / 停止")
        log.info("「开始」会在工作线程里跑 FlowEngine.run()，界面不会卡")
        log.info("=" * 60)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def closeEvent(self, event: QCloseEvent) -> None:
        """关窗前把工作线程和日志 handler 收干净。

        顺序很重要：先请求停止、等引擎真的退出，再收抓帧线程和日志 handler。
        反过来的话，工作线程可能还会往一个已经断开的桥上发日志。
        """
        log.info("界面关闭，正在收摊……")
        if self._engine_running:
            self._engine_stop_relay.triggered.emit()

        QMetaObject.invokeMethod(
            self._worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection
        )
        self._thread.quit()
        self._thread.wait(3000)

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
