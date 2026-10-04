"""状态层的页面树 —— 游戏界面是分模块的，所以"我在哪"天然是棵树。

```
首页
└── 千里单骑
    └── 战斗
        ├── 开始战斗
        └── 战斗结算
```

## 为什么用树，而不是一张扁平的页面清单

不是为了分类好看，是三个实打实的收益：

1. **剪枝**：定位时只需要试"当前路径上的兄弟"，不用把所有页面的识别条件跑一遍。
   20 个页面的游戏，扁平清单每帧要跑 20 组匹配；树在稳定状态下通常只跑 2~4 组。
   这是抓帧之后最贵的一步，省下来就是帧率。
2. **ROI 继承**：「战斗」的所有子状态只需要看右下角技能栏就能区分，不用整屏匹配。
   子页面的 ``roi`` 相对父页面，:meth:`PageTree.effective_roi` 会沿祖先链叠出来。
   又快又不容易误判。
3. **消歧**：不同分支下可以出现长得一样的图标（"确认"到处都是）。有了父节点上下文，
   同一个模板在不同分支下可以指不同的东西。

## 两种层级语义（必须区分，混用一定出 bug）

* :attr:`PageKind.PAGE` —— **替换式**。进入子页面就不再是父页面了（像状态机的嵌套状态）。
  「战斗」→「结算」：结算画面出来时战斗 UI 已经没了，父页面不再成立。
* :attr:`PageKind.OVERLAY` —— **叠加式**。父页面仍然成立，它只是盖在上面。
  「战斗」+「网络错误弹窗」是**同时成立**的。

所以定位结果不是单个 id，而是 :class:`PageMatch`：一个主页面 + 若干叠加层。

## 职责边界

* 本模块只回答**"这一帧画面是哪个页面"** —— 单帧、纯匹配、不做决定。
* "连续几帧才算数"（``min_stable_frames``）、"在这个页面待了多久"、
  "状态变了要通知谁" 属于**跟踪层**（``state/tracker.py``）。
* "在这个页面上该做什么" 属于**流程层**（``flow/graph.py`` 的 ``Node``）。

页面本身**没有任何行为**。一旦往 ``Page`` 上挂"进这个页面要点击哪"，
就没法表达"同一个页面在不同阶段要做不同的事"（第一次进主界面领奖励，
之后直接开打），那正是流程层存在的理由。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..exceptions import StateError
from ..types import ActionResult, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from ..atomic.query import Query

log = get_logger("state.page")

__all__ = [
    "UNKNOWN_PAGE",
    "Page",
    "PageAttempt",
    "PageId",
    "PageKind",
    "PageMatch",
    "PageTree",
]

PageId = str
"""页面标识。建议用路径形式（``"home/qianli/battle"``），
:meth:`PageTree.add` 会自动从嵌套结构推导，见 ``docs/state-and-flow.md``。"""

UNKNOWN_PAGE: PageId = "unknown"
"""约定俗成的"什么都没认出来"。**这是一个有效结果，不是错误** ——
认不出来是最常见的真实情况（过场动画、加载、切场景），
所以每个流程都必须显式定义它的应对方式。"""


class PageKind(StrEnum):
    """页面和它父节点的关系。"""

    PAGE = "page"
    """替换式：进入它就不再是父页面（默认）。"""

    OVERLAY = "overlay"
    """叠加式：父页面依然成立，它只是盖在上面（弹窗、加载遮罩）。"""


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Page:
    """页面树的一个节点。**只有识别规则，没有行为。**

    :param id: 唯一标识。``add()`` 会按嵌套位置自动推导成路径形式，
        也可以在配置里显式指定。
    :param queries: 命中条件。**默认全部命中**才算（AND 语义）——
        同时看两个特征比只看一个可靠得多。需要 OR 就包一个 ``OrQuery``。
    :param exclude: 否决条件。命中任一则**排除**这个页面。
        用来处理"子页面和父页面长得太像"这类冲突。
    :param roi: 搜索区域，**相对父页面**（None = 与父页面相同）。
        这是树最大的性能收益来源：别整屏匹配。
    :param confidence: 相似度阈值；具体查询可以各自覆盖。
    :param min_stable_frames: 连续命中多少帧才算确认进入。
        >1 能过滤动画过程中的"闪现"（加载类页面建议 2~3）。
        **由跟踪层使用**，本模块的单帧匹配不管它。
    :param priority: 同级之间谁先试。弹窗类给高值。
    :param kind: 替换式还是叠加式，见 :class:`PageKind`。
    :param terminal: 终态，进入即结束整个流程（如"游戏已关闭"）。
    :param timeout: 允许在该页面停留的秒数，超了算异常。None = 不限。
    :param name: 人看的名字，进日志。
    :param description: 更长的说明。
    :param meta: 任意附加信息。
    """

    id: PageId
    queries: tuple[Query, ...] = ()
    exclude: tuple[Query, ...] = ()
    roi: Region | None = None
    confidence: float = 0.9
    min_stable_frames: int = 1
    priority: int = 0
    kind: PageKind = PageKind.PAGE
    terminal: bool = False
    timeout: float | None = None
    name: str = ""
    description: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.name or self.id

    @property
    def is_overlay(self) -> bool:
        return self.kind is PageKind.OVERLAY

    @property
    def has_conditions(self) -> bool:
        """没有查询条件的页面永远匹配 —— 只有根节点应该这样。"""
        return bool(self.queries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "priority": self.priority,
            "min_stable_frames": self.min_stable_frames,
            "timeout": self.timeout,
            "terminal": self.terminal,
            "roi": self.roi.to_tuple() if self.roi else None,
            "query_count": len(self.queries),
            "exclude_count": len(self.exclude),
        }

    def __repr__(self) -> str:
        return f"Page({self.id!r}, kind={self.kind.value}, queries={len(self.queries)})"


# --------------------------------------------------------------------------- #
# 定位结果
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PageAttempt:
    """一次页面匹配的痕迹。调试"为什么认成了这个页面"时唯一有用的东西。"""

    id: PageId
    matched: bool
    reason: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "matched": self.matched, "reason": self.reason}


@dataclass(slots=True)
class PageMatch:
    """**单帧**定位结果。

    刻意不带 ``hits`` / ``since`` —— 那些是"持续了多久"，属于跟踪层的职责。
    本类是纯观测：这一帧是什么、有多确信、试过谁。
    """

    id: PageId = UNKNOWN_PAGE
    path: tuple[PageId, ...] = ()
    """从根到 ``id`` 的完整路径（含 ``id`` 自己）。"""

    overlays: tuple[PageId, ...] = ()
    """同时命中的叠加层（弹窗），按优先级降序。

    这是"战斗页面 + 网络错误弹窗"能同时表达的原因 ——
    如果只用单个 id，这种共存状态根本描述不了。
    """

    confidence: float = 0.0
    observed_at: float = 0.0
    frame_id: int = -1
    values: dict[str, Any] = field(default_factory=dict)
    attempts: list[PageAttempt] = field(default_factory=list)
    message: str = ""

    @property
    def is_unknown(self) -> bool:
        return self.id == UNKNOWN_PAGE

    @property
    def depth(self) -> int:
        return len(self.path)

    @property
    def has_overlay(self) -> bool:
        return bool(self.overlays)

    def is_(self, page_id: PageId) -> bool:
        """当前页面（或任一叠加层）是不是它。"""
        return page_id == self.id or page_id in self.overlays

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": list(self.path),
            "overlays": list(self.overlays),
            "confidence": round(self.confidence, 4),
            "frame_id": self.frame_id,
            "values": self.values,
            "attempts": [a.to_dict() for a in self.attempts],
        }

    def __repr__(self) -> str:
        suffix = f" +{list(self.overlays)}" if self.overlays else ""
        return f"PageMatch({self.id!r}{suffix}, confidence={self.confidence:.3f})"


# --------------------------------------------------------------------------- #
# 树
# --------------------------------------------------------------------------- #
class PageTree:
    """页面树 + 单帧定位。

    刻意设计成**构造期可变、运行期只读**：结构在装配阶段定好，
    跑起来之后没人改它。这样它可以被多个运行共享，也能安全地序列化对比。

    :param roots: 顶层页面 id。通常包含"首页"和若干全局叠加层
        （断线重连、网络错误 —— 它们不属于任何父页面）。
    """

    __slots__ = ("_children", "_pages", "_parent", "_roots")

    def __init__(self, roots: Iterable[PageId] = ()) -> None:
        self._pages: dict[PageId, Page] = {}
        self._children: dict[PageId, list[PageId]] = {}
        self._parent: dict[PageId, PageId | None] = {}
        self._roots: list[PageId] = []
        for root in roots:
            self._roots.append(root)
            self._parent[root] = None
            self._children.setdefault(root, [])

    # ------------------------------------------------------------------ #
    # 构建（装配期）
    # ------------------------------------------------------------------ #
    def add(self, page: Page, parent: PageId | None = None) -> Page:
        """加一个页面。

        :param parent: 父页面 id；None 表示顶层。
        :raises StateError: id 重复，或父页面不存在。
        """
        if page.id in self._pages:
            raise StateError(f"页面 id 重复: {page.id!r}")
        if parent is not None and parent not in self._pages:
            raise StateError(f"页面 {page.id!r} 的父页面不存在: {parent!r}")

        self._pages[page.id] = page
        self._parent[page.id] = parent
        self._children.setdefault(page.id, [])
        if parent is None:
            if page.id not in self._roots:
                self._roots.append(page.id)
        else:
            self._children[parent].append(page.id)
        return page

    def add_many(self, pages: Iterable[tuple[Page, PageId | None]]) -> None:
        """批量加。**按父先子后的顺序**给（loader 解析嵌套结构时天然满足）。"""
        for page, parent in pages:
            self.add(page, parent)

    @classmethod
    def from_nested(cls, data: Mapping[str, Any]) -> PageTree:
        """从嵌套字典建树（YAML 配置用）。

        期望结构（``id`` 由嵌套位置自动推导成路径形式）::

            pages:
              home:                              # id = "home"
                name: 首页
                queries:
                  - {type: ImageQuery, template: home/logo.png}
                children:
                  qianli:                        # id = "home/qianli"
                    queries: [...]
                    children:
                      battle:                    # id = "home/qianli/battle"
                        roi: [600, 400, 680, 500]   # 相对父页面
                        queries: [...]
                        children:
                          result: {queries: [...]}

              # 全局叠加层：不属于任何父页面
              network_error:
                kind: overlay
                priority: 100
                queries:
                  - {type: ImageQuery, template: common/network_error.png}

        ``queries`` 里的字典由 ``query_from_dict`` 还原成 Query 对象
        （那一步在流程层的 loader 里，还没实现）。
        """
        raise NotImplementedError(
            "待实现：递归遍历 pages -> 用 query_from_dict 构造 queries -> "
            "按嵌套位置推导 id 路径 -> 逐层调 add(page, parent)"
        )

    # ------------------------------------------------------------------ #
    # 查询结构
    # ------------------------------------------------------------------ #
    @property
    def pages(self) -> Mapping[PageId, Page]:
        return dict(self._pages)

    @property
    def roots(self) -> tuple[PageId, ...]:
        return tuple(self._roots)

    def __len__(self) -> int:
        return len(self._pages)

    def __contains__(self, page_id: object) -> bool:
        return page_id in self._pages

    def get(self, page_id: PageId) -> Page | None:
        return self._pages.get(page_id)

    def require(self, page_id: PageId) -> Page:
        """取页面，不存在就抛（装配期用，别静默返回 None）。"""
        page = self._pages.get(page_id)
        if page is None:
            raise StateError(f"页面不存在: {page_id!r}")
        return page

    def parent_of(self, page_id: PageId) -> PageId | None:
        return self._parent.get(page_id)

    def children_of(self, page_id: PageId | None = None) -> tuple[Page, ...]:
        """子页面，按 ``priority`` 降序（同级的先试谁）。

        ``page_id=None`` 时返回所有顶层页面。
        """
        ids = self._roots if page_id is None else self._children.get(page_id, [])
        pages = [self._pages[i] for i in ids if i in self._pages]
        return tuple(sorted(pages, key=lambda p: p.priority, reverse=True))

    def siblings_of(self, page_id: PageId, *, include_self: bool = False) -> tuple[Page, ...]:
        peers = self.children_of(self.parent_of(page_id))
        if include_self:
            return peers
        return tuple(p for p in peers if p.id != page_id)

    def overlays_of(self, page_id: PageId) -> tuple[Page, ...]:
        """某个页面的叠加层子节点（弹窗），按优先级降序。"""
        return tuple(p for p in self.children_of(page_id) if p.is_overlay)

    def global_overlays(self) -> tuple[Page, ...]:
        """顶层叠加层 —— 任意页面上都可能出现的弹窗。"""
        return tuple(p for p in self.children_of(None) if p.is_overlay)

    def ancestors_of(self, page_id: PageId) -> tuple[PageId, ...]:
        """祖先链，从根到父（不含自己）。"""
        chain: list[PageId] = []
        current = self._parent.get(page_id)
        while current is not None:
            chain.append(current)
            current = self._parent.get(current)
        return tuple(reversed(chain))

    def path_of(self, page_id: PageId) -> tuple[PageId, ...]:
        """从根到自己的完整路径（含自己）。"""
        return (*self.ancestors_of(page_id), page_id)

    def depth_of(self, page_id: PageId) -> int:
        """根节点深度 0。"""
        return len(self.ancestors_of(page_id))

    def walk(self, order: str = "dfs") -> Iterator[Page]:
        """遍历所有页面。``dfs``（先父后子，默认）或 ``bfs``。"""
        queue: list[PageId] = list(self._roots)
        collected: list[Page] = []
        while queue:
            current = queue.pop(0) if order == "bfs" else queue.pop()
            page = self._pages.get(current)
            if page is not None:
                collected.append(page)
            children = [c for c in self._children.get(current, []) if c in self._pages]
            if order == "bfs":
                queue.extend(children)
            else:
                queue.extend(reversed(children))
        return iter(collected)

    def leaves(self) -> tuple[Page, ...]:
        """没有子页面的页面。"""
        return tuple(p for p in self.walk() if not self._children.get(p.id))

    # ------------------------------------------------------------------ #
    # ROI 继承
    # ------------------------------------------------------------------ #
    def effective_roi(self, page_id: PageId) -> Region | None:
        """把祖先链上的 ``roi`` 叠成**相对当前帧**的最终区域。

        每一层的 ``roi`` 都相对它父页面的 ROI 原点。任何一层是 None 就
        原样继承父层。整条链都是 None 时返回 None（意思是"整帧"）。
        """
        region: Region | None = None
        for ancestor_id in (*self.ancestors_of(page_id), page_id):
            page = self._pages.get(ancestor_id)
            if page is None or page.roi is None:
                continue
            region = page.roi if region is None else page.roi.offset(region.x, region.y)
        return region

    # ------------------------------------------------------------------ #
    # 定位
    # ------------------------------------------------------------------ #
    def locate(
        self,
        frame: Frame,
        hint: PageId | None = None,
        *,
        now: float = 0.0,
    ) -> ActionResult[PageMatch]:
        """定位当前帧是哪个页面。

        ## 算法

        1. **起点**：``hint``（一般是上一帧的页面）或所有顶层页面。
        2. **自顶向下**：先确认顶层，再逐个往下走。某层不成立就退回最近
           仍然成立的祖先，从那里继续试它的其他子节点。
        3. **同级按 priority 试**；每个候选的查询都在
           :meth:`effective_roi` 算出的区域里跑（子页面只看自己那块）。
        4. 走到走不动为止，**最深**的那个命中节点就是当前页面。
        5. 再扫一遍叠加层：当前页面的 ``OVERLAY`` 子节点 + 全局叠加层，
           命中的全部收进 ``PageMatch.overlays``（按优先级降序）。
        6. 一个都没命中 -> ``success(PageMatch(id=UNKNOWN_PAGE))``。

        ## 关键性质

        **``hint`` 只影响尝试顺序，不影响正确性。** 所以即使 hint 完全错了
        （画面已经跳到别的分支），也能自顶向下重新走对 —— 只是多花几次匹配。
        这是它敢用 hint 做优化的前提；如果 hint 影响结果，一旦定位错了就永远出不来。

        ## 返回

        * ``success(PageMatch)`` —— 包括"认不出来"（``id=UNKNOWN_PAGE``）。
          **认不出来是有效结果，不是错误。**
        * ``error`` —— 只用于底层真出错（模板文件缺失、Matcher 抛异常）。
          把它当成"认不出来"会把配置错误伪装成游戏行为，极难排查。
        """
        raise NotImplementedError(
            "待实现：见 docstring 的 6 步。"
            "每层的匹配用 combinators.find_all_of(frame, page.queries)"
            "（AND 语义）先求 exclude 否决，再按 priority 逐层下探，"
            "最后扫叠加层。"
        )

    # ------------------------------------------------------------------ #
    # 校验（装配期）
    # ------------------------------------------------------------------ #
    def validate(self) -> None:
        """结构校验，把配置错误挡在启动阶段而不是跑一半才炸。

        检查项：

        1. 树不能是空的，且必须有顶层页面；
        2. 没有空 id；
        3. ``min_stable_frames >= 1``、``confidence`` 在 ``(0, 1]`` 之间；
        4. ``roi`` 非 None 时必须非空（``w > 0 and h > 0``）；
        5. **无识别条件的叶节点** —— 它永远随父页面一起匹配，不带任何信息量，
           等于空壳（多半是忘了写 ``queries``）。
           **中间节点允许无条件**：那是合法的 pass-through 分组，
           只用来挂 ``roi`` 或组织结构；
        6. 叠加层不能有子页面 —— 弹窗里再套层级会让定位结果无法解释；
        7. ``terminal`` 页面不该有子页面；
        8. **子页面的 roi 必须落在父页面的有效 roi 内**。roi 是**整棵子树**的
           搜索范围（不只是这一页自己的），子页面的 roi 伸到父页面框外，
           就意味着它会在"父页面根本不存在"的地方去找自己的特征 ——
           这正是那种"偶尔认错页面"的难查 bug。

        :raises StateError: 校验失败，message 里带上全部问题。
        """
        problems: list[str] = []

        if not self._pages:
            problems.append("页面树是空的")
        if not self._roots:
            problems.append("没有任何顶层页面")

        for page_id, page in self._pages.items():
            label = repr(page_id) if page_id else "<空 id>"
            if not page_id or not page_id.strip():
                problems.append("存在空 id 的页面")
            if page.min_stable_frames < 1:
                problems.append(f"页面 {label} 的 min_stable_frames 必须 >= 1")
            if not 0.0 < page.confidence <= 1.0:
                problems.append(f"页面 {label} 的 confidence 必须在 (0, 1] 之间")
            if page.roi is not None and page.roi.is_empty:
                problems.append(f"页面 {label} 的 roi 是空区域: {page.roi.to_tuple()}")

        for page in self._pages.values():
            children = [c for c in self._children.get(page.id, []) if c in self._pages]

            if not children and not page.queries:
                problems.append(
                    f"页面 {page.id!r} 没有识别条件又是叶节点 —— 它永远随父页面匹配，"
                    "等于空壳。（只想做分组的话，给它加子页面）"
                )
            if page.is_overlay and children:
                problems.append(
                    f"叠加层 {page.id!r} 不该有子页面 —— 弹窗里套层级会让定位结果无法解释"
                )
            if page.terminal and children:
                problems.append(f"终态页面 {page.id!r} 不该有子页面")

        for page in self._pages.values():
            if page.roi is None:
                continue
            parent_id = self._parent.get(page.id)
            if parent_id is None:
                continue
            parent_roi = self.effective_roi(parent_id)
            own_roi = self.effective_roi(page.id)
            if (
                parent_roi is not None
                and own_roi is not None
                and not parent_roi.contains_region(own_roi)
            ):
                problems.append(
                    f"页面 {page.id!r} 的有效 roi {own_roi.to_tuple()} 超出了父页面 "
                    f"{parent_id!r} 的 {parent_roi.to_tuple()} —— "
                    "roi 是整棵子树的搜索范围，伸到外面会让这一页永远定位不到"
                )

        if problems:
            raise StateError("页面树校验失败:\n  - " + "\n  - ".join(problems))

    # ------------------------------------------------------------------ #
    def describe(self) -> str:
        """打印成一棵树，给日志和 ``gamebot check`` 用。"""
        lines: list[str] = []

        def render(page_id: PageId, prefix: str, is_last: bool) -> None:
            page = self._pages.get(page_id)
            if page is None:
                return
            branch = "└── " if is_last else "├── "
            tag = " [overlay]" if page.is_overlay else ""
            roi = f" roi={page.roi.to_tuple()}" if page.roi else ""
            lines.append(f"{prefix}{branch}{page.display}{tag}{roi}")
            children = [c for c in self._children.get(page_id, []) if c in self._pages]
            for index, child in enumerate(children):
                render(child, prefix + ("    " if is_last else "│   "), index == len(children) - 1)

        lines.append(f"PageTree({len(self._pages)} 个页面)")
        for index, root in enumerate(self._roots):
            render(root, "", index == len(self._roots) - 1)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots": list(self._roots),
            "pages": {pid: page.to_dict() for pid, page in self._pages.items()},
        }

    def __repr__(self) -> str:
        return f"PageTree({len(self._pages)} 个页面, roots={list(self._roots)})"
