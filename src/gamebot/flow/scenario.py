"""一份完整脚本的蓝图 —— 状态树 + 流程图 + 运行参数。

## 为什么把两者打成一个包

它们**必须一起校验**：

* 关联表里每个节点对应的状态必须在状态树里存在（写错一个字母，那一整条
  流程就永远不执行 —— 而且不报错，只是"什么也没发生"）；
* **每个记录信息的状态都必须有流程节点认领**
  （:func:`gamebot.flow.state_binding.validate_binding`）。这不是"值得提示"，而是
  启动期直接 ``ConfigError``：重定位到无人认领的状态，游标就无处可去 ——
  而那正是"允许自动重定位"能成立的前提。

也必须一起校验。分开管理的话，很容易出现"改了状态 id、流程图忘了改"
这种跨文件的静默失效。

## 为什么状态和流程要分开装

以前它们平铺在一个对象里（states / nodes / transitions 三张表），于是"加一个界面"
和"改一条策略"动的是同一个文件、同一个结构。现在明确拆成 ``tree``（我在哪）
和 ``graph``（做什么）—— 两者的变化频率和修改人都不同。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..exceptions import ConfigError
from ..state.page import PageId, PageTree
from ..utils.logging import get_logger
from .graph import Graph
from .node_bindings import NodeBindings

if TYPE_CHECKING:
    from .state_binding import StateBinding

log = get_logger("flow.scenario")

__all__ = ["EngineOptions", "Scenario"]


@dataclass(slots=True)
class EngineOptions:
    """引擎运行参数。"""

    tick_interval: float = 0.2
    """每轮之间的最小间隔（秒）。**别给 0** —— 空转只会打满 CPU 和 adb，
    还让日志没法读。"""

    max_runtime: float | None = None
    """整个流程的时长上限（秒）。"""

    max_ticks: int = 0
    """最大轮数；``0`` = 不限。"""

    stop_pages: tuple[PageId, ...] = ()
    """进入这些状态即结束流程（如 ``"closed"``）。"""

    require_confirmed: bool = True
    """状态未"确认进入"（连续命中帧数不够）前不执行动作。默认开。"""

    dry_run: bool = False
    """空跑：只定位和决策，不执行动作步骤。"""

    save_frames_on_error: bool = False
    """失败时把当帧存盘，方便事后看"当时屏幕上到底有什么"。"""

    dead_end_rounds: int = 3
    """末梢节点上连续这么多轮 ``not_found`` 就认为**流程走到头了**（``no_more_work``）。

    为什么需要它：流程干完活之后，末梢节点会一轮轮地"找不到可做的事"。
    没有这个判定，脚本会一直空转到 ``max_runtime``（实测名将杀 3 秒里空转 193 轮）。

    调大它：界面过渡慢的游戏（点了按钮要好几秒才出新页面）——那时"连着几轮没找到"
    可能只是还没切过去。调成 0 就是关掉这个判定。
    """

    def validate(self) -> list[str]:
        """返回问题列表（空 = 没问题）。装配期调一次。"""
        problems: list[str] = []
        if self.tick_interval <= 0:
            problems.append("tick_interval 必须 > 0")
        if self.max_runtime is not None and self.max_runtime <= 0:
            problems.append("max_runtime 必须 > 0 或留空")
        if self.max_ticks < 0:
            problems.append("max_ticks 不能为负")
        if self.dead_end_rounds < 0:
            problems.append("dead_end_rounds 不能为负（0 = 关掉'流程走完'判定）")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick_interval": self.tick_interval,
            "max_runtime": self.max_runtime,
            "max_ticks": self.max_ticks,
            "stop_pages": list(self.stop_pages),
            "require_confirmed": self.require_confirmed,
            "dry_run": self.dry_run,
        }


@dataclass(slots=True)
class Scenario:
    """一整份脚本：状态树 + 流程图 + **关联表** + 运行参数。

    **三个产物各是一个字段**，谁也不藏在谁里面：

    :param name: 脚本名，进日志和报告。
    :param tree: 状态树 —— "我在哪"（靠画面认）。
    :param graph: 流程图 —— "做什么、何时换"。
    :param bindings: 关联表 —— 状态末梢 ↔ 流程节点的 id 双向映射。
        它**不属于**树也不属于图（那是"两者怎么对上"），所以是独立字段。
    :param options: 运行参数（tick 间隔、预算、未知策略……）。
    :param meta: 任意附加信息。
    """

    name: str = "scenario"
    tree: PageTree = field(default_factory=PageTree)
    graph: Graph = field(default_factory=Graph)
    bindings: NodeBindings = field(default_factory=NodeBindings)
    options: EngineOptions = field(default_factory=EngineOptions)
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # 校验
    # ------------------------------------------------------------------ #
    def validate(self) -> None:
        """跨状态树和图的完整校验。任何一条不满足都抛异常。

        1. 状态树自身合法（:meth:`PageTree.validate`）；
        2. 流程图自身合法（:meth:`Graph.validate`）；
        3. **状态 ↔ 节点的关联合法**（:func:`gamebot.flow.state_binding.validate_binding`）：
           每个节点声明的状态必须存在，而且**每个记录信息的状态都必须有节点
           认领** —— 否则重定位到它就无处可去；
        4. ``options.stop_pages`` 必须在树里存在；
        5. 运行参数合法。

        :raises StateError: 状态树的问题。
        :raises FlowError: 流程图的问题。
        :raises ConfigError: 跨两者的引用错了（状态 id / 节点 id 对不上）。
        """
        problems: list[str] = []

        self.tree.validate()
        self.graph.validate()
        # 关联表的引用错误在这里报（节点关联的状态在不在、状态有没有人认领）
        self.bindings.validate(self.tree, self.graph)

        for page_id in self.options.stop_pages:
            if page_id not in self.tree:
                problems.append(f"stop_pages 里不存在的状态: {page_id!r}")

        problems.extend(self.options.validate())

        if problems:
            raise ConfigError("脚本校验失败:\n  - " + "\n  - ".join(problems))

    # ------------------------------------------------------------------ #
    # 状态 ↔ 节点
    # ------------------------------------------------------------------ #
    def binding(self) -> StateBinding:
        """这份脚本的"状态 ↔ 节点"关联表（引擎和界面检查用它）。"""
        from .state_binding import StateBinding

        return StateBinding(self.bindings, self.graph)

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def unclaimed_pages(self) -> tuple[PageId, ...]:
        """没有任何节点声明认领的状态。

        两类状态**不算数**，因为它们本来就不该有节点：

        * **分类节点**（``kind=GROUP``）—— 自己不参与匹配，定位结果里
          永远不会出现它；
        * **叠加层**（``kind=OVERLAY``）—— 它不是"能待着的位置"，
          而是"主状态之上多了一层"，由主状态的节点负责。

        **终态状态（``terminal=True``）要算数**：它进了就结束流程，但仍然需要
        一个节点认领（通常配一条 ``kind: terminal`` 的边指向它）—— 否则重定位
        到它就无处可去，``validate_binding`` 会因此报错。这一点容易写反：
        "终态不需要动作"不等于"不需要节点"。

        剩下的未认领状态**不是警告而是错误**（由 :func:`validate_binding`
        在启动期拦下）。这个方法留给界面检查做
        "把整棵树摊开看一眼"的展示。
        """
        claimed = set(self.bindings.table().values())
        return tuple(
            p.id
            for p in self.tree.walk()
            if p.id not in claimed and not p.is_overlay and not p.is_group
        )

    def describe(self) -> str:
        """可读的完整描述，给日志和界面检查用。"""
        return "\n".join(
            [
                f"Scenario({self.name!r})",
                self.tree.describe(),
                self.graph.describe(),
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tree": self.tree.to_dict(),
            "graph": self.graph.to_dict(),
            "options": self.options.to_dict(),
            "unclaimed_pages": list(self.unclaimed_pages()),
        }

    def __repr__(self) -> str:
        return (
            f"Scenario({self.name!r}, {len(self.tree)} 页面, "
            f"{len(self.graph)} 节点, {len(self.graph.edges)} 边)"
        )
