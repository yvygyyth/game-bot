"""game-bot —— 传统识图游戏脚本框架。

分层（**依赖只能向下**）::

    ┌─────────────────────────────────────────────────────────┐
    │ 流程层 flow        "接下来做什么"    状态机 + 主循环      │
    ├─────────────────────────────────────────────────────────┤
    │ 状态层 state       "现在是什么状态"  识别 + 快照 + 黑板   │
    ├─────────────────────────────────────────────────────────┤
    │ 执行层 execution   "可靠地做一次"    步骤 + 重试 + 记账   │
    ├─────────────────────────────────────────────────────────┤
    │ 原子化方法层 atomic  "怎么做"         L0~L5 共 47 个方法  │
    │   L5 actions      点/拖/滚/按键                          │
    │   L4 combinators  多查询协作 + 跨帧等待                  │
    │   L3 query        可序列化的查询描述符                    │
    │   L2 frame        一帧截图 + 12 个查询方法                │
    │   L1 session      截图 + 坐标换算 + 输入通道              │
    │   L0 types        ActionResult / Point / Region          │
    └─────────────────────────────────────────────────────────┘

快速上手::

    from gamebot.bootstrap import run_flow
    report = run_flow("config/app.yaml")
    print(report.summary())

只做识图（不进流程）::

    from gamebot.atomic.session import build_session
    from gamebot.vision.opencv_matcher import OpenCvMatcher

    session = build_session(
        "windows",
        matcher=OpenCvMatcher("assets/templates"),
        window_title="游戏窗口",
    )
    with session:
        frame = session.capture()
        r = frame.find_image("start_button.png")
        if r.ok:
            print("找到按钮:", r.value, r.meta.get("score"))
"""

from __future__ import annotations

__version__ = "0.1.0"

from .exceptions import (
    BackendError,
    BackendUnavailable,
    ConfigError,
    FlowError,
    GameBotError,
    StepFailed,
    TemplateNotFoundError,
    TimeoutExceeded,
)
from .types import ActionResult, ActionStatus, Point, Region

__all__ = [
    "ActionResult",
    "ActionStatus",
    "BackendError",
    "BackendUnavailable",
    "ConfigError",
    "FlowError",
    "GameBotError",
    "Point",
    "Region",
    "StepFailed",
    "TemplateNotFoundError",
    "TimeoutExceeded",
    "__version__",
]
