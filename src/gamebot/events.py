"""结构化事件流 —— 运行期**发生了什么**，按时间顺序，一条一条。

## 它和 journal 的分工（别合并）

================  ==========================  ==============================
                  journal                      events
================  ==========================  ==============================
粒度              **一步**的明细账             运行期流水
内容              step / 结果 / 耗时 / 失败帧  tick、换页、换节点、重定位、
                                              步骤起止、仓库写入、运行起止
谁写              执行层（``Executor``）       流程层 + 装配层
落盘              ``logs/journals/*.jsonl``   ``logs/events/*.jsonl``
给谁看            排查"哪一步失败了"           界面、事后复盘、统计
================  ==========================  ==============================

为什么不能是同一个东西：journal 是**执行层**的账本，它的每一行都对应一次
``Step.run()``；而"这一轮认出来的页面变了""游标被重定位挪了"这些事根本
不发生在一个步骤里。硬塞进 journal 会让"一步一行"这条契约失效。

## 为什么界面不该解析日志文本

日志是给人读的（带缩进、带中文、随时会改措辞）。界面要的是**结构**：
当前页面、当前节点、这一轮做了什么、重定位了几次。从日志文本里正则抠这些，
等于让界面的稳定性和日志的措辞绑在一起 —— 改一句中文就崩。

所以：[docs/ui.md](../../docs/ui.md) 里写的那条"状态面板不解析日志"，
在代码上的落地就是这里。

## 两条硬规矩

1. **监听器抛异常不能弄挂脚本。** 事件是观测手段，不是流程的一部分。
   所以 :meth:`EventBus.emit` 捕获 ``Exception`` 并留痕（``bus.errors``）——
   但**不捕获** ``Cancelled``（它继承 ``BaseException``，是"停下来"，不是"出错了"）。
   注意这和引擎的 ``on_tick`` 回调**故意相反**：那个是流程的一部分，抛了就该停。
2. **事件数据必须能 JSON 化。** 它们要落盘、要过界面的 ``json.dumps``。
   ``to_dict`` 里不做兜底转换 —— 传了不能序列化的东西应该在测试里就炸，
   而不是在用户跑了三小时之后写盘失败。
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .utils.logging import get_logger

log = get_logger("events")

__all__ = ["Event", "EventBus", "EventKind", "JsonlEventWriter"]


class EventKind(StrEnum):
    """事件类型。**先只有这些** —— 每加一种都要有地方消费它。"""

    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    TICK = "tick"
    PAGE_CHANGED = "page_changed"
    NODE_CHANGED = "node_changed"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    RECOVERY = "recovery"
    STORE_CHANGED = "store_changed"


@dataclass(frozen=True, slots=True)
class Event:
    """一条事件。

    :param kind: 类型（见 :class:`EventKind`）。
    :param at: ``ctx.now()`` 的时间戳（单调时钟，**不是**墙上时间 —— 落盘时
        由 writer 另记一条 ``wall``，因为单调时钟换算不回"几点几分"）。
    :param tick: 第几轮。一开始就有值，所以"按 tick 对齐"不需要外部推算。
    :param data: 这条事件的内容。必须能 JSON 化。
    """

    kind: EventKind
    at: float = 0.0
    tick: int = 0
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "at": round(self.at, 4),
            "tick": self.tick,
            "data": dict(self.data),
        }

    def __repr__(self) -> str:
        return f"Event({self.kind.value}, tick={self.tick}, {dict(self.data)!r})"


class EventBus:
    """事件的同步分发 + 最近若干条的环形缓冲。

    同步（而不是排进队列由另一个线程消费）是刻意的：这一轮发生了什么，
    这一轮结束时就该在界面上能看到；异步队列会让"界面显示的状态"永远比
    "引擎的状态"晚一拍，排查时非常误导。

    代价是监听器必须**很快**（往控件上贴字符串可以，读磁盘不行）。
    """

    def __init__(self, *, history: int = 200) -> None:
        self._listeners: list[Callable[[Event], None]] = []
        self._history: deque[Event] = deque(maxlen=max(0, history))
        self.errors: list[str] = []
        """监听器抛过的异常（``"类型: 说明"``）。由 UI/测试读，不参与流程。"""

    # ------------------------------------------------------------------ #
    def subscribe(self, listener: Callable[[Event], None]) -> Callable[[], None]:
        """订阅。返回值是**取消订阅的函数**（比记 id 好管理）。"""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def emit(self, event: Event) -> None:
        """分发一条事件。**监听器出错不外抛**（见模块 docstring 的规矩 1）。"""
        self._history.append(event)
        # 复制一份再遍历：监听器里退订自己/别的监听器不能让这一轮少发。
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.errors.append(message)
                log.warning("事件监听器出错: %s", message)

    def recent(self, limit: int | None = None) -> list[Event]:
        """最近的事件（默认全部缓冲，最多 ``history`` 条）。"""
        items = list(self._history)
        return items[-limit:] if limit else items

    def clear(self) -> None:
        self._history.clear()

    def __len__(self) -> int:
        return len(self._listeners)

    def __repr__(self) -> str:
        return f"EventBus({len(self._listeners)} 个监听器, {len(self._history)} 条历史)"


class JsonlEventWriter:
    """把事件追加进 ``.jsonl``。可以直接当监听器：``bus.subscribe(writer)``。

    每行一个事件，另带 ``wall``（墙上时间）—— 因为 ``Event.at`` 是单调时钟，
    事后看文件时没法从它知道"这是昨天几点跑的"。

    写盘出错**不抛**（观测不该弄挂脚本），但只记一次日志：磁盘满的时候
    每轮刷一条 error 会把真正有用的日志淹掉。
    """

    def __init__(self, path: Path, *, echo: bool = False) -> None:
        self.path = Path(path)
        self.echo = echo
        self.broken = False
        self._lock = threading.Lock()

    def __call__(self, event: Event) -> None:
        self.write(event)

    def write(self, event: Event) -> None:
        if self.broken:
            return
        record = event.to_dict()
        record["wall"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        line = json.dumps(record, ensure_ascii=False)
        if self.echo:
            print(line)
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError as exc:  # pragma: no cover - 磁盘满/权限
                self.broken = True
                log.error("事件流写盘失败（后续不再尝试）: %s: %s", self.path, exc)

    def close(self) -> None:
        """没有常驻句柄（每次追加都开关），留个口子给调用方对称使用。"""

    def __repr__(self) -> str:
        return f"JsonlEventWriter({str(self.path)!r}{', broken' if self.broken else ''})"
