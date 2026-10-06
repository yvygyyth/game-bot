"""右侧信息面板：运行状态 + 脚本规模 + 所选节点详情 + 最近一次检查的输出。

上半部分是**运行状态**（阶段 2 加的），数据来自 ``EngineWorker`` 每轮发来的
``TickEvent`` —— 那是个 frozen dataclass，跨线程传的是值不是引擎对象。

其余全部是**装配期数据** —— 构造 ``Scenario``、校验、数节点数边，
一次都不碰游戏窗口。所以不跑脚本时也有真实信息，不是占位假面板。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..registry import NodeEntry, ScriptDetails, ScriptEntry

__all__ = ["InfoPanel"]


class InfoPanel(QWidget):
    """运行状态 + 脚本静态信息 + 节点详情 + 检查输出。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ---- 运行状态（每轮刷新） ----
        self._run_state = QLabel("—", self)
        self._run_state.setStyleSheet("font-weight:600; font-size:14px;")
        self._run_expect = QLabel("—", self)
        self._run_node = QLabel("—", self)
        self._run_tick = QLabel("—", self)
        self._run_recovery = QLabel("—", self)
        self._run_recovery.setWordWrap(True)

        run_form = QFormLayout()
        run_form.addRow("当前状态", self._run_state)
        run_form.addRow("期望状态", self._run_expect)
        run_form.addRow("当前节点", self._run_node)
        run_form.addRow("轮次", self._run_tick)
        run_form.addRow("最近重定位", self._run_recovery)

        run_box = QGroupBox("运行状态", self)
        run_layout = QVBoxLayout(run_box)
        run_layout.addLayout(run_form)

        self._title = QLabel("未选择脚本", self)
        self._title.setStyleSheet("font-weight:600;")
        self._subtitle = QLabel("", self)
        self._subtitle.setStyleSheet("color:#7f8c8d;")
        self._subtitle.setWordWrap(True)

        self._scale = QLabel("—", self)
        self._unclaimed = QLabel("—", self)
        self._unclaimed.setWordWrap(True)
        self._roots = QLabel("—", self)
        self._roots.setWordWrap(True)

        form = QFormLayout()
        form.addRow("规模", self._scale)
        form.addRow("未认领状态", self._unclaimed)
        form.addRow("模板根", self._roots)

        summary = QGroupBox("脚本", self)
        summary_layout = QVBoxLayout(summary)
        summary_layout.addWidget(self._title)
        summary_layout.addWidget(self._subtitle)
        summary_layout.addLayout(form)

        # ---- 节点详情 ----
        self._node_page = QLabel("—", self)
        self._node_steps = QLabel("—", self)
        self._node_edges = QLabel("—", self)
        self._node_page.setWordWrap(True)
        node_form = QFormLayout()
        node_form.addRow("期望状态", self._node_page)
        node_form.addRow("步骤数", self._node_steps)
        node_form.addRow("出边数", self._node_edges)
        node_box = QGroupBox("所选节点", self)
        node_layout = QVBoxLayout(node_box)
        node_layout.addLayout(node_form)

        # **故意没有**"状态树 / 流程图 / 检查输出"那三页了：
        # 左边就是那三页，而且能画成图、能点。这里再放一份是把同一份数据
        # 在两个地方各显示一遍 —— 占位置，还会让人以为是两份不同的东西。
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(run_box)
        layout.addWidget(summary)
        layout.addWidget(node_box)
        layout.addStretch(1)

    # ------------------------------------------------------------------ #
    # 运行状态
    # ------------------------------------------------------------------ #
    def set_run_state(self, event: object | None) -> None:
        """刷新运行状态那一块（每轮一次）。``None`` = 清空（未运行）。

        刻意把"期望状态"和"当前状态"分两行摆：它们不一致的那一刻正是重定位
        发生的时候，而那是排查"它为什么跳了"时唯一要看的东西。
        """
        if event is None:
            self._run_state.setText("—")
            self._run_expect.setText("—")
            self._run_node.setText("—")
            self._run_tick.setText("—")
            self._run_recovery.setText("—")
            return

        page = getattr(event, "page", "unknown")
        overlays = getattr(event, "overlays", ())
        expected = getattr(event, "expected", "")
        confirmed = getattr(event, "confirmed", False)

        suffix = f"  +{'/'.join(overlays)}" if overlays else ""
        self._run_state.setText(f"{page}{suffix}" + ("" if confirmed else "  (确认中)"))
        self._run_expect.setText(expected or "（不校验）")
        self._run_node.setText(getattr(event, "node", "—") or "—")

        aligned = getattr(event, "aligned", True)
        mark = "" if aligned else "   ⚠ 不一致"
        self._run_tick.setText(f"{getattr(event, 'tick', 0)} 轮{mark}")

        count = getattr(event, "recoveries", 0)
        last = getattr(event, "last_recovery", "")
        self._run_recovery.setText(f"{count} 次{('　' + last) if last else ''}")

    def set_details(self, entry: ScriptEntry | None, details: ScriptDetails | None) -> None:
        """换脚本。"""
        if entry is None or details is None:
            self._title.setText("未选择脚本")
            self._subtitle.setText("")
            self._scale.setText("—")
            self._unclaimed.setText("—")
            self._roots.setText("—")
            return

        self._title.setText(f"{entry.title}   ({entry.key})")
        self._subtitle.setText(entry.description or "")
        self._scale.setText(
            f"{details.pages} 状态 / {details.nodes} 节点 / {details.edges} 边"
        )
        self._unclaimed.setText(
            "、".join(details.unclaimed)
            if details.unclaimed
            else "无（分类节点和叠加层不需要节点）"
        )
        self._roots.setText("\n".join(details.template_roots) or "—")

    def set_node(self, node: NodeEntry | None) -> None:
        """换起始节点。"""
        if node is None:
            self._node_page.setText("—")
            self._node_steps.setText("—")
            self._node_edges.setText("—")
            return
        self._node_page.setText(node.state or "（不关联状态 —— 不做校验）")
        self._node_steps.setText(str(node.steps))
        self._node_edges.setText(str(node.out_edges))
