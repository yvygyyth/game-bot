"""引擎工作线程 —— 让界面里的「开始」真的能跑。

## 为什么必须是线程

``FlowEngine.run()`` 是个**阻塞**的循环：它自己 sleep、自己等识别、跑多久取决于
脚本。把它放在界面线程里，整个界面会冻住 —— 连「停止」都点不动，
而"能随时停下"正是这个工具的底线。

所以：引擎在**工作线程**里跑，界面线程只做三件事：收信号、刷控件、发停止请求。

## 三条线程规矩（和 ``preview.py`` 里那三条是一回事）

1. **跨线程只传值**（``QImage`` / 不可变 dataclass / ``str``），绝不传控件、
   不传 ``Session`` 给别人用；
2. **``Session`` 在哪个线程用，就在哪个线程建、在那个线程关。**
   这里不建 Session —— 它由装配期在界面线程建好、连同 ``RunContext`` 一起传进来，
   然后**只有本线程碰它**。底层 mss 的实例是线程局部的，跨线程用是最难查的崩溃来源；
3. **停止用标志，不用杀线程。** ``FlowEngine.stop()`` 只是设一个标志，
   引擎会在下一次 ``ctx.sleep()`` 时被立刻唤醒（毫秒级）并退出循环。
   所以「停止」按钮直接调它就行，不需要跨线程信号，也不需要 ``terminate()``。

## 它不发画面

它**不**再发帧给界面了 —— 界面上的实时画面已经删掉（看不见问题的东西不该占位置）。
"它认到的是哪一块"现在由**识图日志**回答：记录器把每次匹配的框画在真机上
（红=命中 / 橙=未命中 / 蓝=搜索范围），跑完一轮去那一页看就行。

引擎每轮仍然会通过 ``on_tick`` 回调把状态推给界面（``ticked`` 信号）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot

from ..utils.logging import get_logger

if TYPE_CHECKING:
    from ..context import RunContext
    from ..flow.engine import FlowEngine, RunReport

log = get_logger("ui.engine")

__all__ = ["EngineWorker", "TickEvent"]


@dataclass(frozen=True, slots=True)
class TickEvent:
    """一轮跑完之后的**值快照**（跨线程传的就是它，不是引擎对象）。

    刻意做成 frozen dataclass 而不是直接传 ``FlowEngine``：引擎对象带着
    ``Session`` / 游标 / 计数器，把它交给界面线程用就是**两个线程同时碰一个
    有状态对象** —— 那种 bug 只在机器慢的时候偶发，最难查。
    """

    tick: int
    page: str
    overlays: tuple[str, ...] = ()
    expected: str = ""
    node: str = ""
    confirmed: bool = False
    recoveries: int = 0
    last_recovery: str = ""
    note: str = ""

    @property
    def aligned(self) -> bool:
        """状态和流程层的预期对得上吗（没声明 ``page`` 的节点永远算对得上）。"""
        return not self.expected or self.expected == self.page


class EngineWorker(QObject):
    """在工作线程里跑一次 ``FlowEngine.run()``。

    生命周期：``configure(ctx, engine, start_node)`` -> ``run()`` -> ``finished``。
    同一个 worker 可以反复跑（每次 ``configure`` 一套新的）。

    **一次只跑一个**：``configure`` 会拒绝在运行中重配（返回 False），
    因为"跑到一半换场景"会让报告和界面各说各话。
    """

    #: 一轮的状态快照
    ticked = Signal(object)  # TickEvent

    #: 跑完了：``(RunReport, 给人看的一行总结)``
    finished = Signal(object, str)

    #: 起不来 / 中途炸了（装配期错误已经被主窗口挡在前面了）
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._ctx: RunContext | None = None
        self._engine: FlowEngine | None = None
        self._running = False

    # ------------------------------------------------------------------ #
    # 配置（在主线程调用，但只是赋值，不在那一刻开始跑）
    # ------------------------------------------------------------------ #
    @Slot(object, object, str)
    def configure(self, ctx: object, engine: object, start_node: str = "") -> None:
        """装上一套要跑的东西。运行中调用会被忽略（见类 docstring）。"""
        if self._running:
            log.warning("引擎正在运行，忽略这次重配")
            return
        self._ctx = ctx  # type: ignore[assignment]
        self._engine = engine  # type: ignore[assignment]
        if start_node:
            self._engine.start_node = start_node  # type: ignore[union-attr]

    # ------------------------------------------------------------------ #
    # 跑
    # ------------------------------------------------------------------ #
    @Slot()
    def run(self) -> None:
        engine = self._engine
        ctx = self._ctx
        if engine is None or ctx is None:
            self.failed.emit("引擎没有配置好（先选脚本再点开始）")
            return
        if self._running:
            log.warning("引擎已经在跑了，忽略这次启动")
            return

        self._running = True
        try:
            report = engine.run(on_tick=self._on_tick)
        except Exception as exc:
            # 装配期错误该在主窗口拦掉；走到这里是运行期的意外。
            # **不能让它静默** —— 界面会一直显示"运行中"。
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        finally:
            self._running = False

        self.finished.emit(report, _summarize(report))

    @Slot()
    def request_stop(self) -> None:
        """请求停止。引擎会在下一次 sleep 时被唤醒（毫秒级）。

        这个方法**可以从界面线程直接调**：``FlowEngine.stop()`` 只设一个标志，
        没有跨线程的共享写问题，比绕一圈信号更直接、更快。
        """
        engine = self._engine
        if engine is not None:
            engine.stop()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def engine(self) -> FlowEngine | None:
        """当前装着的那台引擎（还没配置就是 ``None``）。

        界面用它来**直接请求停止**：``engine.stop()`` 只设标志位、线程安全，
        从界面线程调是对的。反过来"发个队列信号让引擎线程去调"是错的 ——
        引擎线程正卡在 ``run()`` 里，队列里的槽永远等不到执行
        （``window._on_stop`` 的 docstring 里记了这次踩坑）。
        """
        return self._engine

    # ------------------------------------------------------------------ #
    # 每轮回调（在**本线程**里执行，由 engine.run 调用）
    # ------------------------------------------------------------------ #
    def _on_tick(self, engine: FlowEngine, _outcome: object) -> None:
        ctx = self._ctx
        if ctx is None:
            return

        event = TickEvent(
            tick=engine.report.ticks,
            page=engine.tracker.current_id,
            overlays=tuple(engine.tracker.overlays),
            expected=engine.binding.expects(engine.cursor.current) or "",
            node=engine.cursor.current,
            confirmed=engine.tracker.confirmed,
            recoveries=len(engine.report.recoveries),
            last_recovery=(
                str(engine.report.recoveries[-1]) if engine.report.recoveries else ""
            ),
        )
        self.ticked.emit(event)



def _summarize(report: RunReport) -> str:
    """给界面用的一行总结（``RunReport.summary()`` 太长，日志里有全的）。"""
    parts = [
        f"{report.stop_reason.value}",
        f"{report.ticks} 轮",
        f"{report.step_count} 步",
        f"{report.initial_page} -> {report.final_page}",
    ]
    if report.recoveries:
        parts.append(f"重定位 {len(report.recoveries)} 次")
    failed = len(report.failed_steps)
    if failed:
        parts.append(f"失败 {failed} 步")
    return " / ".join(parts)
