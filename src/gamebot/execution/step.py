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

import importlib
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import fields
from typing import TYPE_CHECKING, Any

from ..atomic import actions
from ..atomic.combinators import wait_any_of, wait_disappear
from ..exceptions import ConfigError
from ..types import ActionResult, ActionStatus, Point, Region
from .policy import ErrorMode, RetryPolicy, StepPolicy

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from ..context import RunContext
    from .executor import StepOutcome

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
    "step_from_dict",
]


def _evaluate(condition: Any, ctx: RunContext) -> ActionResult[Any]:
    """在**当前帧**上求一个条件：``Query``（有 ``run(frame)``）或 ``Callable``。

    两条路径都走 ``ctx.frame()``：同一轮里"判断"和"动手"必须看同一张图，
    否则会出现"判断时在、点击时已经消失"这种鬼故事 —— 而 ``ctx.frame()``
    在 TTL 内复用同一帧，正是为了这个。

    条件自己抛异常不往外炸：转成 ``error`` 结果交给调用方。
    **调用方要把它和"不成立"分开处理**（``Executor._check_skip`` 就是
    按"出错则不跳过"来的）。
    """
    try:
        runner = getattr(condition, "run", None)
        if callable(runner):
            return runner(ctx.frame())
        outcome = condition(ctx)
        if isinstance(outcome, ActionResult):
            return outcome
        return ActionResult.success(outcome) if outcome else ActionResult.not_found("条件不成立")
    except Exception as exc:
        return ActionResult.error(f"条件求值异常: {exc}", exc=exc)


