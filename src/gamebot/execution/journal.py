"""执行层的落盘记录 —— journal。

为什么现在就要留这个口子（哪怕还没实现）：

* **脚本调试靠它**。"为什么昨天能跑今天不行" 只能靠逐步骤的落盘记录回答。
* **它天然就是训练数据的雏形**。每步记录"看到什么 + 做了什么 + 结果如何"，
  攒够了就是模仿学习的样本。所以从第一天起就让数据格式带上前缀信息（frame 路径、
  坐标、置信度），而不是事后补。
* 现在只定义契约，实现（JSONL 落盘）等真正需要时再写。

格式约定（JSONL，一行一条）::

    {"ts": 1730000000.123, "tick": 42, "step": "点击开始游戏",
     "status": "success", "attempts": 1, "elapsed": 0.031,
     "action": {"kind": "click", "point": [960, 540]},
     "frame": "logs/screenshots/tick42.png", "meta": {}}

**帧不内联**，只存路径 —— 否则 log 会爆炸。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from .executor import StepOutcome

__all__ = ["Journal", "JournalEntry", "JsonlJournal", "MemoryJournal", "NullJournal"]


@dataclass(slots=True)
class JournalEntry:
    """一条步骤记录。"""

    step: str
    status: str
    ts: float
    tick: int = 0
    attempts: int = 1
    elapsed: float = 0.0
    action: dict[str, Any] = field(default_factory=dict)
    frame_path: str = ""
    message: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": round(self.ts, 6),
            "tick": self.tick,
            "step": self.step,
            "status": self.status,
            "attempts": self.attempts,
            "elapsed": round(self.elapsed, 6),
            "action": self.action,
            "frame": self.frame_path,
            "message": self.message,
            "meta": self.meta,
        }


class Journal(ABC):
    """记录器契约。实现必须**不阻塞主流程**（IO 慢了宁可丢记录，也不能拖慢脚本）。"""

    @abstractmethod
    def record(self, entry: JournalEntry) -> None:
        ...

    def record_outcome(self, outcome: StepOutcome, *, tick: int = 0) -> None:
        """从 ``StepOutcome`` 直接记一条的便捷方法。"""
        raise NotImplementedError("待实现：把 StepOutcome 映射成 JournalEntry")

    def attach_frame(self, outcome: StepOutcome, frame: Frame) -> str:
        """把帧存成图片并返回路径（供 entry.frame_path 使用）。

        需要 ``ctx.config.paths.screenshots``；由具体实现决定存不存、怎么命名。
        """
        raise NotImplementedError("待实现")

    def close(self) -> None:
        return None

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class NullJournal(Journal):
    """什么都不做。默认值，保证"没配 journal"时零开销。"""

    def record(self, entry: JournalEntry) -> None:
        return None


class MemoryJournal(Journal):
    """存在内存里，给测试断言用。"""

    def __init__(self) -> None:
        self.entries: list[JournalEntry] = []

    def record(self, entry: JournalEntry) -> None:
        self.entries.append(entry)

    def clear(self) -> None:
        self.entries.clear()


class JsonlJournal(Journal):
    """追加写 JSONL 文件。

    :param path: 目标文件。目录会自动创建。
    :param flush_every: 每 N 条 flush 一次（兼顾性能与"崩了也能看到最后几条"）。
    """

    def __init__(self, path: Any, *, flush_every: int = 1) -> None:
        self.path = path
        self.flush_every = flush_every
        self._handle: Any = None
        self._since_flush = 0

    def record(self, entry: JournalEntry) -> None:
        raise NotImplementedError("待实现：json.dumps(ensure_ascii=False) + 换行")

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
