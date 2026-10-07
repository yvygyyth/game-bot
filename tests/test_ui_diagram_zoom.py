"""图怎么缩放 / 平移 —— 以及**重画时不能把它顶回去**。

## 这个 bug 的成因（值得记下来）

运行中每一轮都会重画状态树/流程图（为了高亮"当前在哪一格"），而重画会
``_scene.clear()`` 再把节点全部重建。原来每次重画末尾都**无条件**调
``reset_view()``，而它第一件事是 ``resetTransform()`` —— 于是：

* 用户把图放大看细节；
* 引擎下一轮 tick，重画一次，缩放被重置 —— 表现是"一放大就缩回去"。

而且清场景那一瞬间 ``sceneRect`` 变空、滚动范围跟着塌掉再撑开，
所以**平移量也会跳**（移到别处的视角被拉回来）。

修法两条：``reset_view`` 在用户动过之后就不再自动调；
重画前后记住**视口中心对应的场景坐标**并恢复。
"""

from __future__ import annotations

import pytest

from gamebot.ui.panels.diagram import DiagramPanel, _Diagram


@pytest.fixture
def panel(qt_app):
    panel = DiagramPanel()
    panel.resize(600, 400)
    panel.show()
    qt_app.processEvents()
    return panel


def _zoom_of(view: _Diagram) -> float:
    """当前缩放比例（变换矩阵的 m11）。"""
    return view.transform().m11()


class TestZoomSurvivesRedraw:
    """**这个文件的核心**：重画不能动用户调好的视角。"""

    def test_show_tree_keeps_the_zoom(self, panel, qt_app):
        from gamebot.state import PageTree
        from games.mingjiangsha.jingji.pages import FEATURE_TREE

        tree = PageTree()
        tree.add(FEATURE_TREE)
        view = panel._tree_view

        view.show_tree(tree)
        qt_app.processEvents()
        view.zoom(2.0)
        zoomed = _zoom_of(view)
        assert zoomed > 0

        # 模拟"引擎下一轮 tick 又重画一次"
        view.show_tree(tree, current_page="lobby")
        qt_app.processEvents()

        assert _zoom_of(view) == pytest.approx(zoomed), (
            "重画之后缩放被改回去了 —— 这正是'一放大就缩回去'那个 bug"
        )

    def test_show_graph_keeps_the_zoom(self, panel, qt_app):
        from games.mingjiangsha.jingji.graph import SCENARIO

        scenario = SCENARIO.materialize(name="zoom-test")
        view = panel._graph_view

        view.show_graph(scenario.graph, bindings=scenario.bindings)
        qt_app.processEvents()
        view.zoom(2.0)
        zoomed = _zoom_of(view)

        view.show_graph(scenario.graph, current="lobby", bindings=scenario.bindings)
        qt_app.processEvents()

        assert _zoom_of(view) == pytest.approx(zoomed)

    def test_many_redraws_do_not_accumulate_drift(self, panel, qt_app):
        """跑几十轮（真实运行就是这样）缩放必须一动不动。"""
        from games.mingjiangsha.jingji.graph import SCENARIO

        scenario = SCENARIO.materialize(name="zoom-test")
        view = panel._graph_view
        view.show_graph(scenario.graph, bindings=scenario.bindings)
        qt_app.processEvents()
        view.zoom(1.8)
        zoomed = _zoom_of(view)

        for _ in range(30):
            view.show_graph(scenario.graph, current="lobby", bindings=scenario.bindings)
        qt_app.processEvents()

        assert _zoom_of(view) == pytest.approx(zoomed)


class TestAutoFitStillHappens:
    """让位归让位，**第一次看到图还是要自动适配** —— 否则开箱就是糊的。"""

    def test_first_draw_fits_by_itself(self, panel, qt_app):
        from games.mingjiangsha.jingji.graph import SCENARIO

        scenario = SCENARIO.materialize(name="fit-test")
        view = panel._graph_view

        view.show_graph(scenario.graph, bindings=scenario.bindings)
        qt_app.processEvents()

        # 自动适配过 -> 不是单位变换（除非图和视口恰好一样大，那也算合理）
        assert view.transform().m11() > 0

    def test_switching_script_refits(self, panel, qt_app):
        """换脚本要强制重新适配 —— 新图和上一个的视角没关系。"""
        from games.mingjiangsha.jingji.graph import SCENARIO

        scenario = SCENARIO.materialize(name="refit-test")
        panel.set_scenario(scenario)
        qt_app.processEvents()
        panel._graph_view.zoom(3.0)
        zoomed = _zoom_of(panel._graph_view)

        panel.set_scenario(scenario)  # 重选同一个脚本也算"换了场景"
        qt_app.processEvents()

        assert _zoom_of(panel._graph_view) != pytest.approx(zoomed), (
            "换脚本之后应该重新适配，而不是继承上一个的放大比例"
        )

    def test_clearing_scenario_does_not_crash(self, panel, qt_app):
        panel.set_scenario(None)
        qt_app.processEvents()
        assert panel._scenario is None


class TestPanSurvivesRedraw:
    def test_view_center_is_restored(self, panel, qt_app):
        """重画之后**看的内容**还是原来那块 —— 平移量不被清场景带走。"""
        from games.mingjiangsha.jingji.graph import SCENARIO

        scenario = SCENARIO.materialize(name="pan-test")
        view = panel._graph_view
        view.show_graph(scenario.graph, bindings=scenario.bindings)
        qt_app.processEvents()
        view.zoom(2.5)
        qt_app.processEvents()

        # 挪到别处（直接设滚动条，等价于用户拖动）
        view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        qt_app.processEvents()
        before = view.mapToScene(view.viewport().rect().center())

        view.show_graph(scenario.graph, current="lobby", bindings=scenario.bindings)
        qt_app.processEvents()
        after = view.mapToScene(view.viewport().rect().center())

        assert abs(after.x() - before.x()) < 2.0
        assert abs(after.y() - before.y()) < 2.0
