"""流程层的流程图 —— "接下来做什么、什么条件下换目标"。

## 和状态树的分工（这是整个设计的核心）

| | 回答什么 | 表达什么 | 文件 |
|---|---|---|---|
| **状态树** | 我现在**在哪** | 空间 / 结构 / 怎么认出来 | ``state/page.py`` |
| **流程图** | 接下来**做什么** | 时间 / 控制流 / 何时换目标 | 本文件 |

两者**不能互相替代**：

* 树表达不了"结算页面 → 回首页重来"这种跨分支跳转（树里没有这条边）；
* 图表达不了"战斗的所有子状态只看右下角技能栏就能区分"（图层级剪枝 + ROI 继承）。

结合的接口只有一个：:attr:`Node.page` —— 节点声明"我打算在哪个页面上执行"。
三种结合模式见 ``docs/state-and-flow.md``，推荐的是模式 1：
**实际页面 ≠ 期望页面时就不执行动作**，这是防止"在错误页面上乱点"的第一道闸。

## 和你给的草稿的差异（每一条都是刻意的）

1. **``action`` / ``on_enter`` / ``on_exit`` 从裸 ``Callable`` 换成 :class:`Step`。**
   裸函数不可序列化、不可日志化、没有重试和超时；``Step`` 全都有，而且执行层
   已经实现好了。想塞裸函数就用 ``FunctionStep(fn)`` 包一层，一行的事。
   另外节点做的事通常是**一串**（点技能 → 等冷却 → 看血量），所以是 ``steps``
   而不是单个 ``action``；只做一件事就是长度 1 的列表。
2. **``Edge.condition`` 优先用 ``Query``**（可配置、可序列化、可复用），
   ``Callable`` 作为逃生舱。条件本身是"某张图在不在"的部分，不该退化成 lambda。
3. **``Graph`` 保持无状态**（蓝图），运行游标单独放 :class:`GraphCursor`。
   你草稿里的 ``next_node(current, ctx)`` 把两者混在一起了 —— 那样同一个图
   就没法跑两次做对比，也没法序列化。运行期计数（cooldown / max_times）在游标上。
4. **``next_node`` 之外多一个 ``evaluate()``**，返回带**诊断痕迹**的
   :class:`Decision`。"为什么没走这条边"是流程调试里最花时间的问题。
5. **条件抛异常不中断流程**，但一定出现在 ``Decision.errors`` 里。引擎应该把它
   记进 journal —— 反复出现说明条件写错了，而不是"恰好没满足"。
6. **不做边的索引**：边数是几十量级，每帧过滤一遍比维护索引更不容易出错
   （索引会和 ``edges`` 不同步）。真到几千条边再说。

## 一个重要的语义

``next_node`` 返回 **None 表示"原地不动"**，这不是错误 —— 很多状态下就是要
反复做当前节点的事（战斗中点技能），没有边满足是正常分支，不是失败。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Union

from ..exceptions import FlowError
from ..state.page import PageId
from ..types import ActionResult
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from ..atomic.query import Query
    from ..context import RunContext
    from ..execution.step import Step

log = get_logger("flow.graph")

__all__ = [
    "Decision",
    "Edge",
    "EdgeAttempt",
    "EdgeKind",
    "EdgeStats",
    "Graph",
    "GraphCursor",
    "Node",
    "NodeId",
]

NodeId = str
"""流程图节点标识。"""

EdgeCondition = Union["Query", Callable[["RunContext"], Any]]
"""边条件：``Query``（推荐）或 ``Callable[[RunContext], bool | ActionResult]``。"""


class EdgeKind(StrEnum):
    """边的类型。影响日志、报告，以及引擎的兜底处理。"""

    NORMAL = "normal"
    """常规转移。"""

    FALLBACK = "fallback"
    """兜底：其他都不成立时才走（如"卡住了就重来"）。"""

    RECOVERY = "recovery"
    """异常恢复：超时、回到主界面。优先级通常最高，但**必须带 condition**。"""

    TERMINAL = "terminal"
    """终态：结束流程。"""


# --------------------------------------------------------------------------- #
# 节点
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Node:
    """流程图的一个节点 = "待在某个页面时要做的事"。

    :param id: 唯一标识。建议和页面同名（``"home/qianli/battle"``），好对照。
    :param steps: 每次轮到这个节点时执行的步骤，按顺序。空列表 = 纯等待/观察节点。
    :param page: **声明"我负责哪个状态"**（``PageId``）；None = 不声明，也就不校验。

        这一个字段有三个用途，全都由 :class:`gamebot.flow.binding.StateBinding`
        实现（那是两侧唯一的桥）：

        1. **动前校验**：实测状态和它不符时拒绝执行 steps —— 防止在错误页面上乱点；
        2. **重定位去向**：状态层报出真实锚点后，靠它反查"该落到哪个节点"；
        3. **动后预期**：节点跑完，当前"预期状态"跟着游标变成它的 ``page``。

        不写它的节点就是"纯逻辑/纯等待"节点：不校验、不参与重定位，
        流程图因此可以只写正常流程。见 ``docs/state-and-flow.md``。
    :param priority: 多个节点声明同一个 ``page`` 时谁是**主节点**。
        重定位必须落到唯一一个节点上，所以同状态多节点时要能选出主节点：
        取 ``priority`` 最大者，并列时取先声明的。
    :param on_enter: 进入该节点时执行一次（进入 = 从别的节点切过来）。
    :param on_exit: 离开该节点时执行一次。
    :param max_visits: 一轮运行中最多执行几次；``0`` = 不限。
        防止"原地死循环刷同一个界面"。
    :param cooldown: 两次执行之间的最小间隔（秒）。防止空转打满 CPU / adb。
    :param timeout: 在该节点停留的时间预算（秒）；超了走 ``on_timeout``。
    :param on_timeout: 超时后跳到哪个节点；空串 = 交给引擎的通用兜底。
    :param description: 说明。
    :param meta: 任意附加信息。
    """

    id: NodeId
    steps: list[Step] = field(default_factory=list)
    page: PageId | None = None
    priority: int = 0
    on_enter: list[Step] = field(default_factory=list)
    on_exit: list[Step] = field(default_factory=list)
    max_visits: int = 0
    cooldown: float = 0.0
    timeout: float | None = None
    on_timeout: NodeId = ""
    description: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, node_id: NodeId, *steps: Step, **kwargs: Any) -> Node:
        """只做一件事的节点的简写：``Node.of("battle", ClickImageStep("skill.png"))``。"""
        return cls(id=node_id, steps=list(steps), **kwargs)

    @property
    def display(self) -> str:
        return self.description or self.id

    @property
    def is_passive(self) -> bool:
        """只识别不动作的节点。"""
        return not self.steps and not self.on_enter and not self.on_exit

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "page": self.page,
            "priority": self.priority,
            "steps": len(self.steps),
            "on_enter": len(self.on_enter),
            "on_exit": len(self.on_exit),
            "max_visits": self.max_visits,
            "cooldown": self.cooldown,
            "timeout": self.timeout,
            "on_timeout": self.on_timeout,
        }

    def __repr__(self) -> str:
        return f"Node({self.id!r}, steps={len(self.steps)}, page={self.page!r})"


# --------------------------------------------------------------------------- #
# 边
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Edge:
    """一条转移。

    :param source: 起点节点 id。
    :param target: 终点节点 id。
    :param condition: 守卫条件。``None`` = 无条件（只要在上面的状态就直接走）。
        优先用 ``Query``；需要复杂逻辑时用 ``Callable[[RunContext], bool]``。
    :param priority: 数字大的先判断。多条边同时成立时靠它定胜负 ——
        **不要靠列表顺序**，那样在 YAML 里挪一行就会静默改变行为。
    :param label: 人类可读说明，会写进日志和报告。
    :param cooldown: 该边触发后多少秒内不允许再次触发。防止识别抖动导致来回横跳。
    :param max_times: 一轮运行里最多触发几次；``0`` = 不限。用于"重试 3 次就放弃"。
    :param kind: 边类型，见 :class:`EdgeKind`。
    :param meta: 任意附加信息。
    """

    source: NodeId
    target: NodeId
    condition: EdgeCondition | None = None
    priority: int = 0
    label: str = ""
    cooldown: float = 0.0
    max_times: int = 0
    kind: EdgeKind = EdgeKind.NORMAL
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.label or f"{self.source} -> {self.target}"

    @property
    def has_condition(self) -> bool:
        return self.condition is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "priority": self.priority,
            "kind": self.kind.value,
            "label": self.label,
            "has_condition": self.has_condition,
            "cooldown": self.cooldown,
            "max_times": self.max_times,
        }

    def __repr__(self) -> str:
        return f"Edge({self.display!r}, priority={self.priority})"


# --------------------------------------------------------------------------- #
# 决策（带诊断）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class EdgeAttempt:
    """一条边的评估痕迹。"""

    edge: Edge
    accepted: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"edge": self.edge.display, "accepted": self.accepted, "reason": self.reason}


@dataclass(slots=True)
class Decision:
    """一次"下一步去哪"的完整结果，**包含为什么**。

    ``target is None`` 表示原地不动 —— 不是失败，是很正常的分支
    （战斗中点技能，没有边满足就继续做当前节点的事）。
    """

    current: NodeId
    target: NodeId | None = None
    attempts: list[EdgeAttempt] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    """条件求值时的异常。**不会中断流程，但一定要记进 journal** ——
    反复出现说明条件写错了，而不是"恰好没满足"。"""

    @property
    def moved(self) -> bool:
        return self.target is not None and self.target != self.current

    @property
    def stayed(self) -> bool:
        return self.target is None

    def explain(self) -> str:
        """一行说明，给日志用。"""
        if self.target is None:
            reason = "；".join(f"{a.edge.display}: {a.reason}" for a in self.attempts) or "没有出边"
            return f"{self.current} 原地不动（{reason}）"
        return f"{self.current} -> {self.target}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "target": self.target,
            "attempts": [a.to_dict() for a in self.attempts],
            "errors": self.errors,
        }

    def __repr__(self) -> str:
        return f"Decision({self.explain()!r})"


# --------------------------------------------------------------------------- #
# 运行期计数（刻意放在 Graph 外面）
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class EdgeStats:
    """边的运行期计数。

    **和 ``Graph`` 分开**，这样蓝图可以被多个运行共享、序列化、对比 ——
    两轮跑同一个图的差异，只体现在这里。
    """

    fired: dict[int, int] = field(default_factory=dict)
    last_at: dict[int, float] = field(default_factory=dict)

    def count(self, index: int) -> int:
        return self.fired.get(index, 0)

    def since_last(self, index: int, now: float) -> float | None:
        last = self.last_at.get(index)
        return None if last is None else now - last

    def record(self, index: int, now: float) -> None:
        self.fired[index] = self.fired.get(index, 0) + 1
        self.last_at[index] = now

    def reset(self) -> None:
        self.fired.clear()
        self.last_at.clear()

    def to_dict(self) -> dict[str, Any]:
        return {"fired": dict(self.fired)}


# --------------------------------------------------------------------------- #
# 图（蓝图，无状态）
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Graph:
    """流程图蓝图。**无运行期状态** —— 游标和计数在 :class:`GraphCursor`。

    :param initial: 起始节点 id。
    :param nodes: 节点表。
    :param edges: 边表（顺序无意义，优先级由 ``Edge.priority`` 决定）。
    """

    initial: NodeId = ""
    nodes: dict[NodeId, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # 构建
    # ------------------------------------------------------------------ #
    def add_node(self, node: Node) -> Node:
        if node.id in self.nodes:
            raise FlowError(f"节点 id 重复: {node.id!r}")
        self.nodes[node.id] = node
        if not self.initial:
            self.initial = node.id
        return node

    def add_edge(self, edge: Edge) -> Edge:
        self.edges.append(edge)
        return edge

    def connect(
        self,
        source: NodeId,
        target: NodeId,
        *,
        condition: Any = None,
        priority: int = 0,
        **kwargs: Any,
    ) -> Edge:
        """``add_edge(Edge(...))`` 的简写。"""
        return self.add_edge(
            Edge(source=source, target=target, condition=condition, priority=priority, **kwargs)
        )

    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self.nodes

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def node(self, node_id: NodeId) -> Node | None:
        return self.nodes.get(node_id)

    def require(self, node_id: NodeId) -> Node:
        node = self.nodes.get(node_id)
        if node is None:
            raise FlowError(f"节点不存在: {node_id!r}")
        return node

    def index_of(self, edge: Edge) -> int:
        """边在 ``edges`` 里的下标（计数和冷却用它当 key）。

        :return: 下标；找不到返回 -1（那条边不属于这个图，计数会被忽略）。
        """
        for index, candidate in enumerate(self.edges):
            if candidate is edge:
                return index
        return -1

    def out_edges(self, node_id: NodeId) -> tuple[Edge, ...]:
        """出边，按 ``priority`` 降序（同优先级保持声明顺序，便于预期）。

        刻意不做索引：边数是几十量级，每帧过滤一遍比维护一个
        会跟 ``edges`` 不同步的索引更不容易出错。
        """
        matched = [e for e in self.edges if e.source == node_id]
        return tuple(sorted(matched, key=lambda e: -e.priority))

    def in_edges(self, node_id: NodeId) -> tuple[Edge, ...]:
        return tuple(e for e in self.edges if e.target == node_id)

    def node_for_page(self, page_id: PageId) -> Node | None:
        """声明了"我该在这个页面上"的节点。

        这是树和图的**主要结合点**：定位到某页面后，用它反查该去哪个节点。
        多个节点声明同一页面时返回第一个（同页面多节点是合法设计，
        用边的优先级去区分该走哪个）。
        """
        for node in self.nodes.values():
            if node.page == page_id:
                return node
        return None

    def nodes_for_page(self, page_id: PageId) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes.values() if n.page == page_id)

    def reachable_from(self, start: NodeId | None = None) -> set[NodeId]:
        """从起点出发能走到的节点集合（用来找死代码）。"""
        origin = start or self.initial
        if origin not in self.nodes:
            return set()
        seen: set[NodeId] = set()
        queue: list[NodeId] = [origin]
        while queue:
            current = queue.pop()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(e.target for e in self.out_edges(current) if e.target in self.nodes)
        return seen

    # ------------------------------------------------------------------ #
    # 决策
    # ------------------------------------------------------------------ #
    def is_available(
        self,
        edge: Edge,
        *,
        stats: EdgeStats | None = None,
        now: float = 0.0,
    ) -> tuple[bool, str]:
        """次数 / 冷却是否允许这条边。返回 ``(可用?, 不可用原因)``。"""
        if stats is None:
            return True, ""
        index = self.index_of(edge)
        if index < 0:
            return True, ""

        if edge.max_times and stats.count(index) >= edge.max_times:
            return False, f"已达最大次数 {edge.max_times}"
        if edge.cooldown:
            elapsed = stats.since_last(index, now)
            if elapsed is not None and elapsed < edge.cooldown:
                return False, f"冷却中（剩余 {edge.cooldown - elapsed:.2f}s）"
        return True, ""

    def evaluate(
        self,
        current: NodeId,
        ctx: RunContext,
        *,
        stats: EdgeStats | None = None,
        now: float = 0.0,
    ) -> Decision:
        """挑一条可用的出边，返回带诊断的 :class:`Decision`。

        :param stats: 运行期计数。``None`` 表示不检查 cooldown / max_times
            （纯静态评估，调试和单测用）。
        :return: ``target=None`` 表示原地不动。
        """
        attempts: list[EdgeAttempt] = []
        errors: list[str] = []

        for edge in self.out_edges(current):
            available, unavailable_reason = self.is_available(edge, stats=stats, now=now)
            if not available:
                attempts.append(EdgeAttempt(edge, False, unavailable_reason))
                continue

            satisfied, reason, failed = _check_condition(edge.condition, ctx)
            if failed:
                errors.append(f"{edge.display}: {reason}")
            attempts.append(EdgeAttempt(edge, satisfied, reason))
            if satisfied:
                return Decision(
                    current=current,
                    target=edge.target,
                    attempts=attempts,
                    errors=errors,
                )

        return Decision(current=current, target=None, attempts=attempts, errors=errors)

    def next_node(self, current: NodeId, ctx: RunContext) -> NodeId | None:
        """你草稿里那个签名。``None`` = 原地不动。

        等价于 ``evaluate(current, ctx).target``（**不带** cooldown / max_times，
        因为那些计数在游标上）。要完整语义用 :meth:`GraphCursor.next`。
        """
        return self.evaluate(current, ctx).target

    # ------------------------------------------------------------------ #
    # 校验（装配期）
    # ------------------------------------------------------------------ #
    def validate(self) -> None:
        """结构校验，把配置错误挡在启动阶段而不是跑一半才炸。

        检查项：

        1. ``initial`` 非空且存在；
        2. 至少有一个节点；
        3. 每条边的 ``source`` / ``target`` 都存在；
        4. 没有从起点走不到的节点（死代码）；
        5. ``terminal`` 类型的边指向的节点不该再有出边；
        6. ``cooldown`` / ``max_times`` 非负；
        7. 提示"没有条件的边" —— 它会让同一 source 下所有低优先级的边永远走不到，
           除非它本来就是兜底（``kind=FALLBACK/TERMINAL``）。

        :raises FlowError: 校验失败，message 里带上全部问题。
        """
        problems: list[str] = []

        if not self.nodes:
            problems.append("图里一个节点都没有")
        if not self.initial:
            problems.append("没有设置 initial")
        elif self.initial not in self.nodes:
            problems.append(f"initial 指向不存在的节点: {self.initial!r}")

        for edge in self.edges:
            if edge.source not in self.nodes:
                problems.append(f"边 {edge.display} 的 source 不存在: {edge.source!r}")
            if edge.target not in self.nodes:
                problems.append(f"边 {edge.display} 的 target 不存在: {edge.target!r}")
            if edge.cooldown < 0:
                problems.append(f"边 {edge.display} 的 cooldown 不能为负")
            if edge.max_times < 0:
                problems.append(f"边 {edge.display} 的 max_times 不能为负")

        for node in self.nodes.values():
            if node.cooldown < 0:
                problems.append(f"节点 {node.id!r} 的 cooldown 不能为负")
            if node.max_visits < 0:
                problems.append(f"节点 {node.id!r} 的 max_visits 不能为负")
            if node.on_timeout and node.on_timeout not in self.nodes:
                problems.append(f"节点 {node.id!r} 的 on_timeout 指向不存在的节点")

        if self.initial in self.nodes:
            orphans = sorted(set(self.nodes) - self.reachable_from())
            if orphans:
                problems.append(f"从 initial 走不到的节点（死代码）: {', '.join(orphans)}")

        for node in self.nodes.values():
            terminal_targets = [e for e in self.out_edges(node.id) if e.kind is EdgeKind.TERMINAL]
            if terminal_targets and self.out_edges(terminal_targets[0].target):
                problems.append(
                    f"节点 {node.id!r} 有 terminal 边指向 {terminal_targets[0].target!r}，"
                    "但那个节点还有出边 —— 终态不该继续"
                )

        if problems:
            raise FlowError("流程图校验失败:\n  - " + "\n  - ".join(problems))

    # ------------------------------------------------------------------ #
    def describe(self) -> str:
        """打印成可读的清单，给日志和 ``gamebot check`` 用。"""
        lines = [f"Graph(initial={self.initial!r}, {len(self.nodes)} 节点, {len(self.edges)} 边)"]
        for node in self.nodes.values():
            page = f" @ {node.page}" if node.page else ""
            lines.append(f"  [{node.id}]{page}  steps={len(node.steps)}")
            for edge in self.out_edges(node.id):
                guard = "?" if edge.has_condition else "-"
                lines.append(
                    f"      {guard} -> {edge.target}"
                    f"  (p={edge.priority}, {edge.kind.value})"
                )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial": self.initial,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
        }

    def __repr__(self) -> str:
        return f"Graph(initial={self.initial!r}, nodes={len(self.nodes)}, edges={len(self.edges)})"


# --------------------------------------------------------------------------- #
# 运行游标
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class GraphCursor:
    """在图上游走的游标 —— **运行期状态都在这里**。

    :param graph: 要走的图（蓝图，可以被多个游标共享）。
    :param current: 当前节点；空串表示从 ``graph.initial`` 开始。
    """

    graph: Graph
    current: NodeId = ""
    stats: EdgeStats = field(default_factory=EdgeStats)
    visits: dict[NodeId, int] = field(default_factory=dict)
    history: list[NodeId] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.current:
            self.current = self.graph.initial
        if self.current:
            self.history.append(self.current)

    # ------------------------------------------------------------------ #
    def visits_of(self, node_id: NodeId) -> int:
        return self.visits.get(node_id, 0)

    def evaluate(self, ctx: RunContext, *, now: float = 0.0) -> Decision:
        """评估下一步（不改状态）。"""
        return self.graph.evaluate(self.current, ctx, stats=self.stats, now=now)

    def next(self, ctx: RunContext, *, now: float = 0.0) -> NodeId | None:
        """评估下一步并返回目标；``None`` = 原地不动。"""
        return self.evaluate(ctx, now=now).target

    def should_run(self, ctx: RunContext, *, now: float = 0.0) -> tuple[bool, str]:
        """当前节点这一轮该不该执行 steps。返回 ``(该执行?, 原因)``。

        两个拦截条件，都是**这个节点自己的运行期计数**：

        * ``max_visits`` 用尽 —— 防止原地死循环刷同一个界面；
        * ``cooldown`` 还没过 —— 防止空转打满 CPU 和 adb。

        ## 状态校验**不在这里**

        早期它还会比一次 ``node.page`` 和实测状态。那条检查现在归引擎，走
        :class:`~gamebot.flow.binding.StateBinding`：

        * 关联表才说得清"期望什么、实测什么、不一致时该去哪"；
          这里比一下只能给出一句"不符"，而且会**绕开关联表**变成第二份实现；
        * 引擎的顺序是"先校验（可能重定位）、再问该不该跑"，位置不对时根本
          走不到这里。

        留着它会让同一件事有两个出处 —— 那是这套设计一直在避免的东西。
        """
        node = self.graph.node(self.current)
        if node is None:
            return False, f"当前节点不存在: {self.current!r}"

        if node.max_visits and self.visits_of(node.id) >= node.max_visits:
            return False, f"已达最大访问次数 {node.max_visits}"

        return True, ""

    def advance(self, target: NodeId, *, now: float = 0.0) -> bool:
        """移动到目标节点，并记录一次触发。返回是否真的移动了。"""
        if target not in self.graph.nodes:
            raise FlowError(f"要跳去的节点不存在: {target!r}")
        if target == self.current:
            return False

        for edge in self.graph.out_edges(self.current):
            if edge.target == target:
                index = self.graph.index_of(edge)
                if index >= 0:
                    self.stats.record(index, now)
                break

        self.current = target
        self.visits[target] = self.visits.get(target, 0) + 1
        self.history.append(target)
        return True

    def step(self, ctx: RunContext, *, now: float = 0.0) -> NodeId | None:
        """"评估 + 移动"一步到位。返回移动后的当前节点。"""
        decision = self.evaluate(ctx, now=now)
        if decision.target is not None:
            self.advance(decision.target, now=now)
        return decision.target

    def reset(self, *, to: NodeId = "") -> None:
        """回到起点，清空所有计数（不产生历史记录）。

        :param to: 回到哪个节点；留空 = ``graph.initial``。
            ``FlowEngine`` 传它配置的起始节点 —— 不这样的话，
            "从节点 X 开始"的语义会在任何一次 reset 之后悄悄丢掉。
        """
        target = to or self.graph.initial
        if target and self.graph.node(target) is None:
            raise FlowError(f"reset 的目标节点不存在: {target!r}")
        self.current = target
        self.stats.reset()
        self.visits.clear()
        self.history.clear()
        if self.current:
            self.history.append(self.current)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "visits": dict(self.visits),
            "history": list(self.history),
            "stats": self.stats.to_dict(),
        }

    def __repr__(self) -> str:
        return f"GraphCursor(current={self.current!r}, visits={len(self.visits)})"


# --------------------------------------------------------------------------- #
# 条件求值
# --------------------------------------------------------------------------- #
def _check_condition(condition: Any, ctx: RunContext) -> tuple[bool, str, bool]:
    """求一个边条件。

    :return: ``(是否满足, 说明, 是否因异常失败)``。
        异常**不中断流程**（返回 not satisfied），但会标记出来，
        由 :attr:`Decision.errors` 上报 —— 静默吞掉会让"条件写错了"
        表现得像"恰好没满足"，那是最难查的一类 bug。
    """
    if condition is None:
        return True, "无条件", False

    try:
        runner = getattr(condition, "run", None)
        if callable(runner):
            # Query：在**当前帧**上跑（必须是同一帧，否则时序会漂）
            result = runner(ctx.frame())
            if result.ok:
                return True, result.message or "查询命中", False
            return False, result.message or "查询未命中", False

        if callable(condition):
            outcome = condition(ctx)
            if isinstance(outcome, ActionResult):
                return bool(outcome.ok), outcome.message, False
            return bool(outcome), "", False

        return False, f"不是合法的条件（既没有 run() 也不可调用）: {condition!r}", True
    except Exception as exc:  # 条件里的 bug 不该炸掉整轮
        return False, f"条件求值异常: {exc}", True
