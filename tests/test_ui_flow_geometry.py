"""流程图的**几何**：连线不能穿过节点。

## 为什么这类断言必须写

图上"线穿过节点""标签压在文字上"是**肉眼才能发现**的问题 ——
而检查的代价（每次改布局都要盯图）比写这几条断言高得多。
尤其回边和自环：它们是两个特殊分支，手工只会在想到的时候才试一次。

所以这里不测"画得好不好看"（那没法测），只测两条**客观不变量**：

1. 连线的**任何一段**都不穿过节点的矩形内部；
2. 每条边都**画出来了**（防止 ``layout.get`` 拿不到就静默跳过 —— 那类 bug 踩过）。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsRectItem

from gamebot.flow.graph import EdgeKind, Graph, Node, Transition
from gamebot.ui.panels.diagram import FlowDiagramView

pytest.importorskip("PySide6")


def _view(graph: Graph) -> FlowDiagramView:
    view = FlowDiagramView()
    view.resize(1200, 600)
    view.show()
    view.show_graph(graph)
    return view


def _node_rects(view: FlowDiagramView) -> list[QRectF]:
    """场景里所有**节点框**的矩形。

    节点框是 ``QGraphicsRectItem``；边标签的底色框也是这个类型 ——
    所以按大小区分：节点框是 ``NODE_W x NODE_H``，标签底色很扁。
    """
    rects = []
    for item in view.scene().items():
        if isinstance(item, QGraphicsRectItem):
            rect = item.rect()
            if rect.width() > 60 and rect.height() > 20:
                rects.append(item.sceneBoundingRect())
    return rects


def _line_segments(view: FlowDiagramView) -> list[tuple[float, float, float, float]]:
    return [
        (item.line().x1(), item.line().y1(), item.line().x2(), item.line().y2())
        for item in view.scene().items()
        if isinstance(item, QGraphicsLineItem)
    ]


def _crosses_node(segment: tuple[float, float, float, float], rect: QRectF) -> bool:
    """线段和矩形内部**是否真的相交**（贴边不算）。

    用 Liang-Barsky 那套的简化版：把线段参数化 ``P = A + t*(B-A)``，
    求它在矩形内部的那段参数区间是否非空。
    """
    x1, y1, x2, y2 = segment
    dx, dy = x2 - x1, y2 - y1
    # 收缩一点：贴着节点边框走线是可以的（线本来就从边上进出）
    shrink = 2.0
    left, top = rect.left() + shrink, rect.top() + shrink
    right, bottom = rect.right() - shrink, rect.bottom() - shrink

    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - left), (dx, right - x1), (-dy, y1 - top), (dy, bottom - y1)):
        if p == 0:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True


def _chain() -> Graph:
    g = Graph(initial="a")
    g.add_node(Node("a", transitions=[Transition("b", priority=10)]))
    g.add_node(Node("b", transitions=[Transition("c", priority=10)]))
    g.add_node(Node("c"))
    return g


def _cycle() -> Graph:
    g = Graph(initial="a")
    g.add_node(Node("a", transitions=[Transition("b", priority=10)]))
    g.add_node(Node("b", transitions=[Transition("c", priority=10)]))
    g.add_node(Node("c", transitions=[Transition("a", kind=EdgeKind.FALLBACK)]))
    return g


def _self_loop() -> Graph:
    g = Graph(initial="a")
    g.add_node(Node("a", transitions=[Transition("b", priority=10)]))
    g.add_node(Node("b", transitions=[Transition("b", priority=10)]))
    return g


class TestEdgesDoNotCrossNodes:
    """连线的每一段都不能穿过节点内部。"""

    @pytest.mark.parametrize(
        ("name", "build", "edge_count"),
        [
            ("直线链", _chain, 2),
            ("带环", _cycle, 3),
            ("带自环", _self_loop, 2),
        ],
    )
    def test_no_segment_enters_a_node(self, qt_app, name, build, edge_count):
        view = _view(build())
        rects = _node_rects(view)
        assert len(rects) >= 2, f"{name}: 节点框没画出来（找到 {len(rects)} 个）"

        bad = [
            (seg, rect)
            for seg in _line_segments(view)
            for rect in rects
            if _crosses_node(seg, rect)
        ]
        assert not bad, f"{name}: 有 {len(bad)} 段连线穿过节点内部"
        view.close()

    @pytest.mark.parametrize(
        ("name", "build", "edge_count"),
        [
            ("直线链", _chain, 2),
            ("带环", _cycle, 3),
            ("带自环", _self_loop, 2),
        ],
    )
    def test_every_edge_is_drawn(self, qt_app, name, build, edge_count):
        """每条边都要有**终点箭头** —— 箭头数 == 边数。

        这条防的是"静默丢边"：``layout.get(...)`` 拿不到就 ``continue`` 的话，
        图上会少一条边而**不报任何错**。那类 bug 踩过一次（树的子节点整片没画出来）。
        """
        from PySide6.QtWidgets import QGraphicsPolygonItem

        view = _view(build())
        arrows = [i for i in view.scene().items() if isinstance(i, QGraphicsPolygonItem)]
        assert len(arrows) == edge_count, f"{name}: 画了 {len(arrows)} 个箭头，边有 {edge_count} 条"
        view.close()

    def test_a_cycle_does_not_overlap_the_forward_edges(self, qt_app):
        """回边走上方通道，前瞻边的标签走下方 —— 两拨不能撞在一起。

        回边横线的 y 必须**在节点上方**；前瞻边的标签 y 必须**在节点下方**。
        撞在一起的话字会压在线上（第一版就是这样）。
        """
        view = _view(_cycle())
        node_tops = [r.top() for r in _node_rects(view)]
        node_bottoms = [r.bottom() for r in _node_rects(view)]
        assert node_tops and node_bottoms

        # 水平线里，在节点上方的那条 = 回边的通道
        horizontal = [
            seg for seg in _line_segments(view) if abs(seg[1] - seg[3]) < 0.5
        ]
        above = [s for s in horizontal if s[1] < min(node_tops)]
        assert above, "没找到回边的上方通道"
        assert min(s[1] for s in above) < min(node_tops) - 5, "回边通道离节点太近"
        view.close()
