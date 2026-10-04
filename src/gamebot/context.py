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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config.schema import AppConfig
from .state.store import Blackboard, StateStore
from .types import ActionResult, Region
from .utils.logging import get_logger

if TYPE_CHECKING:
    from .atomic.frame import Frame
    from .atomic.session import Session
    from .execution.executor import Executor

log = get_logger("context")

__all__ = ["RunContext", "StopFlag"]


@dataclass(slots=True)
class StopFlag:
    """停止请求的载体。用独立对象而不是 bool，是为了让执行层 / hooks
    都能拿到它并写入（GUI 的"停止"按钮、信号处理器、超时看门狗）。"""

    requested: bool = False
    reason: str = ""
    at: float = 0.0

    def request(self, reason: str = "", *, now: float = 0.0) -> None:
        self.requested = True
        self.reason = reason
        self.at = now or time.perf_counter()

    def clear(self) -> None:
        self.requested = False
        self.reason = ""
        self.at = 0.0


class RunContext:
    """一次运行的全部共享状态。

    :param session: L1 截图层实例。
    :param config: 应用配置。
    :param frame_ttl: 帧的新鲜度上限（秒）。超过就自动重截。
    """

    def __init__(
        self,
        session: Session,
        config: AppConfig,
        *,
        frame_ttl: float = 1.0,
        executor: Executor | None = None,
        states: StateStore | None = None,
        blackboard: Blackboard | None = None,
        clock: Any = None,
    ) -> None:
        self.session = session
        self.config = config
        self.frame_ttl = frame_ttl
        self.executor = executor
        self.states = states or StateStore()
        self.blackboard = blackboard or Blackboard()
        self.stop_flag = StopFlag()
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
        """可被停止请求打断的等待。

        用 ``min(0.05, seconds)`` 分片，是为了让"停止"按钮最多 50ms 内生效 ——
        否则一个 ``sleep(10)`` 会让用户以为程序卡死了。
        """
        if seconds <= 0:
            return
        deadline = self.now() + seconds
        while True:
            remaining = deadline - self.now()
            if remaining <= 0 or self.stop_flag.requested:
                return
            time.sleep(min(0.05, remaining))

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
            self.states.tick,
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
    # 停止
    # ------------------------------------------------------------------ #
    @property
    def stop_requested(self) -> bool:
        return self.stop_flag.requested

    @property
    def stop_reason(self) -> str:
        return self.stop_flag.reason

    def request_stop(self, reason: str = "") -> None:
        """请求停止（执行层在 ``ErrorMode.STOP_FLOW`` 时调它）。"""
        self.stop_flag.request(reason, now=self.now())

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
        """清空运行期状态，准备下一次运行。"""
        self.states.reset()
        self.blackboard.clear()
        self.stop_flag.clear()
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
            f"RunContext(state={self.states.current_id!r}, tick={self.states.tick}, "
            f"captures={self.capture_count}, frame_age={self.frame_age:.2f}s)"
        )
