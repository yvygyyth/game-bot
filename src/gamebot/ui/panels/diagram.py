"""把状态树 / 流程图**画出来**，并高亮"现在在哪"。

## 为什么值得自己画

这两个东西本来就是图：状态是树（父子 = 分类与 ROI 继承），流程是带环的有向图
（节点 + 有箭头的边）。用文字打出来（"home/battle @ 战斗"）能读，但**读不出形状** ——
而调脚本时最常问的三个问题都是形状问题：

* 现在卡在哪一层？（树的哪一支亮着）
* 为什么它走到那个节点去了？（图里有没有那条边）
* 这条边什么时候成立？（边上挂的条件）

所以这里用 ``QGraphicsScene`` 画真正的框和箭头，**当前状态 / 当前节点描红加粗**。

## 为什么用 QGraphicsView 而不是 QTreeView / QTableView

``QTreeView`` 只能表达树，而流程图是带环的图；``QTableView`` 更不沾边。
``QGraphicsScene`` 两者都能画，而且缩放/拖拽是白送的。

布局用**简单分层**（按深度分列、同层依次排开）自己算：
不引入 ``graphviz`` 之类的重依赖，代价是长链条会横向变长 —— 但游戏脚本的
状态树就那么几十个节点，够用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..theme import monospace

if TYPE_CHECKING:
    from gamebot.flow.scenario import Scenario

__all__ = ["DiagramPanel", "FlowDiagramView", "StateTreeView"]

#: 节点框的尺寸（够写下 "home/qianli/battle" 这种 id）
NODE_W = 168.0
NODE_H = 40.0
GAP_X = 60.0
GAP_Y = 18.0

#: 自动缩放的比例上下限。"刚好看得清"比"铺满视口"重要 —— 见 ``reset_view``。
MIN_FIT = 0.25
MAX_FIT = 2.0

COLOR_BG = QColor("#1e1e1e")
COLOR_NODE = QColor("#2d2d30")
COLOR_NODE_GROUP = QColor("#26343f")
COLOR_NODE_CURRENT = QColor("#7a2f2f")
COLOR_NODE_EDGE = QColor("#3d3d40")
COLOR_BORDER = QColor("#5a5a5e")
COLOR_BORDER_CURRENT = QColor("#e05c5c")
COLOR_BORDER_MATCH = QColor("#4ec9b0")
COLOR_TEXT = QColor("#e6e6e6")
COLOR_TEXT_DIM = QColor("#9a9a9a")
COLOR_ARROW = QColor("#8a8a8e")
COLOR_ARROW_ACTIVE = QColor("#e05c5c")


class _Diagram(QGraphicsView):
    """一个只读的示意图：能缩放、能拖，不响应编辑。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(COLOR_BG))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._scene.setBackgroundBrush(QBrush(COLOR_BG))
        #: 用户手动缩放/拖动过之后就不再自动适配 —— 否则每轮重画都会
        #: 把他刚调好的视角顶回去（运行中每轮都重画，那会非常烦人）。
        self._user_zoomed = False
        #: 画完了但还没适配（等有了真实尺寸再适配，见 showEvent）
        self._fit_pending = False

    # -- 交互 -------------------------------------------------------------- #
    def wheelEvent(self, event: Any) -> None:
        """滚轮缩放（以鼠标为中心）。调脚本时经常要看全貌/看细节。"""
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._user_zoomed = True
        self.scale(factor, factor)

    def zoom(self, factor: float) -> None:
        self._user_zoomed = True
        self.scale(factor, factor)

    def showEvent(self, event: Any) -> None:
        """第一次真正显示出来时补一次适配。

        为什么不能只在 :meth:`show_tree` 里适配：那时控件刚构造完，
        ``viewport()`` 只有几十像素（Qt 还没布局），算出来的比例会把整张图
        缩成一枚邮票 —— 而那时 ``fitInView`` / ``scale`` 都不会报错，
        只是结果很小。所以标记成"待适配"，等有了真实尺寸再算。
        """
        super().showEvent(event)
        if self._fit_pending and not self._user_zoomed:
            self.reset_view()

    def reset_view(self) -> None:
        """缩放到"刚好看得清"。

        **不直接 fitInView**：场景很小（比如只有两三个节点）时它会忠实地把
        内容放大到铺满整个视口 —— 小图被拉到糊，而且看不出整体结构。
        所以先算 fit 比例，再夹在 ``[MIN_FIT, MAX_FIT]`` 之间：
        小图最多放大一点点，大图才需要缩。

        视口还没布局好（几十像素）时只记下"待适配"，等 ``showEvent`` 再算。
        """
        self._fit_pending = True
        self.resetTransform()
        bounds = self._scene.itemsBoundingRect()
        if bounds.isEmpty():
            return
        viewport = self.viewport().size()
        if viewport.width() < 200 or viewport.height() < 100:
            # 还没真正布局（构造期），现在算出来的比例会小得离谱
            return
        padded = bounds.adjusted(-12, -12, 12, 12)
        scale = min(viewport.width() / padded.width(), viewport.height() / padded.height())
        scale = max(MIN_FIT, min(MAX_FIT, scale))
        self.scale(scale, scale)
        self.centerOn(bounds.center())
        self._fit_pending = False
        self._user_zoomed = False

    # -- 绘制零件 ---------------------------------------------------------- #
    def _node(
        self,
        x: float,
        y: float,
        label: str,
        *,
        current: bool = False,
        matched: bool = False,
        group: bool = False,
        sub: str = "",
    ) -> QRectF:
        rect = QRectF(x, y, NODE_W, NODE_H)
        item = QGraphicsRectItem(rect)
        fill = COLOR_NODE_CURRENT if current else (COLOR_NODE_GROUP if group else COLOR_NODE)
        item.setBrush(QBrush(fill))
        if current:
            border = COLOR_BORDER_CURRENT
        elif matched:
            border = COLOR_BORDER_MATCH
        else:
            border = COLOR_BORDER
        item.setPen(QPen(border, 2.4 if current else 1.2))
        item.setZValue(1)
        self._scene.addItem(item)

        text = QGraphicsSimpleTextItem(_elide(label, 22))
        font = QFont()
        font.setPointSize(9)
        font.setBold(current or group)
        text.setFont(font)
        text.setBrush(QBrush(COLOR_TEXT if not group else COLOR_TEXT_DIM))
        text.setPos(rect.x() + 8, rect.y() + (6 if sub else 11))
        text.setZValue(2)
        self._scene.addItem(text)

        if sub:
            hint = QGraphicsSimpleTextItem(sub)
            small = QFont()
            small.setPointSize(7)
            hint.setFont(small)
            hint.setBrush(QBrush(COLOR_TEXT_DIM))
            hint.setPos(rect.x() + 8, rect.y() + 23)
            hint.setZValue(2)
            self._scene.addItem(hint)
        return rect

    def _arrow(
        self,
        src: QRectF,
        dst: QRectF,
        *,
        label: str = "",
        dashed: bool = False,
        active: bool = False,
    ) -> None:
        """从 src 右边 -> dst 左边画一条带箭头的线（同一列时走上下）。"""
        color = COLOR_ARROW_ACTIVE if active else COLOR_ARROW
        pen = QPen(color, 2.0 if active else 1.2)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        if abs(src.y() - dst.y()) < NODE_H / 2:
            start = QPointF(src.right(), src.center().y())
            end = QPointF(dst.left(), dst.center().y())
        else:
            start = QPointF(src.center().x(), src.bottom())
            end = QPointF(dst.center().x(), dst.top())
        self._scene.addLine(start.x(), start.y(), end.x(), end.y(), pen)

        # 箭头：按方向画一个小三角
        size = 6.0
        if start.x() != end.x():
            tip = end
            pts = [
                tip,
                QPointF(end.x() - size, end.y() - size / 1.6),
                QPointF(end.x() - size, end.y() + size / 1.6),
            ]
        else:
            tip = end
            pts = [
                tip,
                QPointF(end.x() - size / 1.6, end.y() - size),
                QPointF(end.x() + size / 1.6, end.y() - size),
            ]
        arrow = QPolygonF(pts)
        item = self._scene.addPolygon(arrow, QPen(color, 1.0), QBrush(color))
        item.setZValue(0)

        if label:
            text = QGraphicsSimpleTextItem(_elide(label, 18))
            font = QFont()
            font.setPointSize(7)
            text.setFont(font)
            text.setBrush(QBrush(COLOR_TEXT_DIM if not active else COLOR_BORDER_CURRENT))
            text.setPos((start.x() + end.x()) / 2 - 20, (start.y() + end.y()) / 2 - 14)
            text.setZValue(2)
            self._scene.addItem(text)

    def _empty(self, message: str) -> None:
        text = QGraphicsSimpleTextItem(message)
        text.setBrush(QBrush(COLOR_TEXT_DIM))
        text.setPos(10, 10)
        self._scene.addItem(text)


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class StateTreeView(_Diagram):
    """状态树的图：分类节点画成不同底色，**当前状态描红**。"""

    def show_tree(
        self,
        tree: Any,
        *,
        current_page: str = "",
        current_node_page: str = "",
        overlay_pages: tuple[str, ...] = (),
    ) -> None:
        """重画整棵树。

        :param current_page: 跟踪器认出来的**当前状态** —— 描红那个。
        :param current_node_page: 当前流程节点声明的状态。和 ``current_page``
            不一致时，两个都标出来（一个红、一个绿边），一眼就能看出"它以为在哪、
            实际在哪、是不是正在重定位"。
        :param overlay_pages: 命中的叠加层，标个 "+弹窗" 记号。
        """
        self._scene.clear()
        if tree is None or len(tree) == 0:
            self._empty("（没有状态树：先选一个脚本）")
            return

        layout: dict[str, QRectF] = {}
        cursor_y: dict[int, float] = {}

        def place(page: Any, depth: int, parent_rect: QRectF | None) -> None:
            x = depth * (NODE_W + GAP_X)
            y = cursor_y.get(depth, 0.0)
            cursor_y[depth] = y + NODE_H + GAP_Y
            sub = ""
            if page.is_group:
                sub = "分类节点（不匹配）"
            elif page.is_overlay:
                sub = "叠加层"
            elif page.id in overlay_pages:
                sub = "已命中（叠加）"
            rect = self._node(
                x,
                y,
                page.id,
                current=page.id == current_page,
                matched=bool(current_node_page) and page.id == current_node_page,
                group=page.is_group or page.is_overlay,
                sub=sub,
            )
            layout[page.id] = rect
            if parent_rect is not None:
                self._arrow(parent_rect, rect)
            # 注意：``children_of`` 返回的是 **Page 对象**，不是 id。
            # 早先这里写成 ``for child_id in ...: tree.get(child_id)``，
            # 于是 ``get`` 拿到一个 Page 对象、查不到、返回 None，
            # 整棵子树**静默地**没画出来（树上就少了一大截，但界面不报错）。
            # 这种"拿错类型 → None → 静默跳过"是最难看出来的一类 bug，
            # 所以这里显式取 id，并且失败要记日志。
            for child in tree.children_of(page.id):
                place(child, depth + 1, rect)

        for root_id in tree.roots:
            root = tree.get(root_id)
            if root is not None:
                place(root, 0, None)

        self.reset_view()

    #: 兼容"只给一个当前状态"的简单调用
    def show_state(self, tree: Any, current: str) -> None:
        self.show_tree(tree, current_page=current)


