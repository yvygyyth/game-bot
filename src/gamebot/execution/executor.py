"""执行层 —— Executor：跑步骤，把结果记下来。

## 执行器只做三件事

1. 调那个步骤函数，拿到 ``ActionResult``；
2. 失败的步骤存一张当帧（可选），把结果写进 journal / 回调 hooks；
3. 把 ``StepOutcome`` 交回给调用方（流程层）。

**故意不做的事**：

* **不重试** —— 失败（多半是识图没命中）意味着前提没成立，
  上层会拿实测状态去**重定位**，而不是在原地重试。这是这套设计的核心：
  流程写的是"理想的执行状态"，偏离了就归位；
* **不做状态判断 / 流程跳转** —— 那是状态层和流程层的事；
* **不做 ``skip_if`` / ``precondition``** —— 要"满足条件才做"就直接在函数里写
  ``if``，比一套策略 DSL 直白；
* **不按时长中断** —— 想限时就自己在函数里判断，或者用原子层的
  ``wait_*``（它们自带 ``timeout``）。

执行器保持"哑"，才能被复用和测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..types import ActionResult
from ..utils.logging import get_logger
from ..utils.timing import Stopwatch
from ..vision.recorder import prune_old
from .journal import Journal, NullJournal
from .step import StepFunc, step_name

if TYPE_CHECKING:
    from ..context import RunContext

log = get_logger("execution.executor")

#: 失败帧的文件名前缀。
#:
#: **这个前缀不是装饰**：留存清理靠它圈定范围（``fail_*.png``）。名字不带
#: 前缀的话，"清理旧失败帧"要么扫不到（图无限涨），要么只能不带 pattern 地
#: 删 —— 而截图目录里还躺着识图记录和用户手工截的图，误删比涨满更烦。
FAILED_FRAME_PREFIX = "fail_"

__all__ = ["Executor", "ExecutorHooks", "StepOutcome"]


@dataclass(slots=True)
class StepOutcome:
    """一个步骤跑完之后的完整记录。"""

    step: str
    result: ActionResult[Any]
    elapsed: float = 0.0
    children: list[StepOutcome] = field(default_factory=list)
    action: dict[str, Any] = field(default_factory=dict)
    """这次生效的动作描述（``{"kind": "click", "point": [960, 540]}``）。

    从 ``result.meta`` 里拾取常见的几个键填上，给 journal 用 ——
    journal 的格式约定里 ``action`` 是独立字段（方便以后当训练数据的锚点），
    所以不能只丢在 meta 里。
    """

    frame_path: str = ""
    """这次执行时的帧存盘路径（存了才有）。帧**不内联**进 journal。"""

    @property
    def ok(self) -> bool:
        return self.result.ok

    @property
    def status(self) -> str:
        return self.result.status.value

    @property
    def message(self) -> str:
        return self.result.message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step": self.step,
            "status": self.status,
            "elapsed": round(self.elapsed, 4),
            "message": self.message,
        }
        if self.action:
            payload["action"] = self.action
        if self.frame_path:
            payload["frame"] = self.frame_path
        return payload

    def __repr__(self) -> str:
        return f"StepOutcome({self.step!r}, status={self.status}, elapsed={self.elapsed:.3f}s)"


@dataclass(slots=True)
class ExecutorHooks:
    """执行器回调点。默认全空，方便只关心其中几个的场景。"""

    before_step: Any = None
    """``(ctx, step) -> None``"""

    after_step: Any = None
    """``(ctx, outcome) -> None``"""

    on_failure: Any = None
    """``(ctx, step, outcome) -> None``"""


class Executor:
    """步骤执行器。

    :param ctx: 运行时上下文（步骤用它拿 session / 帧 / 黑板 / 参数）。
    :param hooks: 回调。
    :param journal: 落盘记录器；默认不落盘。
    :param dry_run: True 时动作不下发（"空跑一遍看流程走不走得通"）。
        由 ``RunContext.dry_run`` 在原子层执行动作那一刻拦下 ——
        见 :mod:`gamebot.atomic.actions`。
    :param save_frames_on_error: 失败的步骤要不要存一张当帧（排查用）。
    """

    def __init__(
        self,
        ctx: RunContext,
        *,
        hooks: ExecutorHooks | None = None,
        journal: Journal | None = None,
        dry_run: bool = False,
        save_frames_on_error: bool = False,
    ) -> None:
        self.ctx = ctx
        self.hooks = hooks or ExecutorHooks()
        self.journal = journal or NullJournal()
        self.dry_run = dry_run
        # 装配期传进来（不是从 ctx 猜）：执行层不去读流程层的 Options 类型，
        # 由 bootstrap 把这个开关翻译成一个布尔值给它，依赖方向才不乱。
        self.save_frames_on_error = save_frames_on_error
        self.outcomes: list[StepOutcome] = []
        # 空跑：设在 **session** 上 —— 原子动作层拿得到 session，拿不到 ctx
        ctx.session.dry_run = dry_run

    # ------------------------------------------------------------------ #
    def run(self, step: StepFunc) -> StepOutcome:
        """跑一个步骤，返回它的记录。

        **失败不抛异常**（除了 ``Cancelled``，它表示"别再继续了"，
        直接向上穿透）。失败是**返回值**：调用方（流程层）需要看到它，
        才能决定"拿实测状态重新定位"。

        ``dry_run`` 时动作会在原子层被拦下（返回成功但不下发），
        所以这里照常跑 —— "空跑一遍"得到的是一条真实的决策序列。
        """
        watch = Stopwatch()
        started = watch.elapsed
        result = step(self.ctx)
        result = result.with_elapsed(watch.elapsed - started)

        outcome = StepOutcome(step_name(step), result, elapsed=watch.elapsed)
        outcome.action = _action_of(result)
        self._record(step, outcome)
        return outcome

    def run_many(self, steps: list[StepFunc]) -> list[StepOutcome]:
        """顺序执行多个步骤，**某一步失败就停在那里**。

        停下来的理由：一步失败意味着它的前提没成立，而后面步骤的前提正是
        "前一步成功了" —— 继续跑只会在错的状态上乱操作。
        停下来把结果交回流程层，由它拿实测状态重定位。
        """
        outcomes: list[StepOutcome] = []
        for step in steps:
            outcome = self.run(step)
            outcomes.append(outcome)
            if not outcome.ok:
                log.debug("步骤 %r 失败（%s），后面的步骤不跑了", outcome.step, outcome.message)
                break
        return outcomes

    # ------------------------------------------------------------------ #
    def _record(self, step: StepFunc, outcome: StepOutcome) -> None:
        """存失败帧 -> 落 journal + 触发 hooks。

        **帧必须在写 journal 之前存**：``record_outcome`` 会把
        ``outcome.frame_path`` 写进那一条记录里，而 ``attach_frame`` 是往
        ``outcome`` 上回填路径的。顺序反了就变成"日志里说第 3 步失败了，
        但记录里没有图" —— 图其实躺在磁盘上，只是没人告诉你文件名。
        """
        self._save_failure_frame(outcome)
        self.journal.record_outcome(outcome, tick=getattr(self.ctx.pages, "tick", 0))
        self.outcomes.append(outcome)
        if self.hooks.before_step:
            self.hooks.before_step(self.ctx, step)
        if self.hooks.after_step:
            self.hooks.after_step(self.ctx, outcome)
        if not outcome.ok and self.hooks.on_failure:
            self.hooks.on_failure(self.ctx, step, outcome)

    def _save_failure_frame(self, outcome: StepOutcome) -> None:
        """失败的步骤存一张当帧，并把路径写回 ``outcome``。

        三个约束：

        * 只在**失败**时存 —— 成功的步骤存图没有诊断价值，只会堆盘；
        * **有上限**（``_frame_keep``）：失败帧和识图记录躺在同一个目录里，
          各删各的 pattern，否则跑一晚上就是几千张全尺寸 PNG；
        * 存不下来（磁盘满、没权限、抓屏失败）**不抛异常** ——
          可观测性不该把脚本弄挂。

        ## 为什么没帧时**主动抓一张**

        以前这里 ``frame is None`` 就 return。而失败最常见的形态是
        **识图没命中** —— 那一步可能根本没抓过帧（函数里可能连
        ``ctx.frame()`` 都没调）。于是"失败的步骤存一张当帧"在**最需要它的时候
        恰好不生效**，日志里只有一句"没找到"而看不到当时屏幕上是什么。

        所以要存就现抓一张。抓不到（后端出问题）就放弃，不往上抛。
        """
        if outcome.ok or not self.save_frames_on_error:
            return
        frame = self.ctx.current_frame
        if frame is None:
            try:
                frame = self.ctx.frame()
            except Exception:  # pragma: no cover - 抓屏失败不该让脚本挂
                log.debug("失败帧抓取失败，跳过")
                return
        directory = self.ctx.config.paths.resolve(self.ctx.config.paths.screenshots)
        path = self.journal.attach_frame(
            outcome,
            frame,
            directory=directory,
            prefix=FAILED_FRAME_PREFIX,
            tick=int(getattr(self.ctx.pages, "tick", 0)),
        )
        if not path:
            return
        prune_old(Path(directory), f"{FAILED_FRAME_PREFIX}*.png", self._frame_keep)
        log.debug("失败帧已存: %s", path)
        directory = self.ctx.config.paths.resolve(self.ctx.config.paths.screenshots)
        path = self.journal.attach_frame(
            outcome,
            frame,
            directory=directory,
            prefix=FAILED_FRAME_PREFIX,
            tick=int(getattr(self.ctx.pages, "tick", 0)),
        )
        if not path:
            return
        prune_old(Path(directory), f"{FAILED_FRAME_PREFIX}*.png", self._frame_keep)
        log.debug("失败帧已存: %s", path)

    @property
    def _frame_keep(self) -> int:
        """失败帧最多留几张。

        跟着识图记录的上限走（它的 5 倍，至少 20）：两者都在教同一件事
        "留最近那几次就够看了"，没必要再往配置里加一个要用户理解的旋钮。
        """
        recorder = getattr(self.ctx, "recorder", None)
        keep = getattr(recorder, "keep", 0) or 0
        return max(20, keep * 5)

    def close(self) -> None:
        self.journal.close()

    def __enter__(self) -> Executor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


#: ``ActionResult.meta`` 里这几个键会被提到 ``StepOutcome.action`` 上。
#: journal 的格式约定里 ``action`` 是独立字段（方便以后当训练数据的锚点）。
_ACTION_KEYS = (
    "action",
    "kind",
    "point",
    "template",
    "text",
    "key",
    "region",
    "score",
    "rect",
)


def _action_of(result: ActionResult[Any]) -> dict[str, Any]:
    """从结果的 meta 里挑出"这次做了什么"给 journal 用。"""
    meta = result.meta or {}
    return {key: meta[key] for key in _ACTION_KEYS if key in meta}
