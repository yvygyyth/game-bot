"""流程层的节点 —— "处于某个状态时该做哪些事"。

关键区分（**这是整个设计里最容易搞混的地方**）：

* **状态（State）** 是"游戏是什么样"，由状态层识别出来，脚本无权决定。
* **节点（FlowNode）** 是"我们打算做什么"，由脚本决定。

两者通常一一对应（``main_menu`` 状态 -> ``进入战斗`` 节点），但不必一一对应：
同一个状态在不同阶段可能要做不同的事（第一次进主界面领奖励，之后直接开打）。
需要这种区分时，用**显式的前置条件**（``guard``）或让状态定义更细 ——
但不要偷偷在节点里写"如果这是第三次……"，那会把流程逻辑藏进节点，无法调试。

节点里的步骤按顺序执行，任一步骤按其 ``on_error`` 策略决定是继续还是中断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..state.definition import StateId

if TYPE_CHECKING:
    from ..atomic.query import Query
    from ..execution.step import Step

__all__ = ["FlowNode"]


@dataclass(slots=True)
class FlowNode:
    """一个状态的应对方案。

    :param state: 对应的状态 id。
    :param steps: 每次进入该状态要执行的步骤序列。空列表表示"只识别、不动作"
        （常用来做纯等待 / 观察型状态，如 ``loading``）。
    :param on_enter: 首次进入该状态时执行（只执行一次）。
    :param on_exit: 离开该状态时执行。
    :param guard: 进入节点的额外条件；不满足则跳过 steps（但状态本身仍然成立）。
    :param timeout: 节点执行的总时间预算（秒）。超了按 ``on_timeout`` 处理。
    :param on_timeout: 超时后转移到哪个状态；空串表示交给流程的通用兜底。
    :param max_visits: 该节点最多执行几次；``0`` 不限。超了之后只识别不执行，
        避免"原地死循环刷同一个界面"。
    :param cooldown: 两次执行之间的最小间隔（秒）。防止空转打满 CPU。
    :param description: 说明。
    """

    state: StateId
    steps: list[Step] = field(default_factory=list)
    on_enter: list[Step] = field(default_factory=list)
    on_exit: list[Step] = field(default_factory=list)
    guard: Query | None = None
    timeout: float | None = None
    on_timeout: StateId = ""
    max_visits: int = 0
    cooldown: float = 0.0
    description: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.description or f"节点:{self.state}"

    @property
    def is_passive(self) -> bool:
        """只识别不动作的节点。"""
        return not self.steps and not self.on_enter and not self.on_exit

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "steps": len(self.steps),
            "on_enter": len(self.on_enter),
            "on_exit": len(self.on_exit),
            "timeout": self.timeout,
            "max_visits": self.max_visits,
            "cooldown": self.cooldown,
        }

    def __repr__(self) -> str:
        return f"FlowNode({self.state!r}, steps={len(self.steps)})"
