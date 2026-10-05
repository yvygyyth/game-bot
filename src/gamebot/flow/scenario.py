"""一份完整脚本的蓝图 —— 页面树 + 流程图 + 运行参数。

## 为什么把两者打成一个包

它们**必须一起校验**：

* 每个 ``Node.page`` 声明的页面必须在页面树里存在（写错一个字母，那一整条
  流程就永远不执行 —— 而且不报错，只是"什么也没发生"）；
* ``recovery_node`` 必须在流程图里存在；
* 页面树里有页面没有任何节点认领 —— 不算错，但值得提示（可能是漏写了流程）。

也必须一起加载、一起序列化。分开管理的话，很容易出现"配置里改了页面 id、
流程图忘了改"这种跨文件的静默失效。

## 为什么页面和流程要分开装

以前它们平铺在一个对象里（states / nodes / transitions 三张表），于是"加一个界面"
和"改一条策略"动的是同一个文件、同一个结构。现在明确拆成 ``tree``（我在哪）
和 ``graph``（做什么）—— 两者的变化频率和修改人都不同。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..exceptions import ConfigError
from ..state.page import PageId, PageTree
from ..utils.logging import get_logger
from .graph import Graph, NodeId

if TYPE_CHECKING:
    from .binding import StateBinding

log = get_logger("flow.scenario")

__all__ = ["EngineOptions", "Scenario", "UnknownPolicy"]


class UnknownPolicy(StrEnum):
    """认不出页面时怎么办。

    "认不出来"是最常见的真实情况（动画中间帧、网络卡住、游戏在加载），
    所以必须显式选一个策略，而不是靠默认行为蒙混。
    """

    WAIT = "wait"
    """原地等，重新截图识别。大多数情况选它。"""

    RELOAD_TICK = "reload_tick"
    """放弃本轮，立刻下一轮。识别很便宜时用。"""

    RECOVERY = "recovery"
    """跳到 ``recovery_node``（比如"回主界面"），主动纠偏。"""

    STOP = "stop"
    """直接停流程并报告。适合"不认识就绝不乱点"的保守场景。"""


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
    """进入这些页面即结束流程（如 ``"closed"``）。"""

    on_unknown: UnknownPolicy = UnknownPolicy.WAIT
    recovery_node: NodeId = ""
    """``on_unknown == RECOVERY`` 时跳到哪个节点。"""

    unknown_grace: float = 1.0
    """宽容期（秒）。进入未知状态后的这段时间只等不动作 —— 过场动画本来
    就会短暂认不出来。没有它，脚本会在每次场景切换时误判并乱点。"""

    require_confirmed: bool = True
    """页面未"确认进入"（连续命中帧数不够）前不执行动作。默认开。"""

    dry_run: bool = False
    """空跑：只定位和决策，不执行动作步骤。"""

    save_frames_on_error: bool = False
    """失败时把当帧存盘，方便事后看"当时屏幕上到底有什么"。"""

    def validate(self) -> list[str]:
        """返回问题列表（空 = 没问题）。装配期调一次。"""
        problems: list[str] = []
        if self.tick_interval <= 0:
            problems.append("tick_interval 必须 > 0")
        if self.max_runtime is not None and self.max_runtime <= 0:
            problems.append("max_runtime 必须 > 0 或留空")
        if self.max_ticks < 0:
            problems.append("max_ticks 不能为负")
        if self.unknown_grace < 0:
            problems.append("unknown_grace 不能为负")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick_interval": self.tick_interval,
            "max_runtime": self.max_runtime,
            "max_ticks": self.max_ticks,
            "stop_pages": list(self.stop_pages),
            "on_unknown": self.on_unknown.value,
            "recovery_node": self.recovery_node,
            "unknown_grace": self.unknown_grace,
            "require_confirmed": self.require_confirmed,
            "dry_run": self.dry_run,
        }


@dataclass(slots=True)
class Scenario:
    """一整份脚本：页面树 + 流程图 + 运行参数。

    :param name: 脚本名，进日志和报告。
    :param tree: 页面树 —— "我在哪"。
    :param graph: 流程图 —— "做什么、何时换"。
    :param options: 运行参数（tick 间隔、预算、未知策略……）。
    :param meta: 任意附加信息。
    """

    name: str = "scenario"
    tree: PageTree = field(default_factory=PageTree)
    graph: Graph = field(default_factory=Graph)
    options: EngineOptions = field(default_factory=EngineOptions)
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # 校验
    # ------------------------------------------------------------------ #
    def validate(self) -> None:
        """跨状态树和图的完整校验。任何一条不满足都抛异常。

        1. 状态树自身合法（:meth:`PageTree.validate`）；
        2. 流程图自身合法（:meth:`Graph.validate`）；
        3. **状态 ↔ 节点的关联合法**（:func:`gamebot.flow.binding.validate_binding`）：
           每个节点声明的状态必须存在，而且**每个记录信息的状态都必须有节点
           认领** —— 否则重定位到它就无处可去；
        4. ``options.recovery_node`` 必须在图里存在；
        5. ``options.stop_pages`` 必须在树里存在；
        6. 运行参数合法。

        :raises StateError: 状态树的问题。
        :raises FlowError: 流程图的问题。
        :raises ConfigError: 跨两者的引用错了（状态 id / 节点 id 对不上）。
        """
        from .binding import validate_binding

        problems: list[str] = []

        self.tree.validate()
        self.graph.validate()
        validate_binding(self.graph, self.tree)

        for node in self.graph.nodes.values():
            if node.on_timeout and node.on_timeout not in self.graph.nodes:
                problems.append(f"节点 {node.id!r} 的 on_timeout 指向不存在的节点")

        if self.options.recovery_node and self.options.recovery_node not in self.graph.nodes:
            problems.append(
                f"recovery_node 指向不存在的节点: {self.options.recovery_node!r}"
            )
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
        """这份脚本的"状态 ↔ 节点"关联表（引擎和 ``gamebot check`` 用它）。"""
        from .binding import StateBinding

        return StateBinding(self.graph, self.tree)

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def unclaimed_pages(self) -> tuple[PageId, ...]:
        """没有任何节点声明认领的状态。

        三类状态**不算数**，因为它们本来就不该有节点：

        * **分类节点**（``kind=GROUP``）—— 自己不参与匹配，定位结果里
          永远不会出现它；
        * **叠加层**（``kind=OVERLAY``）—— 它不是"能待着的位置"，
          而是"主状态之上多了一层"，由主状态的节点负责；
        * **终态状态**（``terminal=True``）进了就结束，也不需要动作。

        剩下的未认领状态**不是错误**：它由 :func:`validate_binding` 在
        启动期拦下（"记录信息的状态必须能被重定位到"）。
        这个方法留给 ``gamebot check`` 做"把整棵树摊开看一眼"的展示。
        """
        claimed = {n.page for n in self.graph.nodes.values() if n.page}
        return tuple(
            p.id
            for p in self.tree.walk()
            if p.id not in claimed
            and not p.is_overlay
            and not p.is_group
            and not p.terminal
        )

    def describe(self) -> str:
        """可读的完整描述，给日志和 ``gamebot check`` 用。"""
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
