"""关联表 —— **状态末梢 ↔ 流程节点** 的 id 双向映射。

## 它是独立的第三个产物

这套架构有三个东西，各自一个文件：

| | 是什么 | 表达 |
|---|---|---|
| **状态树** | 我现在在哪（靠画面认） | `PageTree` |
| **流程图** | 该做什么（理想执行顺序） | `Graph` |
| **关联表** | 两者怎么对上 | 本模块 |

**关键：关联不写在任何一边。** 以前它隐含在 ``Node.page`` 字段里 ——
那是"流程图顺手带了状态信息"，两边的边界就模糊了；而且同一个事实只有一个
物理位置，想单独看"这张表"就得把流程图翻一遍。

独立之后，"谁对应谁"是**一处、一张表、能一眼看完**的东西。

## 三条不变式

1. **流程节点不一定有状态** —— 不写的节点就是"纯逻辑/纯等待"，
   不参与自检、也不参与重定位；
2. **状态末梢一定有流程节点** —— 否则重定位到它之后无处可去。
   由 :meth:`NodeBindings.validate` 在装配期强制（分类节点和叠加层除外：
   它们不出现在定位结果里）；
3. **一个流程节点至多映射一个状态** —— 因为"进入该节点后跑哪个状态的定位代码"
   必须唯一。

   反过来**允许多个节点映射同一状态**（同一状态在不同阶段做不同的事）。
   那时 :meth:`NodeBindings.state_to_node` 给出的是**主节点**，
   由 :attr:`Binding.priority` 决定（并列取先声明的）。

## 一个比喻

对照状态机：``Node`` 是状态，``Transition`` 是回调，而**这张表是"当前状态
的持久化记录"** —— 进入某个节点时把当前状态置成它映射的那个，
然后跑那个状态的定位代码，对不上就是出意外了、需要重定位。

## 业务层怎么写

```python
# games/<游戏>/<功能>/bindings.py
from gamebot.flow import Binding

BINDINGS = (
    Binding("home", "home/lobby"),
    Binding("jingji/before_create", "home/jingji/before_create"),
)
```
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..exceptions import ConfigError
from ..state.page import PageId, PageKind, PageTree

__all__ = ["Binding", "NodeBindings"]


@dataclass(frozen=True, slots=True)
class Binding:
    """一条关联：**进入这个流程节点时，当前状态就是它**。

    :param node: 流程节点 id。
    :param state: 状态末梢 id。
    :param priority: 多个节点映射同一状态时谁是主节点（大的赢，并列取先声明的）。
        只在"多对一"时有意义；一对一的话随便。
    """

    node: str
    state: PageId
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.node or not self.node.strip():
            raise ConfigError("Binding 的 node 不能为空")
        if not self.state or not self.state.strip():
            raise ConfigError(f"Binding({self.node!r}) 的 state 不能为空")


@dataclass(frozen=True, slots=True)
class NodeBindings:
    """关联表：id 双向映射，**独立于状态树和流程图**。

    构造期可变、运行期只读 —— 和 ``PageTree`` / ``Graph`` 一样，
    装配阶段定好之后没人改它。

    :param pairs: 关联。重复的 ``node`` 会报错（一个节点只能映射一个状态）。
    """

    pairs: tuple[Binding, ...] = ()
    #: ``node -> state``。一个节点至多一个状态。
    _to_state: Mapping[str, PageId] = field(default_factory=dict, repr=False)
    #: ``state -> 主节点 id``（多对一时由 priority 定）。
    _to_node: Mapping[PageId, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        to_state: dict[str, PageId] = {}
        for pair in self.pairs:
            if pair.node in to_state:
                raise ConfigError(
                    f"节点 {pair.node!r} 关联了两个状态："
                    f"{to_state[pair.node]!r} 和 {pair.state!r} —— "
                    "一个节点至多映射一个状态（不然进入它之后不知道该跑哪个状态的定位代码）"
                )
            to_state[pair.node] = pair.state

        # 多对一：主节点由 priority 定，并列时取先声明的（保持可预期）
        best: dict[PageId, Binding] = {}
        for pair in self.pairs:
            current = best.get(pair.state)
            if current is None or pair.priority > current.priority:
                best[pair.state] = pair
        object.__setattr__(self, "_to_state", to_state)
        object.__setattr__(self, "_to_node", {s: b.node for s, b in best.items()})

    # ------------------------------------------------------------------ #
    # 双向查
    # ------------------------------------------------------------------ #
    def state_of(self, node_id: str | None) -> PageId | None:
        """这个流程节点对应哪个状态；没有就是 ``None``（= 不参与自检）。"""
        if not node_id:
            return None
        return self._to_state.get(node_id)

    def node_for(self, state_id: PageId | None) -> str | None:
        """认领这个状态的**主**节点 id；没有就是 ``None``。

        重定位用它：状态层报出真实锚点之后，靠这一句决定落到哪个节点。
        """
        if not state_id:
            return None
        return self._to_node.get(state_id)

    def nodes_for(self, state_id: PageId | None) -> tuple[str, ...]:
        """所有认领这个状态的节点 id（按 ``priority`` 降序）。"""
        if not state_id:
            return ()
        matched = [p for p in self.pairs if p.state == state_id]
        return tuple(b.node for b in sorted(matched, key=lambda b: -b.priority))

    def is_bound(self, node_id: str | None) -> bool:
        return bool(node_id) and node_id in self._to_state

    # ------------------------------------------------------------------ #
    # 校验（装配期）
    # ------------------------------------------------------------------ #
    def validate(self, tree: PageTree | None, graph: Any = None) -> None:
        """把引用错误挡在启动阶段。

        1. 每个节点关联的状态必须在状态树里（写错一个字母，那条流程就永远
           不执行 —— 而且不报错，只是"什么也没发生"）；
        2. 关联里的节点必须在流程图里；
        3. **每个记录信息的状态都必须有节点认领**。这是用户定的不变式：
           重定位到它之后必须有个地方可去。``GROUP`` 分类节点不算（它自己
           不匹配，定位结果里永远不会出现它）；叠加层也不算（它盖在主状态
           之上，由主状态的节点负责）。

        :raises ConfigError: 校验失败，message 里带上全部问题。
        """
        problems: list[str] = []

        if tree is not None:
            for pair in self.pairs:
                if pair.state not in tree:
                    problems.append(
                        f"节点 {pair.node!r} 关联的状态 {pair.state!r} 不在状态树里"
                    )

        if graph is not None:
            for pair in self.pairs:
                if graph.node(pair.node) is None:
                    problems.append(
                        f"关联表里的节点 {pair.node!r} 不在流程图里"
                    )

        if tree is not None:
            claimed = set(self._to_state.values())
            for page in tree.walk():
                # 分类节点不出现在定位结果里 —— 不需要认领；
                # 叠加层盖在主状态之上，由主状态的节点负责。
                if page.kind is PageKind.GROUP or page.is_overlay:
                    continue
                if page.id not in claimed:
                    problems.append(
                        f"状态 {page.id!r} 没有任何流程节点认领 —— "
                        "重定位到它之后无处可去。给它加一条关联，"
                        "或把它标成 kind: group"
                    )

        if problems:
            raise ConfigError("关联表校验失败:\n  - " + "\n  - ".join(problems))

    # ------------------------------------------------------------------ #
    # 描述
    # ------------------------------------------------------------------ #
    def table(self) -> dict[str, PageId]:
        """``节点 -> 状态``。给 ``gamebot check`` 和日志看。"""
        return dict(sorted(self._to_state.items()))

    def state_to_node(self) -> dict[PageId, str]:
        """``状态 -> 主节点``。"""
        return dict(sorted(self._to_node.items()))

    def unbound_nodes(self, graph: Any = None) -> tuple[str, ...]:
        """不关联任何状态的流程节点（纯逻辑/纯等待）。

        给了 ``graph`` 就按流程图算（含"流程里有但表里没提"的节点）；
        没给就只能看表。
        """
        if graph is None:
            return ()
        return tuple(sorted(n for n in graph.nodes if n not in self._to_state))

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_to_state": self.table(),
            "state_to_node": self.state_to_node(),
        }

    def __len__(self) -> int:
        return len(self._to_state)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._to_state

    def __repr__(self) -> str:
        return f"NodeBindings({len(self._to_state)} 条关联)"

    # ------------------------------------------------------------------ #
    @classmethod
    def of(cls, pairs: Iterable[tuple[str, PageId]]) -> NodeBindings:
        """简写：``NodeBindings.of([("home", "home/lobby")])``。"""
        return cls(pairs=tuple(Binding(n, s) for n, s in pairs))
