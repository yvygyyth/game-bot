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

        # ---- 首次填充 ----
        # 先枚举窗口、再选脚本：脚本选中时就要按"当前窗口标题"建抓屏会话，
        # 顺序反了会先按空标题建一次（抓整屏），再重建一次，白折腾。
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

        # 跨线程：窗口 -> 工作线程
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
        """让工作线程重建抓屏会话。"""
        config = self._current_config()
        if config is None:
            self.preview.show_error("没有可用的配置")
            return
        self.configureSource.emit(config, title or self.controls.window_title)

    @Slot(QImage, float, tuple, int)
    def _on_frame(self, image: QImage, elapsed: float, size: tuple, seq: int) -> None:
        self.preview.show_frame(image, elapsed, size, seq)

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
    # 开始 / 停止（阶段 2）
    # ------------------------------------------------------------------ #
    def _on_start(self) -> None:
        reason = "界面还没接到 FlowEngine.run()（阶段 2）"
        QMessageBox.information(self, "还没实现", reason)
        log.info("「开始」被点了，但%s", reason)

    def _on_stop(self) -> None:
        # 阶段 2 这里会调 ctx.request_stop()。现在不需要做什么，
        # 因为根本没有在跑的东西。
        log.info("「停止」被点了，当前没有在跑的脚本")

    def _warn_about_unimplemented(self) -> None:
        log.info("=" * 60)
        log.info("阶段 1：选脚本、看画面、看日志、检查、自检 都能用")
        log.info("「开始」/「停止」还没接到引擎（阶段 2：引擎侧已就绪）")
        log.info("=" * 60)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def closeEvent(self, event: QCloseEvent) -> None:
        """关窗前把工作线程和日志 handler 收干净。

        顺序很重要：先让工作线程收摊并**等它真的退出**，再摘日志 handler。
        反过来的话，工作线程可能还会往一个已经断开的桥上发日志。
        """
        log.info("界面关闭，正在收摊……")
        QMetaObject.invokeMethod(
            self._worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection
        )
        self._thread.quit()
        self._thread.wait(3000)

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
