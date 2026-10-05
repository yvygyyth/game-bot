"""右侧信息面板：脚本规模、所选节点详情、最近一次检查的输出。

这里显示的全部是**装配期数据** —— 构造 ``Scenario``、校验、数节点数边，
一次都不碰游戏窗口。所以它在阶段 1 就能给出真实有用的信息，
不是占位的假面板。

阶段 2 会在这里加"运行状态"那块（当前页面 / 轮次 / 步数 / 最近决策），
数据来自事件流（见 ``docs/ui.md`` 第五节）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..registry import NodeEntry, ScriptDetails, ScriptEntry
from ..theme import monospace

__all__ = ["InfoPanel"]


class InfoPanel(QWidget):
    """脚本静态信息 + 节点详情 + 检查输出。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

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
        form.addRow("未认领页面", self._unclaimed)
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
        node_form = QFormLayout()
        node_form.addRow("期望页面", self._node_page)
        node_form.addRow("步骤数", self._node_steps)
        node_form.addRow("出边数", self._node_edges)
        node_box = QGroupBox("所选节点", self)
        node_layout = QVBoxLayout(node_box)
        node_layout.addLayout(node_form)

        # ---- 状态树 / 流程图 / 检查输出 ----
        self._tree = self._readonly()
        self._graph = self._readonly()
        self._report = self._readonly()
        tabs = QTabWidget(self)
        tabs.addTab(self._tree, "状态树")
        tabs.addTab(self._graph, "流程图")
        tabs.addTab(self._report, "检查输出")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(summary)
        layout.addWidget(node_box)
        layout.addWidget(tabs, 1)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _readonly() -> QPlainTextEdit:
        widget = QPlainTextEdit()
        widget.setReadOnly(True)
        widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        monospace(widget)
        return widget

    # ------------------------------------------------------------------ #
    def set_details(self, entry: ScriptEntry | None, details: ScriptDetails | None) -> None:
        """换脚本。"""
        if entry is None or details is None:
            self._title.setText("未选择脚本")
            self._subtitle.setText("")
            self._scale.setText("—")
            self._unclaimed.setText("—")
            self._roots.setText("—")
            self._tree.setPlainText("")
            self._graph.setPlainText("")
            return

        self._title.setText(f"{entry.title}   ({entry.key})")
        self._subtitle.setText(entry.description or "")
        self._scale.setText(
            f"{details.pages} 页面 / {details.nodes} 节点 / {details.edges} 边"
        )
        self._unclaimed.setText(
            "、".join(details.unclaimed)
            if details.unclaimed
            else "无（叠加层和终态页面不需要节点）"
        )
        self._roots.setText("\n".join(details.template_roots) or "—")
        self._tree.setPlainText(details.tree_text)
        self._graph.setPlainText(details.graph_text)
        if details.problems:
            self.show_report("定义有问题", list(details.problems))

    def set_node(self, node: NodeEntry | None) -> None:
        """换起始节点。"""
        if node is None:
            self._node_page.setText("—")
            self._node_steps.setText("—")
            self._node_edges.setText("—")
            return
        self._node_page.setText(node.page or "（任意页面 —— 不绑定页面）")
        self._node_steps.setText(str(node.steps))
        self._node_edges.setText(str(node.out_edges))

    def show_report(self, title: str, lines: list[str]) -> None:
        """把检查 / 自检的结果写进"检查输出"页。"""
        body = "\n".join(lines) if lines else "（无输出）"
        self._report.setPlainText(f"== {title} ==\n{body}")
        tabs = self.findChild(QTabWidget)
        if tabs is not None:
            tabs.setCurrentIndex(2)