class FlowDiagramView(_Diagram):
    """流程图的图：节点框 + 带箭头的边，**当前节点描红**。"""

    def show_graph(self, graph: Any, *, current: str = "") -> None:
        self._scene.clear()
        if graph is None or len(graph) == 0:
            self._empty("（没有流程图：先选一个脚本）")
            return

        # 分层：BFS 从起点算深度（带环的图要防重复访问）
        depth: dict[str, int] = {}
        queue = [graph.initial] if graph.initial else list(graph.nodes)[:1]
        for node_id in queue:
            depth[node_id] = 0
        while queue:
            node_id = queue.pop(0)
            for edge in graph.out_edges(node_id):
                if edge.target not in depth:
                    depth[edge.target] = depth[node_id] + 1
                    queue.append(edge.target)
        for node_id in graph.nodes:
            depth.setdefault(node_id, 0)

        layout: dict[str, QRectF] = {}
        cursor_y: dict[int, float] = {}
        for node_id, level in sorted(depth.items(), key=lambda kv: (kv[1], kv[0])):
            node = graph.node(node_id)
            x = level * (NODE_W + GAP_X)
            y = cursor_y.get(level, 0.0)
            cursor_y[level] = y + NODE_H + GAP_Y
            sub = node.page or "不校验状态"
            layout[node_id] = self._node(
                x, y, node_id, current=node_id == current, sub=_elide(sub, 26)
            )

        for edge in graph.edges:
            src, dst = layout.get(edge.source), layout.get(edge.target)
            if src is None or dst is None:
                continue
            label = edge.label or ("无条件" if not edge.has_condition else "条件")
            self._arrow(
                src,
                dst,
                label=label,
                dashed=not edge.has_condition,
                active=edge.source == current,
            )

        self.reset_view()