class Step(ABC):
    """一个可执行的工作单元。

    实现者只需关心"做什么"，"失败了怎么办"交给 ``policy``。
    """

    performs_action: bool = True
    """这一步会不会**真的操作游戏**（点 / 按 / 拖）。

    只被 ``Executor(dry_run=True)`` 用：空跑时动作步骤不真的下发，只走一遍
    决策流程。**默认 True 是刻意的** —— 自定义步骤忘了声明时，宁可被多拦一次，
    也不能让"空跑"真的去点游戏。只读的步骤（``QueryStep`` / ``CaptureStep``）
    显式覆写成 False。
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

    def used_templates(self) -> tuple[str, ...]:
        """这个步骤会用到的模板名。

        用途只有一个：让 ``gamebot check`` 在**启动之前**告诉你"有张图还没截"。
        模板名拼错、导出时忘了放进 assets，这些问题在运行期表现为
        "跑到某个分支就卡住"，可能十分钟才撞上一次；在这里只是一次路径比较。

        **用模板的步骤应该覆写它**，否则检查会漏报（漏报不会误伤，
        只是少一层保护）。别写猜的 —— 误报会让这个检查失去信任。
        """
        return ()

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
        templates: Sequence[str] = (),
    ) -> None:
        """
        :param templates: 这个函数会用到的模板名。**包的是个普通函数时没法自动
            推断**，所以显式声明一下，``gamebot check`` 才能查到它用到的图::

                FunctionStep(back_to_home, templates=(T_BACK, T_RETRY))
        """
        super().__init__(name or getattr(func, "__name__", "function"), policy=policy)
        self.func = func
        self.templates = tuple(templates)

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        return self.func(ctx)

    def describe(self) -> str:
        return f"调用 {getattr(self.func, '__name__', repr(self.func))}"

    def used_templates(self) -> tuple[str, ...]:
        return self.templates


class QueryStep(Step):
    """只查询、不动作。结果写进黑板，供后续步骤 / 转移条件使用。

    例：读取当前体力值并存入 ``ctx.blackboard["stamina"]``。
    """

    performs_action = False

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
        """在**当前帧**上跑查询。

        没命中时**仍然写黑板**：那里存的是"这一轮看到的值"，
        没看到也是一条信息（后续条件可能要判断"没看到就换策略"）。
        """
        result = _evaluate(self.query, ctx)
        if self.save_as:
            ctx.blackboard.set(self.save_as, result.value)
        return result


class CaptureStep(Step):
    """强制刷新当前帧。

    需要"点完之后画面变了，后面几步必须看新图"时，在中间插一个它。
    """

    performs_action = False

    def __init__(self, *, name: str = "刷新帧", policy: StepPolicy | None = None) -> None:
        super().__init__(name, policy=policy, needs_fresh_frame=True)

    def run(self, ctx: RunContext) -> ActionResult[Frame]:
        """截一张新帧并替换当前帧。

        显式截（``ctx.capture()``）而不是 ``ctx.frame()``：后者的 TTL 命中时
        会**返回旧帧**，那就违背了这一步存在的意义 —— "我确定现在要一张新的"。
        """
        frame = ctx.capture()
        return ActionResult.success(frame, frame_id=frame.frame_id)


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
        """点击一个**逻辑坐标**。

        走 ``click_logic_point``（内部 ``session.to_screen()``），
        和识图得到的源坐标是两个入口 —— 见
        :func:`gamebot.atomic.actions.click_source_point` 里的坐标基准说明。
        """
        return actions.click_logic_point(
            ctx.session, self.point, button=self.button, clicks=self.clicks
        )


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
        """在当前帧上找图并点击。

        两个安全边界，别改：

        * **找不到就绝不点**。返回 ``not_found`` 让重试策略去决定，而不是
          "就近点一下试试" —— 那是识图脚本最危险的失败模式；
        * **点是源坐标**（``click_source_point``）。命中点来自截图，
          再走一次 ``to_screen`` 会二次换算点偏。
        """
        frame = ctx.frame()
        # confidence=None 时由 Frame 回落到 Session 的默认阈值，
        # 这里不要把默认值写死 —— 阈值应该只有一个出处（配置）。
        found = frame.find_image(self.template, region=self.region, confidence=self.confidence)
        if not found.ok:
            return ActionResult(
                found.status,
                None,
                f"{self.template} 未命中，取消点击",
                found.elapsed,
                found.meta,
            )

        hit = found.value
        if hit is None:
            return ActionResult.error(f"{self.template} 命中但没有坐标")

        source = hit.offset(self.offset[0], self.offset[1])
        clicked = actions.click_source_point(ctx.session, source)
        # 点完画面就变了 —— 显式作废当前帧，让后续步骤（和下一轮）看新图。
        # 不在这里重截：截图的时机由流程层决定（CaptureStep / needs_fresh_frame）。
        if clicked.ok:
            ctx.invalidate_frame()
        return clicked.with_meta(
            template=self.template,
            hit_point=hit,
            offset=self.offset,
            score=found.meta.get("score"),
        )

    def used_templates(self) -> tuple[str, ...]:
        return (self.template,)


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
        """在当前帧上查文本并点击。

        同样"找不到就绝不点"，同样点源坐标（命中点来自截图）。
        OCR 没装时 ``find_text`` 返回 ``error``（不是 not_found），
        这里原样透传 —— "OCR 没装"和"文字不在屏幕上"是两件事。
        """
        frame = ctx.frame()
        found = frame.find_text(
            self.text, region=self.region, lang=self.lang, confidence=self.confidence
        )
        if not found.ok:
            return ActionResult(
                found.status,
                None,
                f"文本 {self.text!r} 未命中，取消点击",
                found.elapsed,
                found.meta,
            )

        hit = found.value
        if hit is None:
            return ActionResult.error(f"文本 {self.text!r} 命中但没有坐标")

        clicked = actions.click_source_point(ctx.session, hit)
        if clicked.ok:
            ctx.invalidate_frame()
        return clicked.with_meta(text=self.text, hit_point=hit, score=found.meta.get("score"))


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
        """单键走 ``press_key``，多键走 ``hotkey``（组合键要求同时按下）。"""
        if len(self.keys) == 1:
            return actions.press_key(
                ctx.session, self.keys[0], presses=self.presses, interval=self.interval
            )
        result = actions.hotkey(ctx.session, self.keys)
        if not result.ok:
            return result
        return ActionResult.success(self.keys, elapsed=result.elapsed, keys=list(self.keys))


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
        """固定秒数走 ``actions.sleep``；条件等待走跨帧组合子。

        条件等待的轮询**自己截图**（等的是"画面变过来"，不能复用同一张旧图），
        所以成功之后要把当前帧作废，让后续步骤看新图 —— 组合子抓到的那一帧
        在结果里（``meta["frame"]``），但流程层的帧缓存并不知道它。

        ``timeout``（等不到就超时）和 ``policy.timeout``（这一步的总预算）
        是两回事：前者是这个等待自己的上界，后者含重试。
        """
        if self.seconds is not None:
            return actions.sleep(self.seconds, ctx.session)

        if self.disappear:
            result = wait_disappear(
                ctx.session, self.query, timeout=self.timeout, interval=self.interval
            )
        else:
            result = wait_any_of(
                ctx.session, [self.query], timeout=self.timeout, interval=self.interval
            )
        if result.ok:
            ctx.invalidate_frame()
        return result


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
        self._children: list[StepOutcome] = []

    def run(self, ctx: RunContext) -> ActionResult[list[Any]]:
        """交给 ``ctx.executor`` 逐步执行并汇总。

        **走 executor 而不是自己循环 ``step.run(ctx)``**：子步骤也要吃到
        各自的 ``policy``（重试 / 跳过 / 失败处理）和 journal 记账 ——
        自己循环就等于把这层能力绕过去了，表现是"复合步骤里的重试不生效"。

        内部的 skip **不算失败**（``StepOutcome.ok`` 对 skipped 是 True）：
        "条件不满足所以没做"不是错误。
        """
        outcomes = self._run_children(ctx)
        failures = [o for o in outcomes if not o.ok]
        if failures:
            break_label = "（已中止后续子步骤）" if self.abort_on_failure else ""
            return ActionResult.not_found(
                f"复合步骤 {len(failures)}/{len(outcomes)} 个子步骤失败{break_label}",
                results=[o.to_dict() for o in outcomes],
            )
        return ActionResult.success(
            [o.result.value for o in outcomes],
            results=[o.to_dict() for o in outcomes],
        )

    def child_outcomes(self) -> list[StepOutcome]:
        """最近一次执行里子步骤的结果。

        协议方法：**执行层**和**流程层**约定用它把子步骤结果挂到父 outcome 上
        （引擎只用鸭子类型调它，不去 import 具体的步骤类型）。
        """
        return list(self._children)

    def _run_children(self, ctx: RunContext) -> list[StepOutcome]:
        self._children = []
        for step in self.steps:
            outcome = self._run_one(step, ctx)
            self._children.append(outcome)
            if self.abort_on_failure and not outcome.ok:
                break
        return list(self._children)

    def _run_one(self, step: Step, ctx: RunContext) -> StepOutcome:
        """单个子步骤：优先交给 executor（带策略与记账），没有就退回裸执行。

        裸执行**只应该出现在临时脚本里**（``ctx.executor`` 为空）。
        这时给它包一个最小 outcome，至少让报告里能看到这一步跑了。
        """
        from .executor import StepOutcome

        executor = getattr(ctx, "executor", None)
        if executor is not None:
            return executor.run(step)
        try:
            result = step.run(ctx)
        except Exception as exc:  # 裸路径下把异常转成结果，别炸掉整轮
            result = ActionResult.error(f"子步骤 {step.describe()} 异常: {exc}", exc=exc)
        return StepOutcome(step.name, result)

    def used_templates(self) -> tuple[str, ...]:
        return tuple(t for step in self.steps for t in step.used_templates())


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
        self._children: list[StepOutcome] = []

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        """在当前帧上求 ``when``，选一支执行。

        条件求值**出错**时走 else 分支并把错误写进 message：
        这一步本身不该因为"条件坏了"而变成失败（配置问题该在
        ``_check_skip`` / 边条件那里暴露），但也不能静默 —— message 里带上原因。
        """
        condition = _evaluate(self.when, ctx)
        branch, label = (self.then_steps, "then") if condition.ok else (self.else_steps, "else")
        if not branch:
            return ActionResult.success(
                None,
                message=f"条件{'成立' if condition.ok else '不成立'}，{label} 分支为空",
                branch=label,
                condition=condition.message,
            )

        outcomes: list[StepOutcome] = []
        executor = getattr(ctx, "executor", None)
        for step in branch:
            if executor is not None:
                outcomes.append(executor.run(step))
            else:
                from .executor import StepOutcome

                outcomes.append(StepOutcome(step.name, step.run(ctx)))
        self._children = outcomes

        failures = [o for o in outcomes if not o.ok]
        if failures:
            return ActionResult.not_found(
                f"{label} 分支 {len(failures)}/{len(outcomes)} 个子步骤失败",
                results=[o.to_dict() for o in outcomes],
                branch=label,
            )
        return ActionResult.success(
            [o.result.value for o in outcomes],
            results=[o.to_dict() for o in outcomes],
            branch=label,
            condition=condition.message,
        )

    def child_outcomes(self) -> list[StepOutcome]:
        """最近一次执行里被选中的那一支的子步骤结果。"""
        return list(self._children)

    def used_templates(self) -> tuple[str, ...]:
        nested = [*self.then_steps, *self.else_steps]
        return tuple(t for step in nested for t in step.used_templates())


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


# --------------------------------------------------------------------------- #
# 反序列化（YAML -> Step）
# --------------------------------------------------------------------------- #
def step_from_dict(data: Any) -> Step:
    """把配置里的一个步骤还原成 :class:`Step` 对象。

    :raises ConfigError: 类型没登记、字段拼错、嵌套结构不对。
        **一律抛错而不是跳过**：静默忽略拼错一个键，表现是"这一步跑起来
        什么都没做"，那种 bug 要跑上十分钟才撞得到一次。
    """
    if isinstance(data, Step):
        return data
    if not isinstance(data, dict):
        raise ConfigError(f"步骤定义必须是映射(mapping)，收到: {type(data).__name__}")

    payload = dict(data)
    type_name = str(payload.pop("type", "")).strip()
    if not type_name:
        raise ConfigError(f"步骤定义缺少 type: {data!r}")

    cls = _STEP_REGISTRY.get(type_name)
    if cls is None:
        known = ", ".join(sorted(_STEP_REGISTRY))
        raise ConfigError(f"未登记的步骤类型 {type_name!r}。可用的有: {known}")

    if "policy" in payload:
        payload["policy"] = _policy_from_dict(payload["policy"])

    if cls is CompositeStep and isinstance(payload.get("steps"), (list, tuple)):
        payload["steps"] = [step_from_dict(item) for item in payload["steps"]]
    if cls is ConditionalStep:
        if isinstance(payload.get("when"), (dict, str)):
            payload["when"] = query_from_config(payload["when"])
        for key in ("then_steps", "else_steps"):
            if isinstance(payload.get(key), (list, tuple)):
                payload[key] = [step_from_dict(item) for item in payload[key]]
    if cls is FunctionStep:
        payload["func"] = _resolve_function(payload.get("func"))
    for key in ("query",):
        if isinstance(payload.get(key), (dict, str)):
            payload[key] = query_from_config(payload[key])

    if "point" in payload and not isinstance(payload["point"], Point):
        payload["point"] = _point_from_config(payload["point"])
    if payload.get("region") is not None and not isinstance(payload["region"], Region):
        payload["region"] = _region_from_config(payload["region"])
    if "offset" in payload and isinstance(payload["offset"], (list, tuple)):
        payload["offset"] = tuple(payload["offset"])

    # 对**类本身**取签名（``inspect.signature(cls)`` 会自动跳过 self），
    # 而不是对 ``cls.__init__`` 取 —— 后者在 mypy 看来是"对实例取 __init__"，
    # 而实例的 __init__ 可能来自不兼容的子类。
    #
    # 踩过：写成 ``type(cls).__init__`` 是错的 —— ``cls`` 已经是类，
    # ``type(cls)`` 是它的**元类**，于是 allowed 里全是元类构造函数的参数名，
    # 每一个合法字段都被判成"未知字段"（9 个用例如例全红）。
    allowed = set(inspect.signature(cls).parameters) - {"args", "kwargs"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ConfigError(
            f"{type_name} 有未知字段: {', '.join(unknown)}（可用: {sorted(allowed)}）"
        )

    try:
        return cls(**payload)
    except TypeError as exc:
        raise ConfigError(f"{type_name} 的参数不对: {exc}") from exc


def query_from_config(value: Any) -> Any:
    """委托给原子层的 ``query_from_dict``（延迟 import，避免循环依赖）。"""
    from ..atomic.query import query_from_dict

    try:
        return query_from_dict(value)
    except ValueError as exc:
        raise ConfigError(f"查询解析失败: {exc}") from exc


def _policy_from_dict(data: Any) -> StepPolicy:
    """``policy`` 子字典 -> :class:`StepPolicy`（含 ``retry`` 子字典）。"""
    if isinstance(data, StepPolicy):
        return data
    if not isinstance(data, dict):
        raise ConfigError(f"policy 必须是映射(mapping)，收到: {type(data).__name__}")

    payload = dict(data)
    if isinstance(payload.get("retry"), dict):
        payload["retry"] = _retry_from_dict(payload["retry"])
    if isinstance(payload.get("on_error"), str):
        payload["on_error"] = _coerce_enum(ErrorMode, payload["on_error"], "policy.on_error")
    for key in ("precondition", "skip_if"):
        if isinstance(payload.get(key), (dict, str)):
            payload[key] = query_from_config(payload[key])

    allowed = {f.name for f in fields(StepPolicy)}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ConfigError(f"policy 里有未知字段: {', '.join(unknown)}（可用: {sorted(allowed)}）")
    return StepPolicy(**payload)


def _retry_from_dict(data: dict[str, Any]) -> RetryPolicy:
    """``retry`` 子字典 -> :class:`RetryPolicy`。

    ``retry_on`` 接受字符串列表（``["not_found", "timeout"]``）：
    配置里写枚举值名（``NOT_FOUND``）不自然，写 ``.value``（``not_found``）
    才对得上日志里看到的东西。
    """
    payload = dict(data)
    raw_statuses = payload.get("retry_on")
    if isinstance(raw_statuses, (list, tuple)):
        payload["retry_on"] = tuple(
            _coerce_enum(ActionStatus, item, "retry.retry_on") for item in raw_statuses
        )
    elif isinstance(raw_statuses, str):
        payload["retry_on"] = (_coerce_enum(ActionStatus, raw_statuses, "retry.retry_on"),)

    allowed = {f.name for f in fields(RetryPolicy)}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ConfigError(f"retry 里有未知字段: {', '.join(unknown)}（可用: {sorted(allowed)}）")
    return RetryPolicy(**payload)


def _coerce_enum(enum_cls: type, value: Any, where: str) -> Any:
    """把配置里的字符串转成枚举；大小写和下划线都容忍一点。"""
    if isinstance(value, enum_cls):
        return value
    text = str(value).strip().lower()
    try:
        return enum_cls(text)
    except ValueError:
        pass
    try:
        return enum_cls(text.upper())
    except ValueError as exc:
        choices = ", ".join(m.value for m in enum_cls)  # type: ignore[attr-defined]
        raise ConfigError(f"{where} 的值 {value!r} 不认识（可用: {choices}）") from exc


def _region_from_config(value: Any) -> Region:
    """``region`` 三种写法都收：``[x,y,w,h]`` / ``{x,y,w,h}`` / ``Region``。"""
    if isinstance(value, Region):
        return value
    if isinstance(value, dict):
        return Region.from_dict(value)
    if isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise ConfigError(f"region 需要 4 个数字 [x,y,w,h]，收到: {value!r}")
        return Region.from_tuple(tuple(int(v) for v in value))  # type: ignore[arg-type]
    raise ConfigError(f"region 的写法不认识: {value!r}（用 [x,y,w,h] 或 {{x,y,w,h}}）")


def _point_from_config(value: Any) -> Point:
    """``point`` 三种写法：``[x,y]`` / ``{x,y}`` / ``Point``。"""
    if isinstance(value, Point):
        return value
    if isinstance(value, dict):
        return Point.from_dict(value)
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ConfigError(f"point 需要 2 个数字 [x,y]，收到: {value!r}")
        return Point.from_tuple(tuple(int(v) for v in value))  # type: ignore[arg-type]
    raise ConfigError(f"point 的写法不认识: {value!r}（用 [x,y] 或 {{x,y}}）")


def _resolve_function(path: Any) -> Callable[..., Any]:
    """``"包.模块.函数"`` -> 可调用对象。

    逃生舱：配置里写不出复杂逻辑时，指向一个 Python 函数。
    **必须在装配期解析失败**（找不到模块/属性就报错），
    否则会拖到运行期变成"跑到这一步才炸"。
    """
    if callable(path):
        return path
    if not isinstance(path, str) or not path.strip():
        raise ConfigError(f"FunctionStep 的 func 必须是 '模块.函数' 形式，收到: {path!r}")

    target = path.strip()
    if "." not in target:
        raise ConfigError(f"FunctionStep 的 func 需要完整路径（'模块.函数'），收到: {target!r}")

    module_path, _, attr = target.rpartition(".")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ConfigError(f"FunctionStep 找不到模块 {module_path!r}: {exc}") from exc

    func = getattr(module, attr, None)
    if not callable(func):
        raise ConfigError(f"FunctionStep 的 {module_path!r} 里没有可调用的 {attr!r}")
    return func
