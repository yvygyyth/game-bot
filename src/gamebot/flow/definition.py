"""流程层的定义 —— 一份完整的"脚本怎么跑"的声明。

一个 ``FlowDefinition`` 就是脚本的全部流程规则，可以由 YAML 加载，
也可以纯代码构造。它是**只读的蓝图**，运行期的可变状态全在
``FlowMachine`` 和 ``StateStore`` 里 —— 蓝图不因为跑了一轮就变样，
这样才能把同一个定义跑两次做对比。

包含：

* ``states``     —— 识别规则（喂给 ``StateDetector``）
* ``nodes``      —— 每个状态要做的事（喂给引擎）
* ``transitions``—— 状态之间怎么走（喂给 ``FlowMachine``）
* 运行参数       —— tick 间隔、总时长预算、终态、未知状态的应对

校验放在 ``validate()`` 里，装配时调一次，把配置错误挡在启动阶段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..state.definition import StateDefinition, StateId
from ..state.snapshot import UNKNOWN_STATE
from .node import FlowNode
from .transition import Transition

__all__ = ["FlowDefinition", "UnknownPolicy"]


class UnknownPolicy(StrEnum):
    """认不出状态时怎么办。

    "认不出来"是最常见的真实情况（动画中间帧、网络卡住、游戏在加载），
    所以必须显式选一个策略，而不是靠默认行为蒙混。
    """

    WAIT = "wait"
    """原地等，重新截图识别。大多数情况选它。"""

    RELOAD_TICK = "reload_tick"
    """放弃本轮，立刻下一轮。适合识别很便宜的场景。"""

    RECOVERY = "recovery"
    """跳到 ``recovery_state``（比如"回主界面"），主动纠偏。"""

    STOP = "stop"
    """直接停流程并报告。适合"不认识就绝不乱点"的保守场景。"""


@dataclass(slots=True)
class FlowDefinition:
    """流程蓝图。

    :param name: 流程名，进日志和报告。
    :param initial: 起始状态。引擎启动时假定在这里（也用于"回主界面"兜底）。
    :param states: 状态识别定义集合。
    :param nodes: 状态 -> 应对节点。
    :param transitions: 转移规则。
    :param stop_states: 进入即结束流程的状态（如 ``"game_closed"``）。
    :param tick_interval: 每轮之间的最小间隔（秒）。**别给 0** —— 空转只会
        把 CPU 和 adb 打满，还让日志无法阅读。
    :param max_runtime: 整个流程的运行时长上限（秒）；None 不限。
    :param max_ticks: 最大轮数；``0`` 不限。
    :param on_unknown: 未知状态的应对策略。
    :param recovery_state: ``on_unknown == RECOVERY`` 时的目标状态。
    :param unknown_grace: 宽容期（秒）。进入未知状态后的这段时间内不触发策略，
        只是等 —— 因为过场动画本来就会短暂认不出来。
    :param stable_frames: 全局要求的连续命中帧数下限，会被每个状态定义里的
        同名参数覆盖（取较大者）。
    :param meta: 任意附加信息。
    """

    name: str = "flow"
    initial: StateId = UNKNOWN_STATE
    states: list[StateDefinition] = field(default_factory=list)
    nodes: dict[StateId, FlowNode] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    stop_states: tuple[StateId, ...] = ()
    tick_interval: float = 0.2
    max_runtime: float | None = None
    max_ticks: int = 0
    on_unknown: UnknownPolicy = UnknownPolicy.WAIT
    recovery_state: StateId = ""
    unknown_grace: float = 1.0
    stable_frames: int = 1
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    @property
    def state_ids(self) -> list[StateId]:
        return [s.id for s in self.states]

    def state(self, state_id: StateId) -> StateDefinition | None:
        return next((s for s in self.states if s.id == state_id), None)

    def node(self, state_id: StateId) -> FlowNode | None:
        return self.nodes.get(state_id)

    def transitions_from(self, state_id: StateId) -> list[Transition]:
        """源状态匹配 ``state_id`` 的转移，按优先级降序。"""
        matched = [t for t in self.transitions if t.applies_to(state_id)]
        return sorted(matched, key=lambda t: t.priority, reverse=True)

    # ------------------------------------------------------------------ #
    # 校验
    # ------------------------------------------------------------------ #
    def validate(self) -> None:
        """装配期校验。任何一条不满足都抛 ``FlowError``。

        检查项：

        1. ``initial`` 必须能在 ``states`` 里找到（或为 UNKNOWN_STATE）；
        2. 状态 id 不能重复；
        3. 每个 ``FlowNode.state`` 必须有对应的 ``StateDefinition``；
        4. 所有 ``Transition.target`` 必须是已定义状态或 stop_state；
        5. ``Transition.sources`` 里的每个状态都必须已定义；
        6. ``stop_states`` 必须已定义；
        7. 至少要有一个状态定义（否则永远认不出来）；
        8. ``on_unknown == RECOVERY`` 时 ``recovery_state`` 必须已定义。

        :raises FlowError: 校验失败，message 里会带上具体是哪一条。
        """
        raise NotImplementedError("待实现：按上面 8 条逐项检查并收集全部错误后一次性抛出")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "initial": self.initial,
            "states": [s.to_dict() for s in self.states],
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "transitions": [t.to_dict() for t in self.transitions],
            "stop_states": list(self.stop_states),
            "tick_interval": self.tick_interval,
            "max_runtime": self.max_runtime,
            "on_unknown": self.on_unknown.value,
            "recovery_state": self.recovery_state,
        }

    def __repr__(self) -> str:
        return (
            f"FlowDefinition({self.name!r}, states={len(self.states)}, "
            f"nodes={len(self.nodes)}, transitions={len(self.transitions)})"
        )
