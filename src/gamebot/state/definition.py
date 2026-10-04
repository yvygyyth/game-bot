"""状态层的状态定义。

.. note::
   **已被 ``state/page.py`` 的页面树取代**（``Page`` + ``PageTree``）。
   保留是为了不打断已有代码，新脚本请直接用页面树 ——
   页面树是它的超集（深度 1 的树就等于扁平清单），额外带来逐层剪枝、
   ROI 继承和同名图标消歧。

把"游戏现在处于什么状态"从代码里搬到数据里，是因为状态判断是这个脚本里
**变化最频繁、最需要调参**的部分：

* 每个状态的识别条件（找哪些图 / 读哪些字）
* 优先级（同时满足多个时听谁的）
* 卡住多久算异常

这些写进 YAML，改的时候不用碰 Python。

关于"状态"的粒度：建议按**流程能立即做出决定**的粒度切。比如
``主界面 / 战斗中 / 结算中 / 弹窗 / 未知`` 就够用；把"血条 80% 的战斗中"
也切成一个状态，只会让转移表爆炸。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..atomic.query import Query

__all__ = ["StateDefinition", "StateId"]

StateId = str
"""状态标识。建议用英文小写下划线，和 YAML 的 key 一致。"""


@dataclass(frozen=True, slots=True)
class StateDefinition:
    """一个游戏状态的识别规则。

    :param id: 唯一标识，如 ``"main_menu"``。
    :param queries: 命中条件。**默认全部命中**才认为是该状态（AND 语义），
        因为"看到开始按钮"和"看到设置按钮"同时成立比只看一个可靠得多。
        需要 OR 语义就包一个 ``OrQuery``。
    :param exclude: 反条件。命中任一则**否决**该状态。用来处理
        "主界面按钮和战斗中按钮长得一样"这类冲突。
    :param min_stable_frames: 连续命中多少帧才确认进入该状态。
        >1 可以过滤动画过程中的闪现（强烈建议加载类状态用 2~3）。
    :param priority: 同时满足多个状态定义时，数字大的胜出。
        建议：弹窗类 > 异常类 > 结算类 > 常规界面。
    :param timeout: 在该状态停留超过这个秒数算异常（可选）。
        比如"加载中"卡 30 秒就该报警重开。
    :param terminal: 终态。进入即结束整个流程（如 ``"游戏已关闭"``）。
    :param description: 给人看的说明，写日志用。
    """

    id: StateId
    queries: tuple[Query, ...] = ()
    exclude: tuple[Query, ...] = ()
    min_stable_frames: int = 1
    priority: int = 0
    timeout: float | None = None
    terminal: bool = False
    description: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.description or self.id

    @property
    def has_conditions(self) -> bool:
        return bool(self.queries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "priority": self.priority,
            "min_stable_frames": self.min_stable_frames,
            "timeout": self.timeout,
            "terminal": self.terminal,
            "description": self.description,
            "query_count": len(self.queries),
            "exclude_count": len(self.exclude),
        }
