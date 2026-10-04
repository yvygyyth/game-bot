"""流程层的转移规则 —— "在什么状态下、满足什么条件，就去哪儿"。

一条转移 = 源状态 + 目标状态 + 守卫条件 + 优先级。

设计取舍：

* **转移是声明式的**。能从"当前状态 + 观察到的画面"算出来的，就不要写进代码。
* **守卫默认只看当前帧**。需要"连续 3 次没血才撤退"这类跨帧条件时，
  用黑板上累积的计数器（步骤里写），不要在守卫里 sleep 截图 ——
  守卫必须快速且无副作用。
* **优先级显式给**。同一状态下多个守卫同时成立时，靠 priority 定胜负，
  而不是靠列表顺序 —— 后者在 YAML 里改一行就会静默改变行为。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..state.definition import StateId

if TYPE_CHECKING:
    from ..atomic.query import Query

__all__ = ["Transition", "TransitionKind"]


class TransitionKind(enum.StrEnum):
    """转移类型，用于日志区分和调试。"""

    NORMAL = "normal"
    """常规状态迁移。"""

    FALLBACK = "fallback"
    """兜底：其他都不成立时才走（如"未知状态 -> 重试当前操作"）。"""

    RECOVERY = "recovery"
    """异常恢复：卡住了、超时了、回到主界面。优先级通常最高。"""

    TERMINAL = "terminal"
    """终态：结束流程。"""


@dataclass(frozen=True, slots=True)
class Transition:
    """一条状态转移规则。

    :param target: 目标状态 id。
    :param sources: 允许的源状态；**空元组表示任意状态**。
    :param guard: 守卫查询。None 表示只要处于 source 就直接转移。
        守卫失败会退回 ``not_found``，引擎不因此报错 —— 守卫不成立是正常情况。
    :param priority: 数字大的先判断。
    :param kind: 转移类型，影响日志与引擎的兜底处理。
    :param label: 人类可读说明，会写进 ``StateChange.reason``。
    :param cooldown: 该转移触发后多少秒内不允许再次触发。
        防止"识别抖动导致来回横跳"（A->B->A->B 死循环）。
    :param max_times: 该转移在一轮流程里最多触发几次；``0`` 表示不限。
        用于"重试 3 次就放弃"这类逻辑。
    """

    target: StateId
    sources: tuple[StateId, ...] = ()
    guard: Query | None = None
    priority: int = 0
    kind: TransitionKind = TransitionKind.NORMAL
    label: str = ""
    cooldown: float = 0.0
    max_times: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> str:
        src = "/".join(self.sources) if self.sources else "*"
        return self.label or f"{src} -> {self.target}"

    def applies_to(self, state_id: StateId) -> bool:
        """源状态是否匹配（空 sources = 通配）。"""
        return not self.sources or state_id in self.sources

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": list(self.sources),
            "to": self.target,
            "priority": self.priority,
            "kind": self.kind.value,
            "label": self.label,
            "has_guard": self.guard is not None,
            "cooldown": self.cooldown,
            "max_times": self.max_times,
        }

    def __repr__(self) -> str:
        return f"Transition({self.display!r}, priority={self.priority})"
