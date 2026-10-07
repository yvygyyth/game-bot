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

#: 节点框的尺寸。**够写下两行**：name 一行、id 一行。
NODE_W = 210.0
NODE_H = 46.0
GAP_X = 150.0
"""列间距。**不只是留白**：长的边说明要放在这一缝里（见 `_edge`），
60 太窄会压到下一个节点上。"""
GAP_Y = 18.0

#: 自动缩放的比例上下限。"刚好看得清"比"铺满视口"重要 —— 见 ``reset_view``。
MIN_FIT = 0.25
MAX_FIT = 2.0

COLOR_BG = QColor("#1e1e1e")
COLOR_NODE = QColor("#2d2d30")
COLOR_NODE_GROUP = QColor("#26343f")
#: 当前状态**和流程预期不一致**时的底色 —— 也就是"需要重定位"的那一刻。
COLOR_BORDER = QColor("#5a5a5e")
#: 当前状态**和流程预期不一致**时的底色 —— 也就是"需要重定位"的那一刻。
COLOR_NODE_MISALIGNED = QColor("#7a2f2f")
#: **绿 = 一致**：识别出来的状态就是流程预期的那个，一切正常。
COLOR_BORDER_OK = QColor("#4ec9b0")
#: **红 = 不一致**：流程以为在别处，需要重定位。**最该被看见的一刻。**
COLOR_BORDER_MISALIGNED = QColor("#e05c5c")
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
        # ---- 导航：拖拽，不要滚动条 ----
        #
        # **关掉滚动条但仍然能拖**：``ScrollBarAlwaysOff`` 只是不画那两个条，
        # 滚动范围照旧存在，所以 ``ScrollHandDrag`` 的拖动、以及滚轮缩放
        # 都还正常。图本来就不大，滚动条占地方又容易误拖。
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._scene.setBackgroundBrush(QBrush(COLOR_BG))
        #: 用户手动缩放/拖动过之后就不再自动适配 —— 否则每轮重画都会
        #: 把他刚调好的视角顶回去（运行中每轮都重画，那会非常烦人）。
        self._user_zoomed = False
        #: 画完了但还没适配（等有了真实尺寸再适配，见 showEvent）
        self._fit_pending = False
        #: 正在重画（``_redraw`` 块内）—— 块内不自动适配
        self._rebuilding = False
        #: 中键拖拽的起点（``None`` = 没在拖）。左键也能拖（``ScrollHandDrag``），
        #: 但左键在图元上会被它自己接管；中键是通用的"平移"手势，补一个。
        self._pan_from: QPointF | None = None

    # -- 交互 -------------------------------------------------------------- #
    def mousePressEvent(self, event: Any) -> None:
        """中键按下 = 开始平移。"""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        """中键拖拽：把位移换算成滚动条的值。

        走滚动条（而不是 ``translate`` 变换）：**和 ``ScrollHandDrag`` 同一套机制**，
        两者不会互相打架，``reset_view`` 也只要重算缩放、不用管平移量。
        """
        if self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_from is not None:
            self._pan_from = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

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

    def reset_view(self, *, force: bool = False) -> None:
        """缩放到"刚好看得清"。**用户自己调过之后就不再自动调它。**

        这是修"一放大就缩回去"的**根本那一句**：重画（每轮一次）原来无条件
        调它，于是 ``resetTransform()`` 把用户刚放大的比例顶回去。
        现在它自己判断 —— 用户动过就不动。

        :param force: 忽略"用户动过"。给**换了个场景**这种场合用：
            换脚本之后必然想看到新图的全貌，而不是继承上一个脚本的视角。
            （运行中的每轮重画**不要**传它 —— 那正是要避免的。）

        **不直接 fitInView**：场景很小（比如只有两三个节点）时它会忠实地把
        内容放大到铺满整个视口 —— 小图被拉到糊，而且看不出整体结构。
        所以先算 fit 比例，再夹在 ``[MIN_FIT, MAX_FIT]`` 之间：
        小图最多放大一点点，大图才需要缩。

        视口还没布局好（几十像素）时只记下"待适配"，等 ``showEvent`` 再算。
        """
        if not force and (self._user_zoomed or self._rebuilding):
            # 用户已经把视角调好了（或者正在重画途中）—— 别碰它。
            # 这里不报错也不提示：滚一下滚轮就是明确的"我要这个视角"。
            return
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

    # -- 绘制零件 ---------------------------------------------------------- #
    def _node(
        self,
        x: float,
        y: float,
        title: str,
        sub: str = "",
        *,
        aligned: bool | None = None,
        group: bool = False,
    ) -> QRectF:
        """画一个节点框：**第一行 title、第二行 sub**（sub 空就只显示一行）。

        ## 边框的两个颜色是**一致 / 不一致**，不是"当前 / 预期"

        * **绿**（``aligned=True``）—— 识别出来的状态**就是**流程预期的那个。
          正常推进时一直是绿框，意思是"照着眼看走，没错位"；
        * **红**（``aligned=False``）—— 识别到的状态**不是**流程预期的那个。
          这就是"流程出错了、需要重定位"的那一刻：游标还停在 B，而画面已经是 C；
        * ``None`` —— 比不了（还没跑、认不出来、或者这个节点压根不校验状态）。

        用户点明过这个语义："红框 = 需要重定位，绿框 = 正常"。
        比原来那套（红=当前状态、绿=流程预期）清楚：那套得先在脑子里把两个颜色
        对应到两个来源，再自己判断它们是不是同一个 —— 而现在颜色**直接就是结论**。

        底色只有在"当前状态"（``title`` 与正在跟踪的那页同名时由调用方决定）上才变化，
        用来把注意力引到出问题的那一个节点上。

        :param aligned: ``True`` 一致 / ``False`` 不一致 / ``None`` 无法比较。
        """
        rect = QRectF(x, y, NODE_W, NODE_H)
        item = QGraphicsRectItem(rect)
        fill = COLOR_NODE_GROUP if group else COLOR_NODE
        if aligned is False:
            # 不一致：底色也变，让"出问题的是这一个"一眼看出来
            fill = COLOR_NODE_MISALIGNED
        item.setBrush(QBrush(fill))
        if aligned is True:
            border, width = COLOR_BORDER_OK, 2.4
        elif aligned is False:
            border, width = COLOR_BORDER_MISALIGNED, 2.4
        else:
            border, width = COLOR_BORDER, 1.2
        item.setPen(QPen(border, width))
        item.setZValue(1)
        self._scene.addItem(item)

        # 没有 sub 时把那一行居中，别让字贴着上边
        top = 5.0 if sub else (NODE_H - 16) / 2
        text = QGraphicsSimpleTextItem(_elide(title, 30))
        font = QFont()
        font.setPointSize(9)
        font.setBold(aligned is not None or group)
        text.setFont(font)
        text.setBrush(QBrush(COLOR_TEXT))
        text.setPos(rect.x() + 8, rect.y() + top)
        text.setZValue(2)
        self._scene.addItem(text)

        if sub:
            hint = QGraphicsSimpleTextItem(_elide(sub, 30))
            small = QFont()
            small.setPointSize(7)
            hint.setFont(small)
            hint.setBrush(QBrush(COLOR_TEXT_DIM))
            hint.setPos(rect.x() + 8, rect.y() + 25)
            hint.setZValue(2)
            self._scene.addItem(hint)
        return rect

    def _edge(
        self,
        src: QRectF,
        dst: QRectF,
        *,
        label: str = "",
        dashed: bool = False,
        active: bool = False,
    ) -> None:
        """画一条**直角**转移线，标签放在线上方并带底色。

        ## 三种走法

        * **往前**（目标在源右边）：``源右 → 中缝竖线 → 目标左``。
          标签放在中缝那段的上方；
        * **回边**（目标在源左边或同一列）：从**上方通道**绕过去 ——
          ``源右 → 上 → 通道横线 → 目标上``，箭头朝下进目标。
          这样回边不会横穿中间那些节点（以前是斜线穿过去，根本读不出来）；
        * **自环**（源就是目标）：在节点上方绕一个小方框。

        ## 标签为什么要有底色

        以前标签放在"两点中点再偏一点"，而两列之间只有 ``GAP_X`` 那么宽 ——
        长一点的说明直接压在下一个节点上，糊成一片。
        现在：中缝加宽、标签放在**线上方**、并且**铺一层底色**，
        和线重叠也读得清。
        """
        color = COLOR_ARROW_ACTIVE if active else COLOR_ARROW
        pen = QPen(color, 2.0 if active else 1.2)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

        def line(x1: float, y1: float, x2: float, y2: float, *, arrow: bool = False) -> None:
            self._scene.addLine(x1, y1, x2, y2, pen)
            if arrow:
                self._arrow_head(QPointF(x2, y2), QPointF(x1, y1), color)

        gap = dst.left() - src.right()
        if gap > 8:
            # 往前：中缝走直角
            mid_x = src.right() + gap / 2
            line(src.right(), src.center().y(), mid_x, src.center().y())
            if abs(src.center().y() - dst.center().y()) > 1:
                line(mid_x, src.center().y(), mid_x, dst.center().y())
            line(mid_x, dst.center().y(), dst.left(), dst.center().y(), arrow=True)
            # 标签走**下方**通道（不是上方、也不是横线正上方）：
            #
            # * 横线在节点垂直中间，紧挨着就是节点里的两行字，贴着看不清谁是谁；
            # * 上方留给**回边**（见下面那条分支）—— 否则回边的通道横线会和
            #   前瞻边的标签撞在同一高度上，字压在线上（踩过）。
            self._edge_label(
                label, active, mid_x + 6, max(src.bottom(), dst.bottom()) + 6
            )
            return

        # 回边 / 自环：走上方通道
        channel_y = min(src.top(), dst.top()) - max(20.0, NODE_H * 0.5)
        if src == dst:
            out_x = src.right() + 16  # 自环：右边出去、上面绕回来
            line(src.right(), src.center().y(), out_x, src.center().y())
            line(out_x, src.center().y(), out_x, channel_y)
            line(out_x, channel_y, src.center().x(), channel_y)
            line(src.center().x(), channel_y, src.center().x(), src.top(), arrow=True)
        else:
            out_x = src.right() + 16
            line(src.right(), src.center().y(), out_x, src.center().y())
            line(out_x, src.center().y(), out_x, channel_y)
            line(out_x, channel_y, dst.center().x(), channel_y)
            line(dst.center().x(), channel_y, dst.center().x(), dst.top(), arrow=True)
        self._edge_label(label, active, min(src.center().x(), dst.center().x()), channel_y - 20)

    def _edge_label(self, label: str, active: bool, x: float, y: float) -> None:
        """边上的说明文字 + 一层底色（否则和线重叠就读不出来）。

        ``QGraphicsSimpleTextItem.boundingRect()`` 是**相对它自己**的
        （左右各带一点留白、上边从 -1 左右开始）。所以底色框要拿它
        **放到场景之后**的范围（``sceneBoundingRect``）来算 ——
        直接用 boundingRect 当场景坐标的话，框会整体偏出去，
        图上看着像文字浮在一块错位的深色板上。
        """
        if not label:
            return
        item = QGraphicsSimpleTextItem(_elide(label, 44))
        font = QFont()
        font.setPointSize(7)
        item.setFont(font)
        item.setBrush(QBrush(COLOR_TEXT_DIM if not active else COLOR_BORDER_MISALIGNED))
        item.setPos(x, y)
        item.setZValue(4)
        self._scene.addItem(item)

        box = QGraphicsRectItem(item.sceneBoundingRect().adjusted(-2, -1, 2, 1))
        box.setBrush(QBrush(COLOR_BG))
        box.setPen(QPen(Qt.PenStyle.NoPen))
        box.setZValue(3)
        self._scene.addItem(box)

    def _arrow_head(self, tip: QPointF, from_: QPointF, color: QColor) -> None:
        """在 ``tip`` 画一个指向前进方向的小三角。"""
        size = 6.0
        dx, dy = tip.x() - from_.x(), tip.y() - from_.y()
        if dx == 0 and dy == 0:
            return
        if abs(dx) >= abs(dy):
            base = [
                QPointF(tip.x() - size, tip.y() - size / 1.8),
                QPointF(tip.x() - size, tip.y() + size / 1.8),
            ]
        else:
            base = [
                QPointF(tip.x() - size / 1.8, tip.y() - size),
                QPointF(tip.x() + size / 1.8, tip.y() - size),
            ]
        item = self._scene.addPolygon(
            QPolygonF([tip, *base]), QPen(color, 1.0), QBrush(color)
        )
        item.setZValue(2)

    def _tree_edges(self, parent: QRectF, children: list[QRectF]) -> None:
        """一棵子树的分组连线：**折线直角**，而且兄弟共用一条竖干线。

        ```
        父 ──┐
             ├── 子1
             ├── 子2
             └── 子3
        ```

        ## 为什么不用"每条边各画一条斜线"

        斜线（父右下角 → 子左上角）在**两个以上**子节点时会变成一把扇子：
        线互相交叉、看不出哪几条是兄弟，而且父子关系靠角度猜。
        实际上第一版就是那么画的（见 git 历史）。

        直角 + 共用干线是树状图的常规画法，好处是**结构一眼看出来**：
        同一条干线上的分支就是兄弟，进了干线再出来就是换了一层。

        ## 为什么"分组"画而不是"每条边"画

        干线要跨越"最上面那个子"到"最下面那个子"，这个区间只有拿到**一组兄弟**
        才知道。逐边画的话每条边只能画到自己那个孩子，拼不出共用的干线。

        :param parent: 父节点的矩形。
        :param children: 它的直接子节点矩形，**顺序即左边列的上下顺序**。
        """
        if not children:
            return
        pen = QPen(COLOR_ARROW, 1.2)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

        # 干线放在父右边到子左边之间的中线上 —— 不贴任何一边，看着才像树的枝
        bus_x = parent.right() + (children[0].left() - parent.right()) / 2

        def segment(x1: float, y1: float, x2: float, y2: float) -> None:
            self._scene.addLine(x1, y1, x2, y2, pen)

        # 父 -> 干线的横枝
        segment(parent.right(), parent.center().y(), bus_x, parent.center().y())

        if len(children) == 1:
            # 只有一个子：直接从父画一条横线过去，不需要竖干线
            # （画了会变成一个小台阶，反而像"这里有个分支"）
            child = children[0]
            segment(parent.right(), child.center().y(), child.left(), child.center().y())
            return

        # 竖干线 + 每个子的横枝
        segment(bus_x, children[0].center().y(), bus_x, children[-1].center().y())
        for child in children:
            segment(bus_x, child.center().y(), child.left(), child.center().y())

    def _empty(self, message: str) -> None:
        text = QGraphicsSimpleTextItem(message)
        text.setBrush(QBrush(COLOR_TEXT_DIM))
        text.setPos(10, 10)
        self._scene.addItem(text)

    # -- 重画时保住视角 ------------------------------------------------------ #
    def _redraw(self) -> Any:
        """清场景 -> 重画的上下文管理器，**保住用户调好的视角**。

        运行中每一轮都会重画（高亮当前状态），而重画会 ``_scene.clear()`` 再
        把节点全建一遍。这带来两个问题：

        1. 原来每次重画末尾都无条件调 :meth:`reset_view` —— 那会
           ``resetTransform()`` 把**用户刚放大的比例顶回去**。运行中每轮一次，
           所以"一放大就缩回去"。
        2. 清场景那一瞬间 ``sceneRect`` 变空，滚动范围跟着塌掉、再撑开，
           于是**平移量也会跳**（移到别处的视角会被拉回来）。

        这个上下文做两件事：清之前记下**视口中心对应的场景坐标**，
        画完恢复它；以及只在用户**没有自己调过**的时候才自动适配。

        用法：

            with self._redraw():
                self._scene.clear()
                ...画...

        ``reset_view()`` 只在块内或块外被明确调用时才生效 ——
        ``show_tree`` / ``show_graph`` 里那两处调用点已经改成走这里的判断。
        """
        from contextlib import contextmanager

        @contextmanager
        def _cm() -> Any:
            center = self.mapToScene(self.viewport().rect().center())
            self._rebuilding = True
            try:
                yield
            finally:
                self._rebuilding = False
                # 场景重建之后，把视角挪回原来那个场景坐标 ——
                # 换了内容也不跳（用户在看哪就还在哪）。
                # 空场景不恢复（centerOn 会把视图挪到 (0,0) 那种地方）。
                if not self._scene.itemsBoundingRect().isEmpty():
                    self.centerOn(center)

        return _cm()


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _alignment(
    *, node_id: str, current_page: str, current_node_page: str
) -> bool | None:
    """这个节点该画**绿框**（一致）还是**红框**（需要重定位）？

    * 它既不是"识别到的状态"也不是"流程预期的状态" —— ``None``（普通边框）；
    * 识别到的状态 == 流程预期的状态 —— ``True``（绿）：照着眼看走，没错位。
      这时只有那一个节点是绿的，别的都是普通边框；
    * 两者不同 —— ``False``（红）：**需要重定位**。这种时候会有两个节点红
      （"流程以为在哪" 和 "实际在哪"各一个），一眼就能看出错位是怎么发生的。

    ## 为什么单独一个函数

    这三分支的语义是这套设计的核心（"状态对不上就重定位"），
    而它原来散在调用处用 ``current=`` / ``matched=`` 两个布尔表达 ——
    读的人得先在脑子里把两个颜色对应到两个来源，再自己判断它们同不同。
    收成一个函数之后，**颜色直接就是结论**，而且它**能被单测**
    （见 ``tests/test_ui_diagram.py``）。

    :param node_id: 正在画的这个节点的 id。
    :param current_page: 状态层识别出来的当前状态（``""`` = 认不出来）。
    :param current_node_page: 当前流程节点声明的状态（``""`` = 这个节点不校验状态）。
    """
    if not current_page:
        return None
    consistent = current_page == current_node_page
    if consistent:
        return True if node_id == current_page else None
    # 不一致：预期的那个和实际的那个各标一个，错位的两头都看得见
    return False if node_id in (current_page, current_node_page) else None


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

        ## 重画不影响用户调好的视角

        运行中每轮都会调它（高亮当前状态），但**用户放大过的比例和拖动到的
        位置都保住**（见 :meth:`_redraw` 和 :meth:`reset_view`）。
        """
        with self._redraw():
            self._build_tree(tree, current_page, current_node_page, overlay_pages)

    def _build_tree(
        self,
        tree: Any,
        current_page: str,
        current_node_page: str,
        overlay_pages: tuple[str, ...],
    ) -> None:
        """真正画的那部分（由 :meth:`show_tree` 包在 ``_redraw`` 里调）。"""
        self._scene.clear()
        if tree is None or len(tree) == 0:
            self._empty("（没有状态树：先选一个脚本）")
            return

        layout: dict[str, QRectF] = {}
        cursor_y: list[float] = [0.0]

        def place(node: Any, depth: int) -> QRectF:
            """先给**整棵子树**排好位，返回本节点的矩形。

            **先递归、后画线**是必须的：兄弟共用一条竖干线，而干线的范围取决于
            所有子节点的位置 —— 所以得先把子节点都排完，才知道线该画多长。
            """
            while len(cursor_y) <= depth:
                cursor_y.append(0.0)
            x = depth * (NODE_W + GAP_X)
            y = cursor_y[depth]
            cursor_y[depth] = y + NODE_H + GAP_Y

            # **只显示 name 和 id** —— name 给人看，id 给写代码/配置时对。
            # name 没写就退回 id，不留空行；两者相同时不重复写。
            title = node.name or node.id
            sub = node.id if node.name and node.name != node.id else ""
            rect = self._node(
                x,
                y,
                title,
                sub,
                aligned=_alignment(
                    node_id=node.id,
                    current_page=current_page,
                    current_node_page=current_node_page,
                ),
                group=node.is_group,
            )
            layout[node.id] = rect

            # ``children_of`` 返回的是**节点对象**，不是 id。
            # 早先这里写成 ``for child_id in ...: tree.get(child_id)`` ——
            # get 拿到一个对象、查不到、返回 None，于是整棵子树**静默地**没画出来。
            # 那种"拿错类型 → None → 静默跳过"最难看出来，所以这里直接用对象。
            children = [place(child, depth + 1) for child in tree.children_of(node.id)]
            self._tree_edges(rect, children)
            return rect

        for root_id in tree.roots:
            root = tree.get(root_id)
            if root is not None:
                place(root, 0)

        self.reset_view()

    #: 兼容"只给一个当前状态"的简单调用
    def show_state(self, tree: Any, current: str) -> None:
        self.show_tree(tree, current_page=current)


class FlowDiagramView(_Diagram):
    """流程图的图：节点框 + 带箭头的边，**当前节点描红**。"""

    def show_graph(
        self, graph: Any, *, current: str = "", bindings: Any = None
    ) -> None:
        """重画整张图。**和 :meth:`StateTreeView.show_tree` 一样保住视角。**

        运行中每轮都会调它（高亮当前节点），所以用户放大过的比例和拖动到的
        位置都必须留住 —— 否则"一放大就缩回去"。
        """
        with self._redraw():
            self._build_graph(graph, current, bindings)

    def _build_graph(self, graph: Any, current: str, bindings: Any) -> None:
        """真正画的那部分（由 :meth:`show_graph` 包在 ``_redraw`` 里调）。"""
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
            x = level * (NODE_W + GAP_X)
            y = cursor_y.get(level, 0.0)
            cursor_y[level] = y + NODE_H + GAP_Y
            # 流程图节点：第一行是**节点 id**（流程图的身份），
            # 第二行是它认领的状态 —— 来自**关联表**，不是节点自己
            # （节点不知道自己是哪个状态，那是独立的一层数据）。
            state = bindings.state_of(node_id) if bindings is not None else None
            page_label = state or "不关联状态"
            # 流程图里"当前节点"就是正常状态 -> 绿框（不是红：红留给"需要重定位"）
            layout[node_id] = self._node(
                x,
                y,
                node_id,
                _elide(page_label, 30),
                aligned=True if node_id == current else None,
            )

        for edge in graph.edges:
            src, dst = layout.get(edge.source), layout.get(edge.target)
            if src is None or dst is None:
                continue
            label = edge.label or ("无条件" if not edge.has_condition else "条件")
            self._edge(
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
        """换一个脚本（或清空）。

        **换场景时强制重新适配视角**：新图的结构和上一个没关系，
        继承上一个的放大比例只会让人莫名其妙。而运行中的每轮
        :meth:`refresh` **不会**强制 —— 那正是"用户调好的视角要留住"的地方。
        """
        self._scenario = scenario
        self.refresh()
        if scenario is not None:
            self._tree_view.reset_view(force=True)
            self._graph_view.reset_view(force=True)

    def refresh(
        self,
        *,
        current_page: str = "",
        current_node: str = "",
        current_node_page: str = "",
        overlays: tuple[str, ...] = (),
    ) -> None:
        """按当前运行状态重画。**运行中每轮都会调**（几毫秒，可以承受）。

        ## 它**不**动视角

        高亮"当前在哪一格"是每轮都变的，但用户放大/拖动出来的视角是他自己
        调的。重画保比例、保位置（见 ``_Diagram._redraw``），
        所以脚本跑着的时候也能安心放大看细节。
        """
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
        self._graph_view.show_graph(
            scenario.graph, current=current_node, bindings=scenario.bindings
        )
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
            state = scenario.bindings.state_of(current_node)
            lines.append(f"  关联  {state or '（不关联状态）'}")
            lines.append(f"  步骤  {len(node.steps)} 个 / 出边 {edges} 条")
    return "\n".join(lines)
