"""执行层的策略对象 —— 重试、超时、失败处理。

原子层**故意不管**重试与超时，因为"失败怎么办"是业务决策，不是技术细节：

* 找"开始按钮"没找到 → 重试 3 次，还不行就报错停下（人在电脑前看着）
* 找"战斗结算画面"没找到 → 一直等到超时 60s（游戏本来就要打一会儿）
* 点技能失败 → 无所谓，继续（下一轮循环会再点）

把这些写成策略对象而不是散在代码里的 ``for + sleep``，好处是：可配置、可复现、
能被流程层统一统计（"这个步骤这轮重试了几次"）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from ..types import ActionStatus

if TYPE_CHECKING:
    from ..atomic.query import Query

__all__ = ["NO_RETRY", "ErrorMode", "RetryPolicy", "StepPolicy"]


class ErrorMode(StrEnum):
    """步骤彻底失败（重试也没救）之后怎么办。"""

    RAISE = "raise"
    """抛 ``StepFailed``，中断整个流程。适合"关键前置条件没满足，继续跑没意义"。"""

    CONTINUE = "continue"
    """记一笔，继续下一步。适合"锦上添花"的操作：签到、领奖励、点掉广告。"""

    STOP_FLOW = "stop_flow"
    """不抛异常，但让流程引擎优雅停下并给出原因。适合"游戏崩了/回到桌面了"。"""

    ABORT_TICK = "abort_tick"
    """放弃本轮 tick，等下一轮重来。适合"当前状态没准备好，下个 tick 再说"。"""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """重试策略。

    :param max_attempts: 总尝试次数（含第一次）。``1`` 表示不重试。
    :param interval: 两次尝试之间的等待（秒）。
    :param backoff: 间隔倍率。``1.0`` 等间隔；``1.5`` 指数退避。
    :param retry_on: 哪些状态算"可重试"。默认三种失败都重试。
        注意 ``error``：后端崩了通常重试没用，但网络抖动导致的 adb 断连重试有效，
        所以默认包含，需要时按步骤收紧。
    """

    max_attempts: int = 1
    interval: float = 0.2
    backoff: float = 1.0
    retry_on: tuple[ActionStatus, ...] = (
        ActionStatus.NOT_FOUND,
        ActionStatus.TIMEOUT,
        ActionStatus.ERROR,
    )

    @property
    def enabled(self) -> bool:
        return self.max_attempts > 1

    def delay_for(self, attempt: int) -> float:
        """第 ``attempt`` 次失败后该等多久（attempt 从 1 开始）。"""
        return self.interval * (self.backoff ** (attempt - 1))

    def should_retry(self, attempt: int, status: ActionStatus) -> bool:
        """是否还有次数、且该状态可重试。"""
        return attempt < self.max_attempts and status in self.retry_on


NO_RETRY = RetryPolicy(max_attempts=1)
"""不重试的常用常量。"""


@dataclass(frozen=True, slots=True)
class StepPolicy:
    """单个步骤的完整执行策略。

    :param timeout: 该步骤总耗时上限（含所有重试）；None 表示不限制。
    :param retry: 重试策略。
    :param on_error: 失败后的处理方式。
    :param precondition: 前置条件查询。**不满足则跳过该步骤**（不算失败）。
        例：先确认弹窗出现，才执行"点确认"。
    :param skip_if: 满足则跳过。例：已经满体力就不用吃体力药。
    :param require_success: True 时把 not_found 也当作致命错误处理。
        等价于"这一步必须成"。
    :param tag: 标签，用于统计和日志过滤（如 ``"daily"`` / ``"battle"``）。
    """

    timeout: float | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    on_error: ErrorMode = ErrorMode.CONTINUE
    precondition: Query | None = None
    skip_if: Query | None = None
    require_success: bool = False
    tag: str = ""

    @classmethod
    def once(cls, **kwargs: object) -> StepPolicy:
        """一次性、失败就继续。最常用的默认值，写起来短一点。"""
        return cls(**kwargs)  # type: ignore[arg-type]

    @classmethod
    def must(cls, **kwargs: object) -> StepPolicy:
        """必须成功，否则抛异常中断流程。"""
        return cls(require_success=True, on_error=ErrorMode.RAISE, **kwargs)  # type: ignore[arg-type]

    @classmethod
    def patient(
        cls,
        attempts: int = 3,
        interval: float = 0.5,
        **kwargs: object,
    ) -> StepPolicy:
        """会重试的耐心策略。"""
        return cls(retry=RetryPolicy(max_attempts=attempts, interval=interval), **kwargs)  # type: ignore[arg-type]
