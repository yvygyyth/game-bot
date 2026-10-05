"""状态 ↔ 流程节点的关联 —— 两个层之间**唯一**的桥。

## 它解决什么

流程层和状态层必须解耦，但有三件事天然需要"某个状态"和"某个流程节点"对上号：

1. **重定位之后去哪**：状态层说"真实在 ``home/jingji``"，流程图得回答"那归谁管"；
2. **动手之前校验**：节点说"我要在 ``home/jingji`` 上点这个按钮"，得先确认真在那儿；
3. **动完手之后我在哪**：节点跑完，当前"预期状态"要跟着变。

三件事都收在这一个对象上。于是两侧各自的纪律变得很好守：

* 状态层**不认识**"节点 / 边 / 去哪"，只回答"这一帧像谁"；
* 流程层**不认识**"状态树 / 优先级 / ROI"，只认一个不透明的锚点字符串；
* 唯一把两者放在一起的代码就是本模块，而它是**启动期算出来的纯数据**。

## 一个方向是"一定"，另一个方向是"最多一个"

用户定的不变式（这句话是整个设计的支点）::

    流程节点  不一定  需要一个状态        （纯等待 / 纯逻辑的节点）
    状态      一定    需要一个流程节点    （否则重定位到它就无处可去）

前半句让"流程图只写正常流程"成为可能：不写 ``page`` 的节点就是不参与状态校验的节点。
后半句是重定位能落地的前提 —— 状态跳到哪个节点必须是**确定**的，
所以同一个状态被多个节点认领时，必须能选出一个主节点（``priority`` 最大者）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..exceptions import ConfigError
from ..utils.logging import get_logger
from .graph import Node

if TYPE_CHECKING:
    from ..state.page import PageId, PageTree

log = get_logger("flow.binding")

__all__ = ["StateBinding", "validate_binding"]


def validate_binding(graph: Any, tree: Any) -> None:
    """装配期校验"状态 ↔ 节点"的引用，**不需要**构造 :class:`StateBinding`。

    单独放一个函数（而不是只做 :meth:`StateBinding.validate`）是为了让
    ``Scenario.validate()`` 能直接调它 —— 那边只需要"校验"，不需要查表；
    而查表对象是运行期的东西，装配期造一个出来纯属多余。

    :raises ConfigError: 校验失败，message 里带上全部问题。
    """
    from ..state.page import PageKind

    problems: list[str] = []
    bound: set[str] = set()
    for node in graph.nodes.values():
        if not node.page:
            continue
        bound.add(node.page)
        if node.page not in tree:
            problems.append(f"节点 {node.id!r} 声明的状态 {node.page!r} 不在状态树里")

    for page in tree.walk():
        # 分类节点自己不参与匹配，定位结果里永远不会出现它 —— 不需要认领；
        # 叠加层是"盖在某一页上的一层"，由主状态的节点负责。
        if page.kind is PageKind.GROUP or page.is_overlay:
            continue
        if page.id not in bound:
            problems.append(
                f"状态 {page.id!r} 没有任何流程节点认领 —— 重定位到它之后无处可去。"
                "给它加一个节点并写上 page，或把它标成 kind: group"
            )

    if problems:
        raise ConfigError("状态-流程关联校验失败:\n  - " + "\n  - ".join(problems))


class StateBinding:
    """状态 -> 主节点 / 节点 -> 状态 的双向查表。

    **构造期可变、运行期只读**：和 ``PageTree`` / ``Graph`` 一样，装配阶段定好，
    跑起来之后没人改它。这样它可以被多个运行共享，也能安全地序列化对比。

    :param graph: 流程图（提供节点和它们的 ``page``）。
    :param tree: 状态树。给了就能校验"绑定的状态真的存在"；
        ``None`` 时跳过那项检查（单测里常这么用）。
    """

    __slots__ = ("_bound", "_by_page", "_graph", "_tree")

    def __init__(self, graph: Any, tree: PageTree | None = None) -> None:
        self._graph = graph
        self._tree = tree
        self._bound: dict[str, list[Node]] = {}
        self._by_page: dict[str, Node] = {}
        for node in graph.nodes.values():
            if not node.page:
                continue
            self._bound.setdefault(node.page, []).append(node)
        for page_id, nodes in self._bound.items():
            # 主节点 = priority 最大的那个；并列时取先声明的（保持可预期）。
            # 刻意**不**报"重复绑定"的错：一个状态多个节点是合法设计
            # （"第一次进领奖，之后直接开打"），用优先级区分就够了。
            self._by_page[page_id] = max(nodes, key=lambda n: n.priority)

    # ------------------------------------------------------------------ #
    # 状态 -> 流程
    # ------------------------------------------------------------------ #
    def node_for(self, page_id: PageId | None) -> Node | None:
        """认领这个状态的**主**节点；没有就是 ``None``。

        重定位用它：状态层报出真实锚点之后，流程层靠这一句决定落到哪个节点。
        """
        if not page_id:
            return None
        return self._by_page.get(page_id)

    def nodes_for(self, page_id: PageId | None) -> tuple[Node, ...]:
        """所有认领这个状态的节点（按 ``priority`` 降序）。"""
        if not page_id:
            return ()
        return tuple(sorted(self._bound.get(page_id, []), key=lambda n: -n.priority))

    def is_bound(self, page_id: PageId | None) -> bool:
        return bool(page_id) and page_id in self._by_page

    # ------------------------------------------------------------------ #
    # 流程 -> 状态
    # ------------------------------------------------------------------ #
    def state_of(self, node: Node | str | None) -> PageId | None:
        """这个节点**声明**的状态；没声明就是 ``None``（= 不校验）。

        接受节点对象或节点 id，省得调用方到处写 ``graph.node(...)``。
        """
        target = self._resolve(node)
        return target.page if target is not None and target.page else None

    def expects(self, node: Node | str | None) -> PageId | None:
        """:meth:`state_of` 的别名，读起来更贴合调用点的语气。

        ``tick()`` 里是这么用的::

            expected = self.binding.expects(self.cursor.current)
        """
        return self.state_of(node)

    def check(self, node: Node | str | None, actual: PageId | None) -> tuple[bool, str]:
        """动手前的校验：节点声明的状态和实测对得上吗。

        :return: ``(通过?, 说明)``。**没声明状态的节点永远通过** ——
            那正是"流程图只写正常流程"的实现方式：不写就不校验。
        """
        target = self._resolve(node)
        if target is None:
            return False, f"节点不存在: {node!r}"

        declared = target.page
        if not declared:
            return True, "节点不绑定状态"
        if actual is None:
            return False, f"节点 {target.id!r} 期望状态 {declared!r}，但当前认不出来"
        if declared == actual:
            return True, "状态正确"

        # 叠加层也算"在这一页上"：战斗页弹网络错误时，节点声明 battle 仍然成立。
        # 这不是放水 —— 弹窗会由边条件（on_page/within_page）表达成显式转移，
        # 而"主状态没变"这件事本身是真的。
        return False, f"节点 {target.id!r} 期望状态 {declared!r}，实测是 {actual!r}"

    # ------------------------------------------------------------------ #
    # 校验（装配期）
    # ------------------------------------------------------------------ #
    def validate(self, *, require_state_node: bool = True) -> None:
        """把"三件事"里的引用错误挡在启动阶段。

        检查项：

        1. 每个节点声明的状态都必须在状态树里存在（写错一个字母，那条流程
           就永远不执行 —— 而且不报错，只是"什么也没发生"）；
        2. ``require_state_node`` 为真时，**每个记录信息的状态都必须有
           节点认领**。这是用户定的不变式：重定位到它之后必须有个地方可去。
           ``GROUP`` 分类节点不算 —— 它自己不做匹配，定位结果里永远不会出现它；
           叠加层也不算 —— 它盖在主状态之上，由主状态的节点负责。

        :raises ConfigError: 校验失败，message 里带上全部问题。
        """
        if self._tree is None:
            # 没给状态树就只能查"节点 -> 状态"那半边
            problems = [
                f"节点 {node.id!r} 声明了状态但没提供状态树，无法校验"
                for node in self._graph.nodes.values()
                if node.page
            ]
            if problems:
                raise ConfigError("状态-流程关联校验失败:\n  - " + "\n  - ".join(problems))
            return
        validate_binding(self._graph, self._tree)

    # ------------------------------------------------------------------ #
    # 描述
    # ------------------------------------------------------------------ #
    def table(self) -> dict[str, str]:
        """状态 -> 主节点 id。给 ``gamebot check`` 和日志看。"""
        return {page_id: node.id for page_id, node in sorted(self._by_page.items())}

    def unbound_nodes(self) -> tuple[str, ...]:
        """不绑定任何状态的节点（流程层的"纯逻辑/纯等待"节点）。"""
        return tuple(
            sorted(n.id for n in self._graph.nodes.values() if not n.page)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_to_node": self.table(),
            "node_to_state": {
                n.id: n.page for n in self._graph.nodes.values() if n.page
            },
            "unbound_nodes": list(self.unbound_nodes()),
        }

    def _resolve(self, node: Node | str | None) -> Node | None:
        if node is None:
            return None
        if isinstance(node, Node):
            return node
        return self._graph.node(node)

    def __len__(self) -> int:
        return len(self._by_page)

    def __contains__(self, page_id: object) -> bool:
        return page_id in self._by_page

    def __repr__(self) -> str:
        return (
            f"StateBinding({len(self._by_page)} 个状态, "
            f"{len(self._graph.nodes)} 个节点, "
            f"{len(self.unbound_nodes())} 个节点不绑定状态)"
        )
