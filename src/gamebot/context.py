"""运行时上下文 —— 三个层（状态 / 流程 / 执行）共享的那个对象。

它是**唯一**允许被跨层传递的东西。有了它，步骤就不需要知道 session 从哪来、
帧该不该复用、日志写到哪：

    Step.run(ctx)  ->  ctx.frame() / ctx.session / ctx.blackboard / ctx.states

为什么帧要挂在上下文里（而不是每步各截一张）：

* **一致性**。同一轮里"判断按钮在不在"和"点击它"必须看同一张图，
  否则会出现"判断时在、点击时已经消失"这种鬼故事。
* **性能**。一次 tick 里 5 个步骤各截一张图，在 adb 上就是 1 秒起步。
* 需要新帧的步骤显式声明 ``needs_fresh_frame=True``，或让流程插入 ``CaptureStep``
  —— 让"我看到了新画面"成为一个显式事件，而不是隐式副作用。

**帧的生命周期**：默认在每次 ``frame()`` 后的 N 秒内视为新鲜（``frame_ttl``），
超时自动重截。这个 TTL 是必要的：卡在某个界面 30 秒时，一帧旧图会骗过所有查询。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config.schema import AppConfig
from .state.page import PageMatch, PageTree
from .state.store import Blackboard
from .state.tracker import PageTracker
from .types import ActionResult, Region
from .utils.logging import get_logger

if TYPE_CHECKING:
    from .atomic.frame import Frame
    from .atomic.session import Session
    from .execution.executor import Executor

log = get_logger("context")

__all__ = ["RunContext"]


class RunContext:
    """一次运行的全部共享状态。

    :param session: L1 截图层实例。
    :param config: 应用配置。
    :param tree: 状态树。跟踪器需要它来查 ``min_stable_frames`` / ``timeout``。
    :param frame_ttl: 帧的新鲜度上限（秒）。超过就自动重截。

    **中止的单一事实源是 ``session``**，不是这里。本类只做转发 ——
    因为原子层的等待循环拿不到 ``RunContext``，只拿得到 ``session``；
    两处各存一份标志迟早会不同步（UI 停了、原子层还在等）。
    """

    def __init__(
        self,
        session: Session,
        config: AppConfig,
        *,
        tree: PageTree | None = None,
        frame_ttl: float = 1.0,
        executor: Executor | None = None,
        pages: PageTracker | None = None,
        blackboard: Blackboard | None = None,
        clock: Any = None,
    ) -> None:
        self.session = session
        self.config = config
        self.frame_ttl = frame_ttl
        self.executor = executor
        self.pages = pages or PageTracker(tree)
        self.blackboard = blackboard or Blackboard()
        self._clock = clock or time.perf_counter
        self._frame: Frame | None = None
        self._frame_at: float = 0.0
        self.capture_count = 0

    # ------------------------------------------------------------------ #
    # 时间
    # ------------------------------------------------------------------ #
    def now(self) -> float:
        """单调时钟。上下文里所有时间都必须走它，方便测试时注入假时钟。"""
        return self._clock()

    def sleep(self, seconds: float) -> None:
        """可被中止打断的等待。直接转发给 ``session.sleep()``。

        实现是 ``Event.wait()``：既睡眠又能被 ``request_stop()`` 立刻唤醒，
        比"切成 50ms 小片轮询标志"既精确又不空转。

        :raises Cancelled: 等待期间被中止。
        """
        self.session.sleep(seconds)

    # ------------------------------------------------------------------ #
    # 帧
    # ------------------------------------------------------------------ #
    @property
    def current_frame(self) -> Frame | None:
        """当前帧（可能已过期，调用方自己判断是否需要新的）。"""
        return self._frame

    @property
    def frame_age(self) -> float:
        return self.now() - self._frame_at if self._frame is not None else float("inf")

    def capture(self, region: Region | None = None) -> Frame:
        """强制截一张新帧并替换当前帧。"""
        frame = self.session.capture() if region is None else self.session.capture_region(region)
        self._frame = frame
        self._frame_at = self.now()
        self.capture_count += 1
        log.debug(
            "新帧 #%d (id=%d, 抓帧数=%d)",
            self.pages.tick,
            frame.frame_id,
            self.capture_count,
        )
        return frame

    def frame(self, region: Region | None = None, *, fresh: bool = False) -> Frame:
        """拿当前帧；过期或 ``fresh=True`` 时自动重截。

        这是步骤实现里最该用的入口 —— **不要**直接调 ``ctx.session.capture()``，
        那会绕开帧复用，让同一轮里的步骤看到不同画面。
        """
        if fresh or region is not None or self._frame is None or self.frame_age > self.frame_ttl:
            return self.capture(region)
        return self._frame

    def invalidate_frame(self) -> None:
        """标记当前帧作废（点击后、切换场景后调）。"""
        self._frame = None
        self._frame_at = 0.0

    # ------------------------------------------------------------------ #
    # 中止（全部转发给 session —— 单一事实源，见类 docstring）
    # ------------------------------------------------------------------ #
    @property
    def stop_requested(self) -> bool:
        return self.session.stop_requested

    @property
    def stop_reason(self) -> str:
        return self.session.stop_reason

    def request_stop(self, reason: str = "") -> None:
        """请求中止。**可以从任意线程调**（UI 的停止按钮、超时看门狗）。

        执行层在 ``ErrorMode.STOP_FLOW`` 时也调它。
        """
        self.session.request_stop(reason)

    def raise_if_stopped(self) -> None:
        """已请求中止就抛 ``Cancelled``。转发给 session。"""
        self.session.raise_if_stopped()

    # ------------------------------------------------------------------ #
    # 页面状态（跟踪器，转发几个最常用的）
    # ------------------------------------------------------------------ #
    @property
    def page(self) -> PageMatch | None:
        """当前页面的**单帧**观测；还没定位过时是 None。

        ``flow.graph.GraphCursor.should_run()`` 通过它读"实际在哪个页面"来做
        位置守卫 —— 实际页面 ≠ 节点期望页面时拒绝执行动作。
        没有它，那个守卫会被静默跳过（只认位置不认人）。
        """
        state = self.pages.current
        if state is None:
            return None
        return PageMatch(
            id=state.id,
            path=state.path,
            overlays=state.overlays,
            confidence=state.confidence,
            frame_id=state.frame_id,
        )

    @property
    def page_id(self) -> str:
        """当前页面 id 的简写（含"认不出来"时返回 ``unknown``）。"""
        return self.pages.current_id

    def is_(self, page_id: str) -> bool:
        """当前页面（或任一叠加层）是不是它。"""
        return self.pages.is_(page_id)

    # ------------------------------------------------------------------ #
    # 便捷查询（给 hooks / 临时逻辑用，步骤实现里请直接调原子层）
    # ------------------------------------------------------------------ #
    def query(self, query: Any, *, fresh: bool = False) -> ActionResult[Any]:
        """在当前帧上跑一个 Query。省得每处都写 ``ctx.frame().xxx``。"""
        return query.run(self.frame(fresh=fresh))

    def find_image(
        self,
        template: str,
        region: Region | None = None,
        confidence: float | None = None,
    ) -> ActionResult[Any]:
        """在当前帧上找一个模板图。"""
        return self.frame().find_image(template, region=region, confidence=confidence)

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    def screenshot_path(self, name: str, *, suffix: str = ".png") -> Path:
        """生成截图存档路径（目录自动创建）。"""
        directory = self.config.paths.resolve(self.config.paths.screenshots)
        directory.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        return directory / f"{safe}{suffix}"

    def journal_path(self, name: str | None = None) -> Path:
        """生成 journal 文件路径。"""
        directory = self.config.paths.resolve(self.config.paths.journals)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return directory / f"{name or self.config.name}-{stamp}.jsonl"

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """清空运行期状态，准备下一次运行（含清掉中止标志）。"""
        self.pages.reset()
        self.blackboard.clear()
        self.session.clear_stop()
        self.invalidate_frame()
        self.capture_count = 0

    def close(self) -> None:
        if self.executor is not None:
            self.executor.close()
        self.session.close()

    def __enter__(self) -> RunContext:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"RunContext(page={self.pages.current_id!r}, tick={self.pages.tick}, "
            f"captures={self.capture_count}, frame_age={self.frame_age:.2f}s)"
        )
