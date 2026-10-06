"""业务层脚本的**声明** —— 页面、节点、边摊在这里，框架负责组装。

## 为什么"声明"和"组装"要分开

业务层该回答的是**"这个脚本是什么"**：有哪些状态、每个状态做什么、什么条件下
从一个状态走到另一个。它不该回答**"怎么把它拼成一个对象"** —— 那是框架的事，
而且是**每一份声明都一样**的事（按层级建树、按顺序加节点、连边、校验）。

所以这里的类型收的是**数据**，组装在 :meth:`ScenarioSpec.materialize` 里做一次。
好处有三个，都是实际的：

* **没有"组装代码"可写错** —— 原来每个功能都要自己写一遍
  ``graph = Graph(...); graph.add_node(...); graph.connect(...)``，
  漏掉一步（忘了 ``add_node`` 就连边）是运行期的事故；
* **声明是纯数据**，所以能被赋值、能被对比、能一眼看全，不需要"执行一遍才知道
  它是什么"；
* **组装时的顺序与校验只有一处**：页面按"父先子后"加、边在节点之后连
  （这样悬空引用当场报）、``options`` 直接进 ``Scenario``。

## 「父子」和「顺序」都不用你去操心

* 页面用 ``(页面, 父页面 id)`` 的扁平列表给，**父在前**——
  框架按这个顺序 ``add()`` 就能算出路径形式的 id 和 ROI 继承；
* 节点用列表给，边的 ``source`` / ``target`` 写节点 id，
  框架在**全部节点加完之后**才连边，所以"边指向不存在的节点"会当场报错
  （而不是等你跑到那条边才发现）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exceptions import ConfigError
from .flow.graph import Edge, Graph, Node
from .flow.scenario import EngineOptions, Scenario
from .state.page import PageGroup, PageNode, PageTree

__all__ = ["ScenarioSpec"]

#: ``(起点节点 id, 终点节点 id, 边的其余参数)``。
#: 用三元组而不是直接收一个 ``Edge``：``Edge`` 要求 ``source`` / ``target``
#: 在**构造时**就给出，而"边从哪连到哪"正是这里想写得最短的部分。
EdgeEntry = tuple[str, str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    """一个脚本的状态树 + 流程图 + 运行选项，**都是数据**。

    :param pages: ``(页面, 父页面 id)``，**父必须先于子**。``None`` 表示顶层。
    :param nodes: 全部流程节点，顺序即声明顺序（同状态多节点时用它定主节点）。
    :param edges: ``(source, target, kwargs)``。``kwargs`` 透传给
        :class:`~gamebot.flow.graph.Edge`（``condition`` / ``priority`` /
        ``label`` / ``cooldown`` / ``max_times`` / ``kind``）。
        边在**所有节点加完之后**才连，所以悬空引用当场报。
    :param initial: 起始节点 id。**必选**：一个流程从哪开始是它的核心信息，
        给默认值只会让"忘了写"变成"悄悄从第一个节点开始"。
    :param options: 引擎选项。不传就是默认值。
    :param name: 脚本名（进日志和报告）。留空则用 SPEC 的 name。
    :param meta: 任意附加信息。
    """

    initial: str
    tree: PageGroup | None = None
    nodes: tuple[Node, ...] = ()
    edges: tuple[EdgeEntry, ...] = ()
    options: EngineOptions = field(default_factory=EngineOptions)
    name: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """声明自身的检查 —— 一望即知的那些，**构造这一行就报**。

        需要"看到全部数据"的（悬空引用、从 initial 走不到、节点认领状态）
        留给 :meth:`materialize` —— 那一步本来就拿着全部数据。
        """
        if not self.initial.strip():
            raise ConfigError("ScenarioSpec.initial 不能为空 —— 流程总得从某个节点开始")
        if not self.nodes:
            raise ConfigError("ScenarioSpec.nodes 不能为空 —— 一个节点都没有的流程没有意义")

        seen: set[str] = set()
        for node in self.nodes:
            if node.id in seen:
                raise ConfigError(f"节点 id 重复: {node.id!r}")
            seen.add(node.id)
        if self.initial not in seen:
            raise ConfigError(
                f"ScenarioSpec.initial={self.initial!r} 不在 nodes 里"
                f"（有: {sorted(seen)}）"
            )

        if self.tree is not None and not isinstance(self.tree, PageNode):
            raise ConfigError(
                f"ScenarioSpec.tree 要是 PageGroup / PageLeaf，"
                f"收到 {type(self.tree).__name__}"
            )

    # ------------------------------------------------------------------ #
    # 组装
    # ------------------------------------------------------------------ #
    def materialize(self, *, name: str, tree: PageTree | None = None) -> Scenario:
        """把这份声明**组装**成运行期的 :class:`Scenario`。

        **框架调它，业务层不调。** 顺序是有讲究的：

        1. 先建树（``pages`` 必须父先子后，``add()`` 才能算出路径 id 与 ROI 继承）；
        2. 再加**全部**节点 —— 然后才连边。反过来的话，"边指向还没加的节点"
           会变成一条假错误；
        3. 连完边 ``Scenario.validate()`` 会跑完整校验（悬空引用、走不到的节点、
           节点认领状态），报错里带全部问题。

        :param name: 脚本名（``Scenario.name``）。用 SPEC 的 name。
        :param tree: 预置的树（游戏级公共页面）。给了就在它上面加本功能的页面。
        :raises ConfigError: 声明里有跨对象的问题。
        """
        target = tree if tree is not None else PageTree()
        if self.tree is not None:
            # 嵌套结构：add() 会递归把整棵树加进去（父先子后由递归保证）
            target.add(self.tree)

        graph = Graph(initial=self.initial)
        for node in self.nodes:
            graph.add_node(node)
        for source, edge_target, kwargs in self.edges:
            graph.add_edge(Edge(source, edge_target, **kwargs))

        scenario = Scenario(
            name=self.name or name,
            tree=target,
            graph=graph,
            options=self.options,
            meta=dict(self.meta),
        )
        # 跨对象的问题（悬空引用 / 走不到的节点 / 节点认领状态）在这一步报。
        # 放在材质化里而不是等引擎 run —— 那样"定义坏了"会表现成"跑一半卡住"。
        scenario.validate()
        return scenario
