"""关联表的**运行期查表** —— 薄薄一层，数据全在 :mod:gamebot.flow.bindings。

## 为什么这里没有校验了

校验（引用对不对、状态有没有人认领）在
`NodeBindings.validate()` —— 那是**装配期**的事，
和运行期查表是两件事。以前两者都挤在这个文件里，于是构造一个查表对象
和校验一份声明变成了同一个入口，装配期还得凭空造一个查表对象出来。

## 自检不是这里的事

节点期望的状态和实测对不上这件事**没有单独的机制**了：

* 进入流程节点 -> 关联表**更新当前状态**；
* 然后跑那个状态的**定位代码**；
* 对上了就继续，对不上就重定位（拿实测锚点反查关联表）。

自检和定位是同一个动作，不是两套东西。见 `flow/engine.py` 的 `tick`。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..state.page import PageId
from .bindings import NodeBindings

if TYPE_CHECKING:
    from .graph import Graph

__all__ = ["StateBinding"]


class StateBinding:
    """状态 -> 主节点 / 节点 -> 状态 的双向查表。

    **就是 `NodeBindings` 的一层包装** —— 留着这个类是为了给引擎一个
    只读视图的入口（引擎不该去改关联表），并且把 `Graph` 一起拿着
    方便按节点取信息。

    :param bindings: 关联表。
    :param graph: 流程图。给了才能校验关联里的节点真的存在。
    """

    __slots__ = ("_bindings", "_graph")

    def __init__(self, bindings: NodeBindings, graph: Graph | None = None) -> None:
        self._bindings = bindings
        self._graph = graph

    @property
    def bindings(self) -> NodeBindings:
        return self._bindings

    # ------------------------------------------------------------------ #
    # 状态 -> 流程
    # ------------------------------------------------------------------ #
    def node_for(self, state_id: PageId | None) -> str | None:
        """认领这个状态的**主**节点 id；没有就是 `None`。

        重定位用它：状态层报出真实锚点之后，靠这一句决定落到哪个节点。
        """
        return self._bindings.node_for(state_id)

    def nodes_for(self, state_id: PageId | None) -> tuple[str, ...]:
        """所有认领这个状态的节点 id（按 priority 降序）。"""
        return self._bindings.nodes_for(state_id)

    def is_bound(self, node_id: str | None) -> bool:
        return self._bindings.is_bound(node_id)

    # ------------------------------------------------------------------ #
    # 流程 -> 状态
    # ------------------------------------------------------------------ #
    def state_of(self, node_id: str | None) -> PageId | None:
        """这个节点对应哪个状态；没有就是 `None`（= 不参与自检/重定位）。"""
        return self._bindings.state_of(node_id)

    def expects(self, node_id: str | None) -> PageId | None:
        """:meth:state_of 的别名，读起来更贴合调用点的语气。"""
        return self.state_of(node_id)

    # ------------------------------------------------------------------ #
    # 描述
    # ------------------------------------------------------------------ #
    def table(self) -> dict[str, PageId]:
        return self._bindings.table()

    def unbound_nodes(self) -> tuple[str, ...]:
        return self._bindings.unbound_nodes(self._graph)

    def to_dict(self) -> dict[str, Any]:
        return self._bindings.to_dict()

    def __len__(self) -> int:
        return len(self._bindings)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._bindings

    def __repr__(self) -> str:
        return f"StateBinding({len(self._bindings)} 条关联)"