class DiagramPanel(QWidget):
    """状态树 / 流程图：上面画图、下面同时给**完整文字版**。

    为什么两个都给：图能一眼看出结构（谁连着谁、当前在哪一格），
    但图里放不下细节 —— 节点 id 长了要省略、ROI 数值、边的优先级、
    "这个状态有没有节点认领"。文字版一行不漏，翻起来慢但**信息全**。
    两个上下摆着看，比在两页之间来回切要省事。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tree_view = StateTreeView(self)
        self._graph_view = FlowDiagramView(self)
        self._scenario: Scenario | None = None

        self._which = QComboBox(self)
        self._which.addItems(["状态树", "流程图"])
        self._which.currentIndexChanged.connect(self._on_switch)

        self._hint = QLabel("—", self)
        self._hint.setStyleSheet("color:#8ab4f8;")
        self._hint.setWordWrap(True)
        monospace(self._hint)

        self._text = QPlainTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text.setToolTip("完整文字版：一行不漏（图里放不下的细节都在这）")
        monospace(self._text)

        bar = QHBoxLayout()
        bar.addWidget(self._which)
        bar.addWidget(self._hint, 1)

        views = QWidget(self)
        views_layout = QVBoxLayout(views)
        views_layout.setContentsMargins(0, 0, 0, 0)
        views_layout.addWidget(self._tree_view)
        views_layout.addWidget(self._graph_view)
        self._graph_view.hide()

        # 用 splitter 而不是固定高度：用户自己决定"多看结构"还是"多看文字"。
        # 文字那块给够最小高度（约 5 行），免得被压成一条缝 —— 那正是
        # 上一版"信息被吃掉"的原因（PageTree 只显示了前两行）。
        vertical = QSplitter(Qt.Orientation.Vertical, self)
        vertical.addWidget(views)
        vertical.addWidget(self._text)
        vertical.setStretchFactor(0, 2)
        vertical.setStretchFactor(1, 2)
        views.setMinimumHeight(150)
        self._text.setMinimumHeight(110)
        vertical.setSizes([280, 175])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(bar)
        layout.addWidget(vertical, 1)

    def set_scenario(self, scenario: Scenario | None) -> None:
        self._scenario = scenario
        self.refresh()

    def refresh(
        self,
        *,
        current_page: str = "",
        current_node: str = "",
        current_node_page: str = "",
        overlays: tuple[str, ...] = (),
    ) -> None:
        """按当前运行状态重画。运行中每轮都会调（几毫秒，可以承受）。"""
        scenario = self._scenario
        if scenario is None:
            self._tree_view.show_tree(None)
            self._graph_view.show_graph(None)
            self._text.setPlainText("（没有场景：先选一个脚本）")
            self._hint.setText("—")
            return
        self._tree_view.show_tree(
            scenario.tree,
            current_page=current_page,
            current_node_page=current_node_page,
            overlay_pages=overlays,
        )
        self._graph_view.show_graph(scenario.graph, current=current_node)
        self._text.setPlainText(_describe(scenario, current_page, current_node))
        if current_page or current_node:
            where = current_page or "unknown"
            expect = current_node_page or "（不校验）"
            self._hint.setText(f"当前 {where}　期望 {expect}　节点 {current_node or '—'}")
        else:
            self._hint.setText("未运行")

    def _on_switch(self, index: int) -> None:
        self._tree_view.setVisible(index == 0)
        self._graph_view.setVisible(index == 1)
        (self._tree_view if index == 0 else self._graph_view).reset_view()


def _describe(scenario: Any, current_page: str, current_node: str) -> str:
    """完整文字版：树 + 图 + 当前位置。

    ``tree.describe()`` / ``graph.describe()`` 是状态层和流程层自己提供的
    权威描述 —— 界面**不再自己拼**一份，避免"界面说的"和"定义实际内容"
    两套说法（那会让人不知道该信哪个）。
    """
    tree = scenario.tree
    graph = scenario.graph
    lines = [
        tree.describe(),
        "",
        graph.describe(),
        "",
        "── 当前 ──",
        f"  状态  {current_page or 'unknown'}",
        f"  节点  {current_node or '（未运行）'}",
    ]
    if current_node:
        node = graph.node(current_node)
        if node is not None:
            edges = len(graph.out_edges(current_node))
            lines.append(f"  期望  {node.page or '（不校验状态）'}")
            lines.append(f"  步骤  {len(node.steps)} 个 / 出边 {edges} 条")
    return "\n".join(lines)
