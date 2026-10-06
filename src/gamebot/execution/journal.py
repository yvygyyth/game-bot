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

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
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
        """从 ``StepOutcome`` 直接记一条的便捷方法。

        映射规则（为什么这么映射）：

        * ``status`` 用 ``outcome.status`` 而不是 ``result.status`` ——
          跳过是 ``"skipped"``，它既不是成功也不是失败，
          记成 success 会让"这一步到底做没做"变得看不出来；
        * ``message`` 用 ``outcome.message`` —— 跳过时它是跳过原因；
        * ``meta`` 收下 ``result.meta`` 与重试/子步骤信息。**注意别把整个
          meta 里的大对象（numpy 数组之类）原样塞进来** ——
          journal 是 JSONL，不是二进制转储。
        """
        meta: dict[str, Any] = dict(outcome.result.meta or {})
        # 把已经拾取好的动作信息从 meta 里**挪到独立字段**：格式约定里
        # ``action`` 是自己的 key（回放和训练数据要拿它当锚点），
        # 留在 meta 里会变成 meta.action.action 这种两层嵌套。
        meta.pop("action", None)
        if outcome.children:
            meta["children"] = [c.to_dict() for c in outcome.children]

        self.record(
            JournalEntry(
                step=outcome.step,
                status=outcome.status,
                ts=perf_counter(),
                tick=tick,
                elapsed=outcome.elapsed,
                action=dict(outcome.action),
                frame_path=outcome.frame_path,
                message=outcome.message,
                meta=meta,
            )
        )

    def attach_frame(
        self,
        outcome: StepOutcome,
        frame: Frame,
        *,
        directory: Any = None,
        prefix: str = "",
        tick: int = 0,
    ) -> str:
        """把帧存成图片并返回路径（供 ``entry.frame_path`` 使用）。

        :param directory: 存到哪。给了就存并把路径写回 ``outcome.frame_path``；
            **没给就直接返回空串，不存** —— 帧不内联进 journal 是硬约定
            （一行一条记录里塞一张图，log 会瞬间爆炸），而"存不存帧"
            是调用方的策略（``save_frames_on_error``），不是记录器的策略。
        :param prefix: 文件名前缀，**调用方用它来圈定自己的留存范围**。
            传了 ``"fail_"`` 的文件才能被"清理旧失败帧"那条规则匹配到 ——
            名字不带前缀的话，清理规则要么扫不到（图无限涨），
            要么只能不带 pattern 地删（会误删手工截图）。两种情况都很糟。
        :param tick: 第几轮，放进文件名。只靠 ``attempts`` 命名的话，
            同一轮里同名步骤会被后来的覆盖，反而丢掉证据。

        存失败（磁盘满、权限）**不抛异常**：可观测性不该把脚本弄挂，
        返回空串、``frame_path`` 留空就行。
        """
        if directory is None:
            return ""
        try:
            target = Path(directory)
            target.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in outcome.step)
            path = target / f"{prefix}t{tick}_{safe}.png"
            saved = frame.save(str(path))
            path_text = str(path) if saved.ok else ""
        except OSError:
            path_text = ""
        if path_text:
            outcome.frame_path = path_text
        return path_text

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
        """写一行 JSONL。

        三个刻意的选择：

        * ``ensure_ascii=False`` —— 步骤名和消息是中文，转义成 ``\\uXXXX``
          之后日志就没法用眼睛看了；
        * ``default=str`` —— meta 里混进 Path / Point / 枚举时不炸，
          退化成字符串。journal 的可用性比类型保真重要；
        * **写失败不抛异常**，只把这一条丢掉。可观测性不该把脚本弄挂 ——
          磁盘满的时候脚本该继续跑完，而不是因为你记不下日志而崩掉。
        """
        try:
            handle = self._handle_for_write()
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False, default=str) + "\n")
            self._since_flush += 1
            if self.flush_every <= 1 or self._since_flush >= self.flush_every:
                handle.flush()
                self._since_flush = 0
        except OSError:
            # 不在这里打日志：日志系统本身可能就是出问题的那一环，
            # 再往里写会递归。
            self._since_flush = 0

    def _handle_for_write(self) -> Any:
        """懒打开文件（第一条记录时才建目录和句柄）。"""
        if self._handle is None:
            path = Path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("a", encoding="utf-8")
        return self._handle

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        self._since_flush = 0
