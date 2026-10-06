"""状态树的节点配色：**绿 = 一致，红 = 需要重定位**。

## 这一组在钉什么

这套设计的核心是"状态对不上就重定位"。图上的颜色就是那句话的可视化：

* **绿框** —— 识别到的状态**就是**流程预期的那个（一切正常）；
* **红框** —— 两者不同，**需要重定位**。这种时候有**两个**节点是红的：
  "流程以为在哪"和"实际在哪"各一个 —— 错位的两头都看得见，
  这样就不用去猜"它是从哪儿跳过来的"。

颜色错了不会崩，只会让人**看错运行状态** —— 那比崩了更费时间。
所以这条规则单独测，而不是只靠肉眼看图。
"""

from __future__ import annotations

import pytest

from gamebot.ui.panels.diagram import _alignment


class TestAlignment:
    """``_alignment`` 的三分支：``None`` 不比 / ``True`` 一致 / ``False`` 错位。"""

    def test_nothing_tracked_yet(self):
        """还没跑（认不出任何状态）—— 谁都别标，图上不该有误导性的颜色。"""
        assert _alignment(node_id="home", current_page="", current_node_page="") is None

    def test_recognised_state_is_green(self):
        """一致时：**只有那一个**节点是绿的。"""
        assert (
            _alignment(
                node_id="home/jingji",
                current_page="home/jingji",
                current_node_page="home/jingji",
            )
            is True
        )

    def test_other_states_are_plain_when_consistent(self):
        """一致时别的节点保持普通边框 —— 绿框要能指认出"就是这一个"。"""
        for other in ("home", "home/lobby", "network_error"):
            assert (
                _alignment(
                    node_id=other,
                    current_page="home/jingji",
                    current_node_page="home/jingji",
                )
                is None
            )

    def test_misaligned_marks_both_ends(self):
        """**不一致时两头都标红** —— 这是"怎么跳过去的"唯一的图上线索。

        场景：流程以为在 ``home/lobby``（游标停在那儿），
        而画面已经是 ``home/jingji``（状态层认出来的）。
        两个节点都得红，否则只看到"实际在哪"、看不到"从哪来"。
        """
        kwargs = {"current_page": "home/jingji", "current_node_page": "home/lobby"}
        assert _alignment(node_id="home/jingji", **kwargs) is False, "实际所在的没标红"
        assert _alignment(node_id="home/lobby", **kwargs) is False, "流程预期的没标红"

    def test_misaligned_leaves_unrelated_nodes_plain(self):
        kwargs = {"current_page": "home/jingji", "current_node_page": "home/lobby"}
        for other in ("home", "network_error"):
            assert _alignment(node_id=other, **kwargs) is None

    def test_node_that_checks_nothing_is_never_green(self):
        """节点没声明 ``page``（不校验状态）时不该绿 —— 它没有"预期"可比。

        报出来的是"不一致"（红），因为识别到的状态确实不是"没有预期"。
        """
        assert (
            _alignment(node_id="home", current_page="home", current_node_page="") is False
        )
        assert (
            _alignment(node_id="elsewhere", current_page="home", current_node_page="")
            is None
        )

    @pytest.mark.parametrize("node_id", ["home", ""])
    def test_unknown_page_is_not_marked(self, node_id):
        """认不出来（``current_page`` 空）时全图无颜色 —— 别乱指。"""
        assert _alignment(node_id=node_id, current_page="", current_node_page="home") is None
