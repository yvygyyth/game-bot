"""执行层 —— Step：可执行、可观测、可重试的最小工作单元。

为什么要"步骤"这层抽象，而不是流程层直接调原子方法：

1. **原子方法是"动作"，步骤是"意图"**。``click_point(Point(960, 540))`` 是动作，
   ``"点击开始游戏按钮"`` 才是意图。日志里要看的是后者。
2. **策略集中**。重试 / 超时 / 跳过条件 / 失败处理挂在步骤上，不用每个调用点重复写。
3. **可观测**。每个步骤产出 ``StepOutcome``，能落进 journal，能统计耗时分布，
   能回放 —— 这是以后想接 AI 训练数据时的抓手。
4. **可组合**。流程节点 = 步骤列表，复合步骤 = 步骤树，不用改原子层。

步骤**不截图**（除非它显式需要）：帧从 ``RunContext`` 拿，保证一个 tick 内的
多个步骤看的是同一张图 —— 除非步骤自己声明需要新帧。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from ..types import ActionResult, Point, Region
from .policy import StepPolicy

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from ..context import RunContext

__all__ = [
    "CaptureStep",
    "ClickImageStep",
    "ClickStep",
    "ClickTextStep",
    "CompositeStep",
    "ConditionalStep",
    "FunctionStep",
    "KeyStep",
    "QueryStep",
    "Step",
    "WaitStep",
]


class Step(ABC):
    """一个可执行的工作单元。

    实现者只需关心"做什么"，"失败了怎么办"交给 ``policy``。
    """

    def __init__(
        self,
        name: str = "",
        *,
        policy: StepPolicy | None = None,
        needs_fresh_frame: bool = False,
    ) -> None:
        self.name = name or type(self).__name__
        self.policy = policy if policy is not None else StepPolicy()
        self.needs_fresh_frame = needs_fresh_frame

    @abstractmethod
    def run(self, ctx: RunContext) -> ActionResult[Any]:
        """执行本体。

        :param ctx: 运行时上下文，能拿 ``session`` / 帧 / 黑板 / 状态。
        :return: 统一结果信封。**不要在这里 sleep 重试**，那是执行器的事。
        """
        raise NotImplementedError

    def describe(self) -> str:
        """给日志和报告用的单行描述。子类覆写成更有信息量的形式。"""
        return self.name

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.describe()!r})"


class FunctionStep(Step):
    """把任意 ``Callable[[RunContext], ActionResult]`` 包成步骤。

    临时脚本、一次性逻辑用它，不用为每件小事定义子类。
    """

    def __init__(
        self,
        func: Callable[[RunContext], ActionResult[Any]],
        name: str = "",
        *,
        policy: StepPolicy | None = None,
    ) -> None:
        super().__init__(name or getattr(func, "__name__", "function"), policy=policy)
        self.func = func

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        return self.func(ctx)

    def describe(self) -> str:
        return f"调用 {getattr(self.func, '__name__', repr(self.func))}"


class QueryStep(Step):
    """只查询、不动作。结果写进黑板，供后续步骤 / 转移条件使用。

    例：读取当前体力值并存入 ``ctx.blackboard["stamina"]``。
    """

    def __init__(
        self,
        query: Any,
        *,
        name: str = "",
        save_as: str = "",
        policy: StepPolicy | None = None,
    ) -> None:
        super().__init__(name or f"查询 {query!r}", policy=policy)
        self.query = query
        self.save_as = save_as

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        raise NotImplementedError("待实现：ctx.frame() 上跑 query，成功且 save_as 非空时写黑板")


class CaptureStep(Step):
    """强制刷新当前帧。

    需要"点完之后画面变了，后面几步必须看新图"时，在中间插一个它。
    """

    def __init__(self, *, name: str = "刷新帧", policy: StepPolicy | None = None) -> None:
        super().__init__(name, policy=policy, needs_fresh_frame=True)

    def run(self, ctx: RunContext) -> ActionResult[Frame]:
        raise NotImplementedError("待实现：ctx.capture() 并替换 ctx 的当前帧")


class ClickStep(Step):
    """点击固定坐标（逻辑坐标系）。"""

    def __init__(
        self,
        point: Point,
        *,
        name: str = "",
        button: str = "left",
        clicks: int = 1,
        policy: StepPolicy | None = None,
    ) -> None:
        super().__init__(name or f"点击 {point.as_tuple()}", policy=policy)
        self.point = point
        self.button = button
        self.clicks = clicks

    def run(self, ctx: RunContext) -> ActionResult[Point]:
        raise NotImplementedError("待实现：调 atomic.actions.click_point")


class ClickImageStep(Step):
    """识图并点击 —— 实际脚本里最常用的步骤。"""

    def __init__(
        self,
        template: str,
        *,
        name: str = "",
        region: Region | None = None,
        confidence: float | None = None,
        offset: tuple[int, int] = (0, 0),
        policy: StepPolicy | None = None,
    ) -> None:
        super().__init__(name or f"点击图片 {template}", policy=policy)
        self.template = template
        self.region = region
        self.confidence = confidence
        self.offset = offset

    def run(self, ctx: RunContext) -> ActionResult[Point]:
        raise NotImplementedError("待实现：在 ctx 当前帧上 find_image，再 click")


class ClickTextStep(Step):
    """查文本并点击。"""

    def __init__(
        self,
        text: str,
        *,
        name: str = "",
        region: Region | None = None,
        lang: str = "ch",
        confidence: float = 0.8,
        policy: StepPolicy | None = None,
    ) -> None:
        super().__init__(name or f"点击文本 {text!r}", policy=policy)
        self.text = text
        self.region = region
        self.lang = lang
        self.confidence = confidence

    def run(self, ctx: RunContext) -> ActionResult[Point]:
        raise NotImplementedError("待实现")


class KeyStep(Step):
    """按键或组合键。"""

    def __init__(
        self,
        key: str | Sequence[str],
        *,
        name: str = "",
        presses: int = 1,
        interval: float = 0.1,
        policy: StepPolicy | None = None,
    ) -> None:
        keys = [key] if isinstance(key, str) else list(key)
        super().__init__(name or f"按键 {'+'.join(keys)}", policy=policy)
        self.keys = keys
        self.presses = presses
        self.interval = interval

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        raise NotImplementedError("待实现：单键走 press_key，多键走 hotkey")


class WaitStep(Step):
    """等待类步骤。

    :param query: 等到该查询命中。
    :param seconds: 或者死等固定秒数（二者只能给一个）。
    :param disappear: True 表示等它消失（配合 query 使用）。
    """

    def __init__(
        self,
        *,
        query: Any = None,
        seconds: float | None = None,
        disappear: bool = False,
        timeout: float = 10.0,
        interval: float = 0.3,
        name: str = "",
        policy: StepPolicy | None = None,
    ) -> None:
        if query is None and seconds is None:
            raise ValueError("WaitStep 至少需要 query 或 seconds 之一")
        label = f"等待 {seconds}s" if seconds is not None else f"等待 {query!r}"
        if disappear:
            label = f"等待消失 {query!r}"
        super().__init__(name or label, policy=policy, needs_fresh_frame=True)
        self.query = query
        self.seconds = seconds
        self.disappear = disappear
        self.timeout = timeout
        self.interval = interval

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        raise NotImplementedError(
            "待实现：seconds 走 actions.sleep，否则走 wait_any_of / wait_disappear"
        )


class CompositeStep(Step):
    """把一串步骤当成一个步骤执行。

    用途：让一组操作共享同一个重试 / 超时策略（"整个领奖流程重试两次"），
    或者作为流程节点的复用单元。
    """

    def __init__(
        self,
        steps: Sequence[Step],
        *,
        name: str = "",
        policy: StepPolicy | None = None,
        abort_on_failure: bool = True,
    ) -> None:
        super().__init__(name or f"复合步骤 x{len(steps)}", policy=policy)
        self.steps = list(steps)
        self.abort_on_failure = abort_on_failure

    def run(self, ctx: RunContext) -> ActionResult[list[Any]]:
        raise NotImplementedError("待实现：交给 ctx.executor 逐步执行并汇总")


class ConditionalStep(Step):
    """条件步骤：满足条件才执行内部步骤。

    :param when: 条件查询 / 谓词。
    :param then_steps: 条件成立时执行。
    :param else_steps: 条件不成立时执行（可选）。
    """

    def __init__(
        self,
        when: Any,
        then_steps: Sequence[Step],
        else_steps: Sequence[Step] = (),
        *,
        name: str = "",
        policy: StepPolicy | None = None,
    ) -> None:
        super().__init__(name or "条件步骤", policy=policy)
        self.when = when
        self.then_steps = list(then_steps)
        self.else_steps = list(else_steps)

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        raise NotImplementedError("待实现：在当前帧上求 when，选择分支")


# --------------------------------------------------------------------------- #
# 注册表 —— 新增步骤类型时在这里登记
# --------------------------------------------------------------------------- #
_STEP_REGISTRY: dict[str, type] = {
    "FunctionStep": FunctionStep,
    "QueryStep": QueryStep,
    "CaptureStep": CaptureStep,
    "ClickStep": ClickStep,
    "ClickImageStep": ClickImageStep,
    "ClickTextStep": ClickTextStep,
    "KeyStep": KeyStep,
    "WaitStep": WaitStep,
    "CompositeStep": CompositeStep,
    "ConditionalStep": ConditionalStep,
}


def step_registry() -> dict[str, type]:
    """可用的步骤类型名 -> 类。YAML 里 ``type: ClickImageStep`` 就是查这张表。

    新增步骤类型时必须登记，否则配置驱动的那部分流程就写不出来。
    """
    return dict(_STEP_REGISTRY)

