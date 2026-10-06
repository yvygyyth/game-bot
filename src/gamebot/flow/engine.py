"""流程层的引擎 —— 主循环。

## 一轮 tick 的完整数据流

```
(1) frame = ctx.frame()                       拿帧（TTL 内复用，否则重截）
(2) expected = binding.expects(cursor.current) 流程层自己的预期 = 当前节点声明的状态
    match = tree.locate(frame, hint=tracker.current_id, expected=expected)
            快路径：先精确验 expected（只探那一页），不成再按 hint 少试几支
(3) tracker.update(match)                      跟踪层：连续几帧了 / 从何时起
(4) 终态判断（stop_pages / 状态的 terminal）
(5) 锚点 == expected ？
      是 -> 校验通过，执行节点步骤；状态没能确认前不动手
      否 -> 意外：
           a. 慢路径 tree.recover(frame, near=expected) 从最近的末梢逐步扩散
           b. binding.node_for(真锚点) 问出"这归哪个节点管"
           c. 游标落到那个节点（重定位），本轮不执行 —— 先把位置摆正
           d. 留一条 Recovery 记录：从哪个状态到哪个状态、试过谁
(6) cursor.step()                              时间：条件满足就换目标
(7) 检查预算（时长 / 轮数），sleep(tick_interval)
```

## 三个关键语义

**一、正常路径是"直着走"的。** 流程层只写正常流程：不写 ``page`` 的节点
完全不校验状态，做完一步就走下一步。这就是"业务流程只关心正常流程"的实现方式。

**二、意外路径靠状态树救回来。** 第 (6) 步自检不过时才付"末梢优先 + 逐步扩散"
的代价（:meth:`gamebot.state.page.PageTree.recover`）。每轮都跑扩散搜索等于
每帧探测全树 —— 那和树存在的意义（剪枝）正好相反。

**三、重定位是显式的、可解释的。** 跳到哪个节点由 :class:`StateBinding` 决定
（"记录信息的状态一定有流程节点认领"是启动期就校验过的不变式），
而且每次都进 :attr:`RunReport.recoveries` —— 排查"它怎么跑那儿去了"
永远有答案，不用猜。

第 (8) 步的 sleep 和所有等待一样是可中止的（``ctx.sleep`` → ``Event.wait``），
所以点了停止是毫秒级响应，不是等满这一轮。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..exceptions import Cancelled, FlowError
from ..state.page import UNKNOWN_PAGE, PageId, PageLeaf
from ..state.tracker import PageChange, PageTracker
from ..utils.logging import get_logger
from ..utils.timing import Stopwatch, humanize
from .binding import StateBinding
from .graph import Decision, GraphCursor, Node, NodeId
from .scenario import Scenario, UnknownPolicy

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..atomic.frame import Frame
    from ..context import RunContext
    from ..execution.executor import Executor, StepOutcome
    from ..execution.step import StepFunc

log = get_logger("flow.engine")

__all__ = ["FlowEngine", "RunReport", "StopReason"]


class StopReason(StrEnum):
    """流程为什么停。报告里必须给出这个，否则"脚本跑完没跑完"说不清。"""

    STOP_PAGE = "stop_page"
    """进入了 stop_pages 里的页面（正常结束）。"""

    TERMINAL_NODE = "terminal_node"
    """停在了终态节点。"""

    MAX_RUNTIME = "max_runtime"
    """到了总时长预算。"""

    MAX_TICKS = "max_ticks"
    """到了轮数预算。"""

    USER = "user"
    """外部请求中止（UI 停止按钮 / Ctrl+C）。"""

    UNKNOWN = "unknown"
    """长时间认不出页面，且策略是 STOP。"""

    ERROR = "error"
    """未捕获异常，流程带着错误停下。"""

    COMPLETED = "completed"
    """一次性流程自然跑完（没有可做的事且没有出边）。"""

    NO_MORE_WORK = "no_more_work"
    """末梢节点连续几轮没事可做 —— **流程走到头了**。

    和 ``COMPLETED`` 的区别在"为什么停"：``COMPLETED`` 是引擎自己走到头
    （比如起点就是终点），而这个是"节点没有出边、步骤又找不到活儿"。
    分开是因为这两种情况要处理的事不一样：后者通常意味着
    **业务的下一段还没写**（名将杀就卡在"匹配页还没定义"）。
    """


#: 末梢节点上连续这么多轮 ``not_found`` 就认为"流程走完了"。**默认值**，
#: 实际取值看 ``EngineOptions.dead_end_rounds``（游戏过渡慢时调大，0 = 关掉）。
#:
#: 为什么是 3：一轮的 ``not_found`` 可能只是界面正在过渡（点了按钮之后的动画、
#: 网络延迟）。连着三轮都找不到，才值得下"没活儿了"的结论。
DEAD_END_STALL_ROUNDS = 3


@dataclass(slots=True)
class Recovery:
    """一次重定位的完整记录。

    **这是"允许自动跳"的代价与回报**：代价是引擎会自己移动游标，
    回报是那次移动永远有据可查。字段刻意一个都不省：

    :param expected: 流程层以为自己在哪（= 被跳过那个节点声明的状态）。
    :param actual: 状态层说真实在哪。
    :param to_node: 最终落到哪个节点；``None`` 表示"认出来了但没人认领"。
    :param attempts: 慢路径（末梢优先 + 逐步扩散）试过谁、为什么没中。
        排查"为什么最后认成了这个"只能靠它。
    """

    at: float = 0.0
    tick: int = 0
    from_node: NodeId = ""
    expected: PageId = ""
    actual: PageId = ""
    to_node: NodeId | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "at": round(self.at, 4),
            "from_node": self.from_node,
            "expected": self.expected,
            "actual": self.actual,
            "to_node": self.to_node,
            "attempts": self.attempts,
        }

    def __repr__(self) -> str:
        target = self.to_node or "<无人认领>"
        return f"Recovery({self.expected!r} -> {self.actual!r} => {target!r})"


@dataclass(slots=True)
class RunReport:
    """一次运行的完整报告。**排查问题的第一手材料**，不要精简字段。"""

    scenario: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    ticks: int = 0
    stop_reason: StopReason = StopReason.COMPLETED
    stop_message: str = ""
    initial_page: PageId = ""
    final_page: PageId = ""
    final_node: NodeId = ""
    changes: list[PageChange] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    """转移决策轨迹。**没走成的那次也在里面** —— "为什么它不动"靠这个回答。"""

    recoveries: list[Recovery] = field(default_factory=list)
    """重定位轨迹。**每次自动跳都在里面** —— "它怎么跑那儿去了"靠这个回答。"""

    outcomes: list[StepOutcome] = field(default_factory=list)
    blackboard: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    @property
    def step_count(self) -> int:
        return len(self.outcomes)

    @property
    def failed_steps(self) -> list[StepOutcome]:
        return [o for o in self.outcomes if not o.ok]

    @property
    def ok(self) -> bool:
        """这次运行算不算"正常结束"。

        ``max_ticks`` / ``max_runtime`` **算正常** —— 那是你设的预算用完了，
        不是出错。把它们算成失败的话，"跑满 3 轮看看流程对不对"这种最常用的
        调试方式会永远返回非零，退出码就失去意义了。
        """
        return self.stop_reason in (
            StopReason.STOP_PAGE,
            StopReason.TERMINAL_NODE,
            StopReason.COMPLETED,
            StopReason.NO_MORE_WORK,
            StopReason.USER,
            StopReason.MAX_TICKS,
            StopReason.MAX_RUNTIME,
        )

    def summary(self) -> str:
        return (
            f"脚本 {self.scenario!r} 结束: {self.stop_reason.value} "
            f"({self.stop_message or '无说明'}), "
            f"{self.ticks} 轮 / {self.step_count} 步 / 耗时 {humanize(self.duration)}, "
            f"{self.initial_page} -> {self.final_page} @ {self.final_node}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "stop_reason": self.stop_reason.value,
            "stop_message": self.stop_message,
            "ticks": self.ticks,
            "duration": round(self.duration, 3),
            "initial_page": self.initial_page,
            "final_page": self.final_page,
            "final_node": self.final_node,
            "changes": [c.to_dict() for c in self.changes],
            "decisions": [d.to_dict() for d in self.decisions],
            "recoveries": [r.to_dict() for r in self.recoveries],
            "steps": [o.to_dict() for o in self.outcomes],
            "errors": self.errors,
        }


class FlowEngine:
    """流程主循环。

    :param scenario: 蓝图（状态树 + 流程图 + 参数）。
    :param ctx: 运行时上下文（提供 session / 帧 / 黑板 / 中止）。
    :param executor: 执行器；None 时用 ``ctx.executor``。
    :param tracker: 页面跟踪器；None 时用 ``ctx.pages``。
    """

    def __init__(
        self,
        scenario: Scenario,
        ctx: RunContext,
        *,
        executor: Executor | None = None,
        tracker: PageTracker | None = None,
        start_node: NodeId = "",
        params: Mapping[str, Any] | None = None,
    ) -> None:
        """
        :param start_node: 从哪个节点开始跑；留空 = ``graph.initial``。

            **用途是调试**：想测"战斗结束"那条分支，不用真从头把游戏玩到那一步 ——
            把游戏手动摆到对应状态、选那个节点、点开始就行。
            没有它，调一条后期分支的成本是"每次重跑整个流程"。

            注意起始节点**不影响状态校验**：它声明的 ``page`` 和实测不符时，
            引擎会走重定位（跳到真正该在的节点），而不是硬着头皮执行。
        :param params: **运行参数（入参）**。开跑前写进上下文，步骤用
            ``ctx.param("farm.rounds", 3)`` 读。

            为什么需要它：``Scenario`` 是在 ``build_scenario()`` 里构造的**静态对象**
            （那次调用拿不到任何运行期信息），而"这次刷几局""用哪套阈值"要等到
            点开始才知道。参数是这次运行的**输入**，和黑板那种"跑出来的状态"
            不是一回事 —— 见 :meth:`RunContext.param`。
        """
        self.scenario = scenario
        self.ctx = ctx
        self.executor = executor or getattr(ctx, "executor", None)
        self.tracker: PageTracker = tracker or ctx.pages
        # 单一事实源：状态校验读的是 ctx.page，而 ctx.page 来自 ctx.pages。
        # 注入的 tracker 必须同步给 ctx，否则会出现"引擎按 A 判断位置、
        # 跟踪层按 B 判断"—— 两边结论可能相反，而且**只在注入时才复现**。
        # 刻意不用 assert 兜：python -O 会把 assert 抹掉，这种保证必须是结构性的。
        ctx.pages = self.tracker
        self.start_node = start_node or scenario.graph.initial
        if start_node and scenario.graph.node(start_node) is None:
            raise FlowError(f"起始节点不存在: {start_node!r}")
        # 状态 ↔ 节点的关联表：动前校验 / 重定位去向 / 动后预期都靠它
        self.binding = StateBinding(scenario.graph, scenario.tree)
        self.cursor = GraphCursor(scenario.graph, current=self.start_node)
        self.report = RunReport(scenario=scenario.name)

        self._stop_reason: StopReason | None = None
        self._stop_message = ""
        self._unknown_since: float | None = None
        #: 当前节点上连续多少轮"没找到可做的事"（判"流程走完了"用，见 _note_stall）
        self._stall_rounds = 0
        self._recovery_warned: set[tuple[NodeId, PageId]] = set()
        self.params: dict[str, Any] = dict(params or {})
        """运行参数（入参）的**引擎侧**那一份，开跑时合进上下文。

        和上下文里那份的关系：装配期可能已经往 ``ctx`` 放过参数（比如 CLI 传的），
        这份是"装配之后再补"的。两边**合并**，引擎这边优先。
        """

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    @property
    def running(self) -> bool:
        return self._stop_reason is None

    def stop(self, reason: StopReason = StopReason.USER, message: str = "") -> None:
        """请求停止。可以在任意时刻调用（包括 hooks 里、信号处理里、别的线程）。

        **同时把中止传给 ``ctx``**，这一点很关键：``ctx.stop_requested`` 是
        ``ctx.sleep()`` / 跨帧等待 / 重试退避能不能"被立刻唤醒"的唯一依据。
        只设本对象的标志位的话，循环要等当前这一觉睡完才看得到 ——
        而这一觉可能是节点声明的 ``cooldown``（若干秒）。
        表现就是"点了停止但脚本还在转"，正是这个项目一直在防的那个 bug。

        （两处的关系：``_stop_reason`` 决定**报告怎么写**，
        ``ctx`` 那边的标志决定**能不能马上醒**。两个都要设。）
        """
        if self._stop_reason is None:
            self._stop_reason = reason
            self._stop_message = message
            log.info("流程停止请求: %s %s", reason.value, message)
        self.ctx.request_stop(message or reason.value)

    def run(
        self,
        on_tick: Callable[[FlowEngine, StepOutcome | None], None] | None = None,
    ) -> RunReport:
        """跑完整个流程，返回报告。

        循环控制（这部分是完整的）：

        * 每轮先检查 ``max_runtime`` / ``max_ticks`` / 外部中止请求；
        * 一轮结束 ``ctx.sleep(tick_interval)``（**可被中止立刻唤醒**）；
        * 异常一律收进 ``report.errors`` 并停止，不往上抛 ——
          脚本跑到一半崩掉时，报告比 traceback 有用得多。

        :param on_tick: 每轮结束后的回调 ``(engine, 本轮结果)``。
            给**外部观察者**用：UI 把状态推到界面上、测试要在"轮与轮之间"
            做点什么（比如让模拟画面跟上来）。刻意做成回调，而不是让调用方
            自己循环 ``tick()`` —— 后者会绕开 ``run()`` 的预算检查、异常兜底
            和报告收集（``report.outcomes`` 只在 ``run()`` 里从 executor 收过来，
            而且每调一次 ``run()`` 就重置一次报告）。
            回调里抛异常按流程异常处理（会被记进 ``report.errors`` 并停止）——
            观察者的问题不该被静默吞掉。
        """
        options = self.scenario.options
        self.scenario.validate()

        # 1) 清引擎**自己**的运行期状态。
        #
        # `_stop_reason` 不清的后果很严重：`running` 就是"它是不是 None"，
        # 而 `run()` 的循环是 `while self.running` —— 跑完第一遍之后它不再是
        # None，于是**第二遍一进循环就退出、一个步骤都不做**，报告还写着
        # COMPLETED。看起来"什么都没发生"，因为确实什么都没发生。
        # （这条是 test_run_params 里"跑三遍"那个用例逼出来的。）
        self._stop_reason = None
        self._stop_message = ""
        self._unknown_since = None
        self._stall_rounds = 0
        self._recovery_warned.clear()

        # 2) 清运行期上下文：跟踪器（当前状态 + 变更历史）、黑板、中止标志、
        # 缓存的帧。同一个引擎跑第二遍时黑板会带着上一遍的数据 —— 那会让
        # "第一次"和"第二次"行为不同，而且极难查。
        self.ctx.reset()

        # 3) 合入运行参数（入参）。**合并**而不是覆盖：装配期可能已经往 ctx 放过
        # （CLI 传的），引擎这份优先。顺序在 reset **之后** —— 参数不是运行期状态，
        # reset 不会碰它，但放后面更保险（不依赖"reset 不动参数"这个约定）。
        if self.params:
            merged = dict(self.ctx.params)
            merged.update(self.params)
            self.ctx.set_params(merged)

        watch = Stopwatch()
        self.report.started_at = self.ctx.now()
        self.report.initial_page = self.tracker.current_id
        # 从配置的起始节点开始（不是 graph.initial）—— 起点是运行参数的一部分
        self.cursor.reset(to=self.start_node)
        log.info(
            "脚本 %r 启动: 起始节点 %s, 初始页面 %s",
            self.scenario.name,
            self.start_node,
            self.tracker.current_id,
        )

        try:
            while self.running:
                if options.max_runtime is not None and watch.elapsed >= options.max_runtime:
                    self.stop(StopReason.MAX_RUNTIME, f"超过 {options.max_runtime}s 预算")
                    break
                if options.max_ticks and self.report.ticks >= options.max_ticks:
                    self.stop(StopReason.MAX_TICKS, f"超过 {options.max_ticks} 轮")
                    break
                if self.ctx.stop_requested:
                    self.stop(StopReason.USER, self.ctx.stop_reason)
                    break

                self.report.ticks += 1
                self.tracker.advance_tick()
                outcome = self.tick()
                if on_tick is not None:
                    on_tick(self, outcome)
                if self.running:
                    self.ctx.sleep(self._tick_interval())
        except KeyboardInterrupt:  # pragma: no cover - 人工中断
            self.stop(StopReason.USER, "用户中断 (Ctrl+C)")
        except Cancelled as cancelled:
            # 中止不是错误：报告里必须写成"外部请求停止"，
            # 否则一次正常的中止会被记成 ERROR，看报告的人会以为脚本崩了。
            self.stop(StopReason.USER, cancelled.reason)
        except Exception as exc:
            log.exception("流程异常终止")
            self.report.errors.append(f"{type(exc).__name__}: {exc}")
            self.stop(StopReason.ERROR, str(exc))

        self.report.ended_at = self.ctx.now()
        self.report.stop_reason = self._stop_reason or StopReason.COMPLETED
        self.report.stop_message = self._stop_message
        self.report.final_page = self.tracker.current_id
        self.report.final_node = self.cursor.current
        self.report.changes = self.tracker.changes
        self.report.blackboard = self.ctx.blackboard.as_dict()
        if self.executor is not None:
            self.report.outcomes = list(self.executor.outcomes)
        log.info(self.report.summary())
        return self.report

    # ------------------------------------------------------------------ #
    # 单轮
    # ------------------------------------------------------------------ #
    def tick(self, *, now: float = 0.0) -> StepOutcome | None:
        """执行一轮。返回本轮"做了什么"，什么都没做（纯等待）时返回 None。

        顺序就是模块 docstring 里的 (1)~(8)：

        1. 拿帧；
        2. 问关联表"当前节点期望哪个状态"，然后用**快路径**验它；
        3. 跟踪层更新；
        4. 终态判断；
        5. **锚点对得上就干活、对不上就重定位**（这是本方法的核心）；
        6. 推进游标 + 记决策。

        三条不能动的性质：

        * **正常路径不查树**（只探预期那一页）。扩散搜索只在意外时跑，
          否则每帧探测全树，树的剪枝收益就没了；
        * **状态没确认前不动手**（``require_confirmed``）—— 过滤动画里的"闪现"；
        * **重定位一定留痕**（:attr:`RunReport.recoveries`）。自动跳的唯一毛病
          就是"隐形"，所以每次跳都带 expected / actual / node / 试过谁。
        """
        now = now or self.ctx.now()

        # (1) 拿帧（TTL 内复用，所以同一轮里所有判断看的是同一张图）
        frame = self._frame()

        node = self.scenario.graph.node(self.cursor.current)
        if node is None:
            self.stop(StopReason.ERROR, f"当前节点不存在: {self.cursor.current!r}")
            return None

        # (2) 流程层自己的预期 + 快路径验证
        #
        # hint 和 expected 是两回事，别合并：
        #   hint     = 上一帧**实际看到**的状态（跟踪器的当前值），只影响尝试顺序
        #   expected = 流程层**以为应该**在的状态（当前节点声明的），先精确验它
        # 大多数时候两者相等，但"刚换完屏"那一轮不同 —— 而正是那一轮
        # 最需要 hint 少试几个分支。
        expected = self.binding.expects(node)
        found = self.scenario.tree.locate(
            frame, self.tracker.current_id, expected=expected, now=now
        )
        if not found.ok:
            # 定位**出错**不等于"认不出来"：模板缺失、Matcher 抛异常都属于
            # 配置/环境问题，当成未知状态会让脚本带着坏掉的识别规则一直空转。
            log.error("状态定位出错: %s", found.message)
            self.report.errors.append(f"状态定位出错: {found.message}")
            self.stop(StopReason.ERROR, found.message)
            return None
        match = found.value
        if match is None:
            # ``locate`` 契约上"成功就一定带一个 PageMatch（认不出来时是
            # UNKNOWN_PAGE）"，所以这里理论上到不了。留着是为了**类型收窄**：
            # 下面 ``tracker.update`` 收的是 PageMatch，而 mypy 看的是
            # ``PageMatch | None``。与其 ignore，不如把这个"不该发生"写出来。
            log.error("状态定位返回成功但没有结果")
            self.stop(StopReason.ERROR, "状态定位返回成功但没有结果")
            return None

        # (3) 跟踪层：连续几帧了、从何时起、换状态了没有
        self.tracker.update(match, now=now, reason="定位")
        anchor = self.tracker.current_id

        # (4) 终态判断（stop_pages 或状态的 terminal 标记）
        if self._check_terminal(anchor, now=now):
            return None

        # (5) 状态自检：锚点和"我以为我在的地方"一致就干活，不一致就重定位。
        #
        # 不写 ``page`` 的节点也有"我以为我在的地方" —— 就是它自己。
        # 这样"流程图只写正常流程"和"意外时总能被拉回正轨"可以同时成立：
        # 不校验不等于闭着眼乱走。认不出来（unknown）**不算不一致** ——
        # 那是"看不清"，不是"走错了"，由 _handle_unknown 的宽容期处理。
        if self._matches_current(node, anchor):
            return self._run_current(node, now=now)

        if anchor == UNKNOWN_PAGE:
            self._handle_unknown(now)
            self._note_advance(now=now)
            return None

        expected = self.binding.expects(node) or node.id
        return self._realign(frame, node, expected, anchor, now=now)

    def _matches_current(self, node: Node, anchor: PageId) -> bool:
        """实测锚点是不是"当前节点应该在的地方"。

        * 节点声明了 ``page``：锚点就是它；
        * 节点没声明（纯逻辑/纯等待节点）：看锚点有没有**别的**节点认领 ——
          有就说明已经走到别人负责的状态上了，该让位；没有就继续待着。
        """
        if self.binding.is_bound(node.page):
            return anchor == node.page
        if anchor == UNKNOWN_PAGE:
            return True
        owner = self.binding.node_for(anchor)
        return owner is None or owner.id == node.id

    # ------------------------------------------------------------------ #
    # 两条分支
    # ------------------------------------------------------------------ #
    def _run_current(self, node: Node, *, now: float) -> StepOutcome | None:
        """状态对得上：走正常路径（干活）。"""
        options = self.scenario.options

        # 状态还没"确认进入"（连续命中帧数不够）前不动手
        if options.require_confirmed and not self.tracker.confirmed:
            self._note_advance(now=now)
            return None

        outcomes = self._run_node(node.id)
        # 转移决策：**没走成的也记**（"为什么它不动"要靠这个回答）
        self._note_advance(now=now)
        return outcomes[-1] if outcomes else None

    def _realign(
        self,
        frame: Frame,
        node: Node,
        expected: PageId,
        anchor: PageId,
        *,
        now: float,
    ) -> StepOutcome | None:
        """状态对不上：走意外路径（重定位）。

        这是"状态树用来在意外时重定位到某个流程节点"的实现：

        1. 锚点认不出来（``unknown``）-> 宽容期内只等，超时按 ``on_unknown`` 处理。
           认不出来时**绝不猜**，也绝不动作；
        2. 认得出但和预期不同 -> 用**慢路径**确认一下真实状态（快路径只验了预期），
           再问关联表"这归哪个节点管"，把游标挪过去；
        3. 挪过去之后**本轮不执行** —— 重定位是"先把位置摆正"，
           干活留给下一轮（那时的自检会自然通过）。
        """
        if anchor == UNKNOWN_PAGE:
            self._handle_unknown(now)
            self._note_advance(now=now)
            return None
        self._unknown_since = None

        # 慢路径：末梢优先 + 逐步扩散。快路径只验了 expected，所以这里要重找一遍。
        recovered = self.scenario.tree.recover(frame, near=expected, now=now)
        candidate = recovered.value if recovered.ok else None
        if candidate is not None and candidate.id != UNKNOWN_PAGE and candidate.id != expected:
            anchor = candidate.id
            self.tracker.update(candidate, now=now, reason="重定位")
            anchor = self.tracker.current_id

        target = self.binding.node_for(anchor)
        if target is None:
            # 启动期 validate_binding 已经保证"有信息的状态都有节点认领"，
            # 所以走到这里通常意味着热改过配置，或者锚点是个没认领的状态。
            self._note_recovery(node.id, expected, anchor, None, recovered.value)
            log.warning(
                "重定位到状态 %r，但没有任何节点认领它 —— 保持原地", anchor
            )
            self._note_advance(now=now)
            return None

        self.cursor.advance(target.id, now=now)
        self._note_recovery(node.id, expected, anchor, target.id, recovered.value)
        log.info(
            "状态自检不符：节点 %r 期望 %r，实测 %r -> 重定位到节点 %r",
            node.id,
            expected,
            anchor,
            target.id,
        )
        # 本轮不再执行：先把位置摆正，干活交给下一轮
        self._note_advance(now=now)
        return None

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _note_advance(self, *, now: float) -> None:
        """记一笔转移决策 + 推进游标。

        "记决策 + 走一步"是所有"本轮不动作"分支的公共尾巴，收在一处是为了
        保证**没有哪个分支会忘记推进**（忘了就是永久卡死）。
        """
        self._note_decision(self.cursor.evaluate(self.ctx, now=now))
        self.cursor.step(self.ctx, now=now)

    def _note_recovery(
        self,
        from_node: NodeId,
        expected: PageId,
        actual: PageId,
        to_node: NodeId | None,
        match: Any,
    ) -> None:
        """记一次重定位。

        **这是"自动跳"能被接受的全部理由**：它不隐形。每次跳都带上
        "我以为在哪 / 实际在哪 / 落到哪个节点 / 慢路径试过谁"，
        排查"它怎么跑那儿去了"时永远有答案。
        """
        record = Recovery(
            at=self.ctx.now(),
            tick=self.report.ticks,
            from_node=from_node,
            expected=expected,
            actual=actual,
            to_node=to_node,
            attempts=[a.to_dict() for a in getattr(match, "attempts", [])],
        )
        self.report.recoveries.append(record)

    def _tick_interval(self) -> float:
        """本轮结束后的等待时长。

        节点声明了 cooldown 时取较大者 —— 防止"某个界面原地空转刷屏"的第一道闸。
        """
        base = self.scenario.options.tick_interval
        return base

    def _handle_unknown(self, now: float) -> None:
        """未知页面处理：先宽容等待，超时后按策略执行。"""
        if self._unknown_since is None:
            self._unknown_since = now
            return
        if now - self._unknown_since < self.scenario.options.unknown_grace:
            return

        policy = self.scenario.options.on_unknown
        log.warning(
            "认不出页面已持续 %.2fs，按策略 %s 处理", now - self._unknown_since, policy.value
        )
        if policy is UnknownPolicy.STOP:
            self.stop(StopReason.UNKNOWN, "长时间无法识别页面")
        elif policy is UnknownPolicy.RECOVERY and self.scenario.options.recovery_node:
            self.cursor.advance(self.scenario.options.recovery_node, now=now)
            self._unknown_since = None
        elif policy is UnknownPolicy.RELOAD_TICK:
            self._unknown_since = None
        # WAIT: 什么都不做，继续等

    def check_state(self, anchor: PageId | None = None) -> tuple[bool, str]:
        """动手前的状态校验（走关联表）。

        这是 :meth:`StateBinding.check` 的转发，**保留成引擎上的公开方法**
        是因为它对排查很有用：想知道"这一步到底校没校验、校验的是什么"，
        在 REPL 里问引擎就行。

        ``Node.page is None`` 的节点永远通过 —— 那正是"流程图只写正常流程"
        的实现方式：不写就不校验。

        :param anchor: 实测锚点；不给就用跟踪器当前状态。
        """
        if anchor is None:
            anchor = self.tracker.current_id
        return self.binding.check(self.cursor.current, anchor)

    def _run_node(self, state_id: NodeId) -> list[StepOutcome]:
        """执行某节点的步骤（含 ``on_enter`` 首次执行）。

        :return: 本次真正执行过的步骤结果（按执行顺序）。
            单个步骤失败**不在这里中断** —— 处理权在 ``StepPolicy.on_error``
            （抛异常 / 停流程 / 继续 / 放弃本轮），那是业务决策，
            流程层只负责如实上报"这一轮做了什么"。
        """
        node = self.scenario.graph.require(state_id)
        outcomes: list[StepOutcome] = []

        # 步骤是普通函数，没有"首次进入"这种两段式钩子 —— 一个节点就是一件事。
        outcomes.extend(self._run_steps(node.steps, state_id))
        return outcomes

    def _run_steps(self, steps: list[StepFunc], node_id: NodeId) -> list[StepOutcome]:
        """按顺序跑一串步骤。**某一步失败就停在那里**。

        停下来而不是继续：一步失败（多半是识图没命中）意味着它的前提没成立，
        而后面步骤的前提正是"前一步成功了"。继续跑只会在错的状态上乱操作。

        停下来之后由调用方（:meth:`tick`）拿实测状态去**重定位**。

        ``node_id`` 只用于日志（说清是哪一步、在哪个节点上失败）。
        """
        if self.executor is None:  # pragma: no cover - 装配期必然有执行器
            return []
        outcomes = self.executor.run_many(list(steps))
        for outcome in outcomes:
            self._note_outcome(outcome)
        if outcomes and not outcomes[-1].ok:
            log.debug(
                "节点 %r 的步骤 %r 失败（%s），这一轮剩下的步骤不跑了",
                node_id,
                outcomes[-1].step,
                outcomes[-1].message,
            )
        return outcomes

    def _check_terminal(self, page_id: PageId, *, now: float) -> bool:
        """终态判断：stop_pages 或状态的 terminal 标记。"""
        if page_id in self.scenario.options.stop_pages:
            self.stop(StopReason.STOP_PAGE, f"进入终态状态 {page_id}")
            return True
        page = self.scenario.tree.get(page_id)
        if isinstance(page, PageLeaf) and page.terminal:
            self.stop(StopReason.STOP_PAGE, f"状态 {page_id} 是终态")
            return True
        return False

    def _frame(self) -> Frame:
        """拿当前帧。需要新帧就说清楚，别默默多截一张。"""
        return self.ctx.frame()

    def _note_decision(self, decision: Decision) -> None:
        """记一笔决策（含没走成的），并把它里面的条件异常暴露出来。"""
        self.report.decisions.append(decision)
        for message in decision.errors:
            log.warning("边条件异常: %s", message)
            self.report.errors.append(f"边条件异常: {message}")

    def _note_outcome(self, outcome: StepOutcome) -> None:
        """记一个步骤结果，并顺带判断**这个末梢节点是不是已经没活儿可干了**。

        ## 为什么需要这个判断

        ``StopReason.COMPLETED`` 的语义一直写着"一次性流程自然跑完（没有可做的事
        且没有出边）"，但**从来没有代码触发它** —— 于是"干完活之后"的流程会一直
        空转：每轮跑一遍步骤、每轮 ``not_found``，直到 ``max_runtime`` 才被掐停。
        名将杀的竞技场正是这个形状（``jingji`` 没有出边，匹配页还没定义）。

        判据刻意收得很窄，只有**同时**满足才算"干完了"：

        * 当前节点**没有出边**（有出边说明它还有下一步可走，那不该停）；
        * 连续 ``DEAD_END_STALL_ROUNDS`` 轮，每一步都是 ``not_found``。

        第二条为什么限制成 ``not_found`` 而不是"任何失败"：``not_found`` 是
        "我要找的东西现在不在画面上"，对一个没有出路的末梢节点来说就是
        "没活儿了"。而 ``error`` 是识别/配置坏了 —— 那种情况该继续报错让人看见，
        不该被"流程正常结束"掩盖掉。

        停之前**先记一条 warning**：这是"流程走完了"和"脚本卡住了"的分界，
        两者的画面一模一样（都是步骤一直 not_found），必须靠日志说清是哪种。
        """
        if self.executor is not None:
            self.executor.outcomes.append(outcome)

        if not self._note_stall(outcome):
            return

        node = self.cursor.current
        log.warning(
            "节点 %r 没有出边，且连续 %d 轮找不到可做的事（%s）—— 按流程走完处理",
            node,
            self._stall_rounds,
            outcome.message or outcome.step,
        )
        self.stop(
            StopReason.NO_MORE_WORK,
            f"节点 {node!r} 没有出边，且连续 {self._stall_rounds} 轮无事可做"
            f"（最后一步: {outcome.step}）",
        )

    def _note_stall(self, outcome: StepOutcome) -> bool:
        """累计/清零"末梢节点上没活儿干"的轮数；够轮数了返回 True。

        ⚠️ **清零和累加必须在同一个函数里**。第一版把它们拆开了：
        ``_dead_end_stalled`` 累加后返回"还不够"，而外层看到 False 就
        ``_stall_rounds = 0`` —— 于是计数永远到不了阈值，"流程走完"永远不触发。
        计数器的读改写别跨函数边界，这类错误还特别难看出来（代码看着挺对）。
        """
        current = self.scenario.graph.node(self.cursor.current)
        stuck = (
            not outcome.ok
            and outcome.status == "not_found"
            # 有出边说明它还有下一步可走 —— 那就不是"干完了"，别停
            and current is not None
            and not self.scenario.graph.out_edges(current.id)
        )
        self._stall_rounds = self._stall_rounds + 1 if stuck else 0
        threshold = self.scenario.options.dead_end_rounds
        if threshold <= 0:  # 0 = 关掉这个判定
            return False
        return self._stall_rounds >= threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.name,
            "running": self.running,
            "cursor": self.cursor.to_dict(),
            "tracker": self.tracker.to_dict(),
            "options": self.scenario.options.to_dict(),
        }

    def __repr__(self) -> str:
        return (
            f"FlowEngine(scenario={self.scenario.name!r}, "
            f"node={self.cursor.current!r}, page={self.tracker.current_id!r})"
        )
