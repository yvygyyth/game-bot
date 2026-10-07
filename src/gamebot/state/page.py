"""状态层的状态树 —— 游戏界面是分模块的，所以"我在哪"天然是棵树。

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

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NoReturn

# 帧内组合子（L4）。依赖方向是 state -> atomic，符合分层规则；
# 它们只在**传进来的帧**上跑查询，不会让状态层自己截图。
from ..atomic.combinators import find_all_of, find_any_of
from ..exceptions import StateError
from ..types import ActionResult, ActionStatus, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from ..atomic.query import Query

log = get_logger("state.page")

__all__ = [
    "UNKNOWN_PAGE",
    "Page",
    "PageAttempt",
    "PageGroup",
    "PageId",
    "PageKind",
    "PageLeaf",
    "PageMatch",
    "PageNode",
    "PageTree",
]

PageId = str
"""页面标识。建议用路径形式（``"home/qianli/battle"``），
:meth:`PageTree.add` 会自动从嵌套结构推导，见 ``docs/state-and-flow.md``。"""

UNKNOWN_PAGE: PageId = "unknown"
"""约定俗成的"什么都没认出来"。**这是一个有效结果，不是错误** ——
认不出来是最常见的真实情况（过场动画、加载、切场景），
所以每个流程都必须显式定义它的应对方式。"""

DEFAULT_CONFIDENCE = 0.9
"""没指定阈值时的默认相似度。

单独提出来是为了让"默认值"这件事只有一个出处：``Page.confidence`` 的默认、
:data:`_UNSET` 的解释、文档里提到的数字都指它。
"""


class _Unset:
    """"调用方没传这个参数"的哨兵。

    为什么不能拿 ``Page.confidence`` 的默认值 0.9 当"没传"：那样一个页面
    只要写了 ``confidence=0.95``（最常见的用法）就会把**它下面所有查询**
    各自的阈值一起覆盖掉 —— 而查询级阈值往往是被实测数据校准过的
    （名将杀首页给的是 0.55，被 0.9 盖掉会让它在悬浮态直接失配）。
    参数默认值和"没传"必须是两个不同的东西。
    """

    __slots__ = ()


_UNSET = _Unset()
"""``locate`` / ``match`` / ``Page`` 内部用来区分"没给 confidence"和"给了 0.9"。"""


class PageKind(StrEnum):
    """页面和它父节点的关系。"""

    PAGE = "page"
    """替换式：进入它就不再是父页面（默认）。"""

    OVERLAY = "overlay"
    """叠加式：父页面依然成立，它只是盖在上面（弹窗、加载遮罩）。"""

    GROUP = "group"
    """**纯分类节点：自己不记录任何信息，也就不参与匹配。**

    它只做两件事：给子树提供 ROI 继承、把状态组织成树。定位时**直接下探它的
    子节点**，不要求它自己成立 —— 这一点很关键：要求"父页面成立"会让
    「首页 → 竞技场 → 战斗」这种链条一进下一层就全部失效，
    因为上一层的特征已经不在屏幕上了。

    所以：**记录信息的只能是末梢状态节点，父节点一律是 group。**
    父节点上写 ``queries`` 是配置错误（解析/校验会指出来）；
    真要表达"中间层也有自己的画面"，就把它建成一个真正的状态节点，
    再给它挂子状态。
    """


# --------------------------------------------------------------------------- #
# 页面 —— **分类节点和状态节点是两种不同的类型**
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True, eq=False)
class PageNode:
    """状态树的一个节点。**只有识别规则，没有行为。**

    ## 为什么分成三种类型，而不是一个 ``kind`` 字段

    原来是一个类加一个 :class:`PageKind` 字段。问题是**类型上看不出区别**：
    ``Page("home", queries=...)`` 和 ``Page("home", kind=GROUP)`` 是同一个类型，
    于是"分类节点不该写 queries"只能靠运行期校验兜着，编辑器一声不吭。

    现在分成三种**类型**：

    * :class:`PageGroup` —— 纯分类节点。它**没有** ``queries`` / ``roi``
      （不是"不该填"，是**根本没有那个字段**）；
    * :class:`PageLeaf` —— 记录信息的状态，也就是末梢；
    * 这个基类只放两者共有的东西（``id`` / ``name`` / ``description``）。

    于是"给分类节点写 queries"从"运行期才会报的配置错误"变成
    ``TypeError: unexpected keyword argument 'queries'`` —— 写的时候就报了。

    :attr:`kind` 仍然保留（派生自类型），因为加载器和界面还要按它分支。

    :param id: 唯一标识。
    :param name: 人看的名字，进日志。
    :param description: 更长的说明。
    :param meta: 任意附加信息。
    """

    id: PageId
    roi: Region | None = None
    """**整棵子树**的搜索范围，子节点继承它（相对父节点的 roi 原点）。

    放在基类上是因为**分类节点和状态节点都需要它**：分类节点自己虽然不匹配，
    但它的子节点要靠它收窄范围 —— 这是树最大的性能收益来源。
    """

    priority: int = 0
    """同级之间谁先试。弹窗类给高值。

    放在基类上：**分类节点也需要它**（多个分支都像的时候，靠它定先探哪一支）。
    """

    name: str = ""
    description: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """共有的构造期校验：id 不能空、roi 不能是空区域。子类的规则各自加。"""
        if not self.id or not self.id.strip():
            raise StateError("页面的 id 不能为空")
        if self.roi is not None and self.roi.is_empty:
            raise StateError(f"页面 {self.id!r} 的 roi 是空区域: {self.roi.to_tuple()}")

    @property
    def kind(self) -> PageKind:
        """节点类型。**派生自类型**，不是独立字段 —— 两者不可能不一致。"""
        raise NotImplementedError

    @property
    def display(self) -> str:
        return self.name or self.id

    def to_dict(self) -> dict[str, Any]:
        """给界面和日志用的纯数据形式。子类补自己的字段。"""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "priority": self.priority,
            "roi": self.roi.to_tuple() if self.roi else None,
        }

    @property
    def is_group(self) -> bool:
        """纯分类节点：自己不记录信息，也就不参与匹配。"""
        return self.kind is PageKind.GROUP

    @property
    def is_overlay(self) -> bool:
        return self.kind is PageKind.OVERLAY

    @property
    def has_conditions(self) -> bool:
        """有没有识别条件。分类节点永远没有。"""
        return False

    @property
    def effective_confidence(self) -> float | _Unset:
        """要传给查询的阈值。

        分类节点没有查询，所以这个值只在 :class:PageLeaf 上真正被用；
        放基类是为了让树层不用每处都 `isinstance` 一下（它是个纯派生值，
        对分类节点返回"不覆盖"没有任何副作用）。
        """
        return _UNSET


@dataclass(frozen=True, slots=True, eq=False)
class PageGroup(PageNode):
    """**纯分类节点：自己不记录任何信息，也就不参与匹配。**

    它只做两件事：给子树提供 ROI 继承、把状态组织成树。定位时**直接下探它的
    子节点**，不要求它自己成立 —— 这一点很关键：要求"父页面成立"会让
    「首页 → 竞技场 → 战斗」这种链条一进下一层就全部失效，
    因为上一层的特征已经不在屏幕上了。

    ## 子节点是**嵌套**的，不是"平铺 + 父 id"

    直接在 ``children`` 里放子节点（见 :class:`PageGroup` 的用法）：

    ```python
    PageGroup("home", roi=..., children=(
        PageLeaf("home/lobby", queries=(...)),
        PageGroup("home/jingji", children=(...)),
    ))
    ```

    为什么不平铺成 ``(页面, 父id)`` 的列表：那样**树形只存在于 id 字符串里**，
    类型上看不出嵌套关系，而且"父在前"这条顺序约束得靠约定加校验去守。
    嵌套之后，父子关系是**对象引用**，顺序问题自然消失，
    而且 `mypy` 能检查每一层。

    :param children: 子节点。空分组没有意义（校验会报）。
    :param roi: **整棵子树**的搜索范围，子节点继承它。
        分类节点自己不需要 ROI（它不匹配），但它的子节点需要 —— 所以这个字段
        在这里，而不是在 :class:`PageLeaf` 上重复写。
    """

    children: tuple[PageNode, ...] = ()

    @property
    def kind(self) -> PageKind:
        return PageKind.GROUP


@dataclass(frozen=True, slots=True, eq=False)
class PageLeaf(PageNode):
    """**记录信息的状态** —— 也是定位能落到的那一层（末梢）。

    :param queries: 命中条件。**默认全部命中**才算（AND 语义）——
        同时看两个特征比只看一个可靠得多。需要 OR 就包一个 ``OrQuery``。
    :param exclude: 否决条件。命中任一则**排除**这个页面。
        用来处理"子页面和父页面长得太像"这类冲突。
    :param roi: 搜索区域，**相对父节点的 roi 原点**（None = 与父节点相同）。
        这是树最大的性能收益来源：别整屏匹配。
    :param confidence: 相似度阈值。**显式传进来才会覆盖页面里各查询自己的阈值**；
        不传（默认）时每个查询用自己的 —— 查询级阈值通常是被实测校准过的
        （名将杀首页给的是 0.55），被页面级的 0.9 硬盖掉会让它在悬浮态失配。
        见 :data:`_UNSET`。
    :param min_stable_frames: 连续命中多少帧才算确认进入。
        >1 能过滤动画过程中的"闪现"（加载类页面建议 2~3）。
        **由跟踪层使用**，本模块的单帧匹配不管它。
    :param priority: 同级之间谁先试。弹窗类给高值。
    :param overlay: 叠加式还是替换式。``True`` 表示"父状态仍然成立，
        它只是盖在上面"（弹窗、加载遮罩）；``False``（默认）是替换式 ——
        进入它就不再是父状态了。
    :param terminal: 终态，进入即结束整个流程（如"游戏已关闭"）。
    :param timeout: 允许在该页面停留的秒数，超了算异常。None = 不限。
    """

    queries: tuple[Query, ...] = ()
    exclude: tuple[Query, ...] = ()
    confidence: float = DEFAULT_CONFIDENCE
    min_stable_frames: int = 1
    overlay: bool = False
    terminal: bool = False
    timeout: float | None = None
    confidence_explicit: bool = field(default=False, compare=False)
    """``confidence`` 是作者显式写的，还是默认值。

    只有知道"这个值是不是作者写的"，才能实现"页面阈值只覆盖那些没写自己
    阈值的查询"（见 :attr:`effective_confidence`）。
    """

    def __init__(
        self,
        id: PageId,
        queries: tuple[Query, ...] = (),
        exclude: tuple[Query, ...] = (),
        roi: Region | None = None,
        confidence: float | _Unset | None = _UNSET,
        min_stable_frames: int = 1,
        priority: int = 0,
        overlay: bool = False,
        terminal: bool = False,
        timeout: float | None = None,
        name: str = "",
        description: str = "",
        meta: dict[str, Any] | None = None,
    ) -> None:
        explicit = not isinstance(confidence, _Unset) and confidence is not None
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "queries", tuple(queries))
        object.__setattr__(self, "exclude", tuple(exclude))
        object.__setattr__(self, "roi", roi)
        object.__setattr__(
            self,
            "confidence",
            DEFAULT_CONFIDENCE if not explicit else float(confidence),  # type: ignore[arg-type]
        )
        object.__setattr__(self, "confidence_explicit", explicit)
        object.__setattr__(self, "min_stable_frames", min_stable_frames)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "overlay", overlay)
        object.__setattr__(self, "terminal", terminal)
        object.__setattr__(self, "timeout", timeout)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "meta", dict(meta or {}))
        self._validate()

    def _validate(self) -> None:
        """**构造即校验**：不合法的状态根本造不出来。

        ## 为什么在这儿，而不是一个单独的 ``validate()``

        这些规则只依赖这一个对象自己的字段（id 非空、帧数 >= 1、阈值在 (0,1]、
        roi 非空）。放构造期有两个好处：

        * **报错位置就是写错的那一行** —— ``PageLeaf(...)`` 那行直接抛，
          而不是等整个树建完、再调一次校验才发现"某一页的阈值不对"；
        * 非法对象**根本不存在**，下游不用再怀疑"手上这个节点有没有问题"。

        跨对象的规则（子节点 roi 落在父节点内、分类节点必须有子节点、节点认领
        状态）留在 ``PageTree.validate()`` / ``Graph.validate()`` /
        ``validate_binding()`` —— 那些**原理上**要看到全部数据才能判断。

        :raises StateError: 任一条件不满足，message 里带页面 id 便于定位。
        """
        # **不能写 super()** —— dataclass(slots=True) 会重建类，
        # 而 super() 依赖的 __class__ cell 指向被替换掉的那个旧类，
        # 于是运行期报 "super(type, obj): obj must be an instance or subtype of type"。
        PageNode.__post_init__(self)
        label = repr(self.id) if self.id else "<空 id>"
        if self.min_stable_frames < 1:
            raise StateError(f"页面 {label} 的 min_stable_frames 必须 >= 1")
        if not 0.0 < self.confidence <= 1.0:
            raise StateError(f"页面 {label} 的 confidence 必须在 (0, 1] 之间")
        if self.timeout is not None and self.timeout <= 0:
            raise StateError(f"页面 {label} 的 timeout 必须 > 0 或留空")

    @property
    def kind(self) -> PageKind:
        return PageKind.OVERLAY if self.overlay else PageKind.PAGE

    @property
    def has_conditions(self) -> bool:
        """有 queries 或 exclude 才算"有识别条件"。"""
        return bool(self.queries or self.exclude)

    @property
    def effective_confidence(self) -> float | _Unset:
        """要传给查询的阈值：没显式写就是"不覆盖"。"""
        return self.confidence if self.confidence_explicit else _UNSET

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
        return f"PageLeaf({self.id!r}, kind={self.kind.value}, queries={len(self.queries)})"


#: ``PageLeaf`` 的旧名字。**保留是为了少改 41 处调用点** ——
#: 对"记录信息的状态"来说 ``Page`` 也说得通，而分类节点现在有了自己的类型
#: :class:`PageGroup`。新代码建议直接用 ``PageLeaf``（名字更明确）。
Page = PageLeaf


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

    exhausted: bool = False
    """**树里所有状态都试过了**，画面确实不属于任何已知状态。

    只在 :meth:`PageTree.recover` 全落空时置真。它把两种 ``unknown`` 区分开：

    * ``exhausted=False``：**还没搜完**（可能只是快路径先短路了）；
    * ``exhausted=True``：搜完了、一个都没命中。

    上层靠它决定"当场结束"还是"再等一帧" —— 前者适用于
    "树里压根没这个状态"，后者适用于过场动画里的短暂认不出来。
    """

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
    """状态树 + 单帧定位。

    刻意设计成**构造期可变、运行期只读**：结构在装配阶段定好，
    跑起来之后没人改它。这样它可以被多个运行共享，也能安全地序列化对比。

    :param roots: 顶层页面 id。通常包含"首页"和若干全局叠加层
        （断线重连、网络错误 —— 它们不属于任何父页面）。
    """

    __slots__ = ("_children", "_pages", "_parent", "_roots")

    def __init__(self, roots: Iterable[PageId] = ()) -> None:
        self._pages: dict[PageId, PageNode] = {}
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
    def add(self, page: PageNode, parent: PageId | None = None) -> PageNode:
        """加一个节点。**分类节点会把它的子节点一起加进来。**

        :param parent: 父节点 id；None 表示顶层。
        :raises StateError: id 重复、父节点不存在、或**子节点的 roi 伸出父节点**。

        ## 嵌套：给一个分类节点就是加一棵子树

        :class:`PageGroup` 的 ``children`` 是嵌套的，所以 ``add`` 会递归下去，
        按"父先子后"的顺序挨个加。这让 `PageTree` 的调用方能直接写：

        ```python
        tree.add(root_group)          # 整棵树
        ```

        而不是自己展平、还得自己保证"父在前"。

        ## 为什么 roi 越界在这里报，而不是等 ``validate()``

        "子节点的 roi 必须落在父节点的有效 roi 内"是**跨两个对象**的规则，
        所以只能等到知道父节点时才能判 —— 而那一刻就是 ``add()``。
        在这里报，写错的那一行立刻炸；等 ``validate()`` 的话，报错点离写错的地方
        隔了整个树的构建过程。

        这条规则的由来：roi 是**整棵子树**的搜索范围（不只是这一层自己的）。
        子节点伸到父节点框外，就意味着它会在"父节点根本不存在"的地方去找自己的
        特征 —— 那正是"偶尔认错页面"这类最难查的 bug 的温床。
        """
        if type(page) is PageNode:
            raise StateError(
                f"页面 {page.id!r} 是抽象的 PageNode —— 它既不是分类节点也不是状态节点。"
                "要分类容器就用 PageGroup，要记录信息就用 PageLeaf"
            )
        if page.id in self._pages:
            raise StateError(f"页面 id 重复: {page.id!r}")
        if parent is not None and parent not in self._pages:
            raise StateError(f"页面 {page.id!r} 的父页面不存在: {parent!r}")

        if parent is not None and page.roi is not None:
            self._check_roi_within_parent(page, self._pages[parent])

        self._pages[page.id] = page
        self._parent[page.id] = parent
        self._children.setdefault(page.id, [])
        if parent is None:
            if page.id not in self._roots:
                self._roots.append(page.id)
        else:
            self._children[parent].append(page.id)

        # 分类节点的子节点跟着一起加（递归）。**父先子后**由递归天然保证。
        if isinstance(page, PageGroup):
            for child in page.children:
                self.add(child, parent=page.id)
        return page

    def _check_roi_within_parent(self, page: PageNode, parent: PageNode) -> None:
        """子页面的 roi 必须落在父页面的**有效 roi** 内。

        ## 坐标系（这里踩过一次）

        ``effective_roi`` 要沿祖先链叠，所以它是树的方法（不是 Page 的属性）。
        它叠出来的是**绝对**（相对整帧）坐标；而 ``page.roi`` 是**相对父页面
        原点**的。两者不能直接比大小 —— 那样一个合法的 ``Region(10, 20, ...)``
        会被判成"越出父页面 (1180, 620, ...)"。

        所以先把子的 roi 平移到父坐标系里（加上父 roI 的原点），再比。
        """
        outer = self.effective_roi(parent.id)
        if outer is None or page.roi is None:
            return
        inner = page.roi.offset(outer.x, outer.y)
        if (
            inner.x < outer.x
            or inner.y < outer.y
            or inner.right > outer.right
            or inner.bottom > outer.bottom
        ):
            raise StateError(
                f"页面 {page.id!r} 的 roi {inner.to_tuple()} 超出了父页面 "
                f"{parent.id!r} 的有效 roi {outer.to_tuple()} —— "
                "roi 是整棵子树的搜索范围，伸到父页面框外会在'父页面不存在'的"
                "地方去找自己的特征（表现为偶尔认错页面）"
            )

    def add_many(self, pages: Iterable[tuple[PageNode, PageId | None]]) -> None:
        """批量加。**按父先子后的顺序**给（loader 解析嵌套结构时天然满足）。"""
        for page, parent in pages:
            self.add(page, parent)

    @classmethod
    def from_nested(cls, data: Mapping[str, Any]) -> PageTree:
        """从嵌套字典建树（YAML 配置用）。

        期望结构（``id`` 由嵌套位置自动推导成路径形式）::

            states:
              home:                              # id = "home"
                name: 首页
                kind: group                      # 父节点是纯分类，不写 queries
                children:
                  lobby:                         # id = "home/lobby"
                    queries:
                      - {type: ImageQuery, template: home/logo.png}
                  jingji:
                    queries: [...]
                    children:
                      battle:                    # id = "home/jingji/battle"
                        roi: [600, 400, 680, 500]   # 相对父节点

              # 全局叠加层：不属于任何父节点
              network_error:
                kind: overlay
                priority: 100
                queries:
                  - {type: ImageQuery, template: common/network_error.png}

        ``queries`` 里的字典由 ``query_from_dict`` 还原成 Query 对象
        （在 ``gamebot.atomic.query`` 里）。

        ## 为什么这个方法留在状态层是桩

        配置驱动的解析入口是 ``gamebot.flow.loader.parse_pages``。
        树是由**上面那层**（流程层的 loader）按配置搭出来的，状态层只提供
        :meth:`add` / :meth:`add_many` 这些原语 —— 这样状态层不需要知道
        "配置长什么样"，也就不会为了解析配置去 import 流程层
        （``tests/test_structure.py`` 的 AST 检查盯着这条依赖方向）。

        所以这里**显式地不实现**，而不是留个 ``pass`` 让人以为它坏了。
        """
        raise NotImplementedError(
            "配置驱动的状态树解析在 gamebot.flow.loader.parse_pages；"
            "状态层只提供 add/add_many 这些原语（见类 docstring）"
        )

    # ------------------------------------------------------------------ #
    # 查询结构
    # ------------------------------------------------------------------ #
    @property
    def pages(self) -> Mapping[PageId, PageNode]:
        return dict(self._pages)

    @property
    def roots(self) -> tuple[PageId, ...]:
        return tuple(self._roots)

    def __len__(self) -> int:
        return len(self._pages)

    def __contains__(self, page_id: object) -> bool:
        return page_id in self._pages

    def get(self, page_id: PageId) -> PageNode | None:
        return self._pages.get(page_id)

    def require(self, page_id: PageId) -> PageNode:
        """取页面，不存在就抛（装配期用，别静默返回 None）。"""
        page = self._pages.get(page_id)
        if page is None:
            raise StateError(f"页面不存在: {page_id!r}")
        return page

    def parent_of(self, page_id: PageId) -> PageId | None:
        return self._parent.get(page_id)

    def children_of(self, page_id: PageId | None = None) -> tuple[PageNode, ...]:
        """子页面，按 ``priority`` 降序（同级的先试谁）。

        ``page_id=None`` 时返回所有顶层页面。
        """
        ids = self._roots if page_id is None else self._children.get(page_id, [])
        pages = [self._pages[i] for i in ids if i in self._pages]
        return tuple(sorted(pages, key=lambda p: p.priority, reverse=True))

    def siblings_of(self, page_id: PageId, *, include_self: bool = False) -> tuple[PageNode, ...]:
        peers = self.children_of(self.parent_of(page_id))
        if include_self:
            return peers
        return tuple(p for p in peers if p.id != page_id)

    def overlays_of(self, page_id: PageId) -> tuple[PageLeaf, ...]:
        """某个页面的叠加层子节点（弹窗），按优先级降序。"""
        return tuple(
            p for p in self.children_of(page_id) if isinstance(p, PageLeaf) and p.is_overlay
        )

    def global_overlays(self) -> tuple[PageLeaf, ...]:
        """顶层叠加层 —— 任意页面上都可能出现的弹窗。"""
        return tuple(p for p in self.children_of(None) if isinstance(p, PageLeaf) and p.is_overlay)

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

    def walk(self, order: str = "dfs") -> Iterator[PageNode]:
        """遍历所有页面。``dfs``（先父后子，默认）或 ``bfs``。"""
        queue: list[PageId] = list(self._roots)
        collected: list[PageNode] = []
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

    def leaves(self) -> tuple[PageNode, ...]:
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
    # 单页匹配
    # ------------------------------------------------------------------ #
    def match(
        self,
        frame: Frame,
        page: Page | PageId,
        *,
        roi: Region | None = None,
        confidence: float | _Unset | None = _UNSET,
    ) -> ActionResult[dict[str, Any]]:
        """判断某一页在**这一帧**上成不成立。

        :param roi: 覆盖页面自身的 roi；不传就用 :meth:`effective_roi`。
        :param confidence: 覆盖查询各自的阈值；**不传则各查询用自己的**。
            页面显式写的 ``confidence`` 由 :meth:`locate` 传进来
            （见 :attr:`Page.effective_confidence`）。
        :return: 命中 ``success(value={"values":..., "scores":...})``；
            未命中 ``not_found``（message 说明是 exclusions 否决还是哪个查询没中）；
            查询求值出错 ``error`` —— 这一条**必须**和"未命中"分开：
            模板路径写错会让这一页永远认不出来，把它当"未命中"排查时
            会以为游戏画面变了。
        """
        target = self._pages.get(page) if isinstance(page, str) else page
        if target is None:
            return ActionResult.error(f"页面不存在: {page!r}")

        # 分类节点（GROUP）**按定义不参与匹配**。少了这一句它会因为"没有 queries"
        # 而永远命中 —— 那会让一个纯分类节点变成"当前状态"，
        # 而它既不该出现在定位结果里，也没有流程节点认领它。
        if target.is_group:
            return ActionResult.not_found(f"{target.id!r} 是分类节点（kind: group），不参与匹配")

        # 到这里 `target` 一定是**状态节点**：`is_group` 只有 PageGroup 会是 True，
        # 而抽象基类 PageNode 进不了树（`add()` 拦掉了）。收窄一次，
        # 下面就能用 `exclude` / `queries` 这些只有状态才有的字段。
        if not isinstance(target, PageLeaf):  # pragma: no cover - 防御性
            return ActionResult.error(f"{target.id!r} 不是状态节点，无法匹配")

        if roi is None:
            roi = self.effective_roi(target.id)
        if isinstance(confidence, _Unset):
            confidence = target.effective_confidence

        # ① 否决条件优先：exclude 命中就不必再验 queries 了。
        #    顺序反过来的话，"结算画面"会先被父页面的 queries 认成"战斗中"。
        if target.exclude:
            vetoed = find_any_of(frame, list(target.exclude), short_circuit=True)
            if vetoed.ok:
                return ActionResult.not_found(
                    f"{target.id!r} 被 exclude 否决: {vetoed.message}"
                )
            if vetoed.status is ActionStatus.ERROR:
                return ActionResult.error(
                    f"页面 {target.id!r} 的 exclude 求值出错: {vetoed.message}"
                )

        # ② 没有 queries 的页面永远命中（pass-through 分组；空壳叶节点由 validate 拦掉）
        if not target.queries:
            return ActionResult.success({"values": {}, "scores": {}})

        try:
            specified = [self._specify(query, roi, confidence) for query in target.queries]
        except ValueError as exc:
            # roi 和查询自己的 region 完全不重叠 = 这个页面永远认不出来。
            # 静默返回"未命中"会把配置错误伪装成游戏画面变了。
            return ActionResult.error(f"页面 {target.id!r} 的搜索区域自相矛盾: {exc}")

        found = find_all_of(frame, specified)
        if found.status is ActionStatus.ERROR:
            return ActionResult.error(f"页面 {target.id!r} 的识别条件求值出错: {found.message}")
        if not found.ok:
            return ActionResult.not_found(
                f"页面 {target.id!r} 的识别条件未全部命中: {found.message}",
                results=found.meta.get("results"),
            )

        values: dict[str, Any] = {}
        scores: dict[str, float] = {}
        for index, child in enumerate(found.value or []):
            if not child.ok:
                continue
            name = self._label(target.queries[index], index)
            values[name] = child.value
            score = child.meta.get("score")
            if isinstance(score, (int, float)):
                scores[name] = float(score)
        return ActionResult.success({"values": values, "scores": scores})

    @staticmethod
    def _specify(
        query: Query,
        roi: Region | None,
        confidence: float | _Unset | None,
    ) -> Query:
        """把页面级的 roi / confidence 具化到单个查询上。

        三件事，缺一个都会出问题：

        1. **roi 和查询自己的 region 求交，谁也不覆盖谁**。覆盖 region 会让
           脚本作者显式写的框失效；反过来让 region 覆盖 roi，树剪枝（"子页面
           只看右下角"）就全废了 —— 而那是这棵树最大的性能收益来源；
        2. **只处理有 ``region`` 字段的查询**（Image/AllImages/Text/AllTexts/
           Compare）。``PixelQuery`` 用的是 ``point``、``NotQuery`` 里套的是
           别的查询，强行套 roi 是错的，原样返回；
        3. **求交为空直接抛**，不静默变成"永远未命中"。
        """
        if not hasattr(query, "region"):
            return query

        region = getattr(query, "region", None)
        if roi is not None:
            if region is None:
                region = roi
            else:
                region = roi.intersect(region)
                if region is None:
                    return _impossible(query, roi)

        updates: dict[str, Any] = {}
        if region is not getattr(query, "region", None):
            updates["region"] = region
        if not isinstance(confidence, _Unset) and hasattr(query, "confidence"):
            updates["confidence"] = confidence
        # query 声明成 Query（Protocol），mypy 不肯对它用 dataclasses.replace；
        # 运行期它一定是 dataclass。这是**唯一**一处必须 ignore 的地方。
        return replace(query, **updates) if updates else query  # type: ignore[type-var]

    @staticmethod
    def _label(query: Any, index: int) -> str:
        """给一个查询起个能在日志里认出来的名字。"""
        name = getattr(query, "template", None) or getattr(query, "text", None)
        return str(name) if name else f"query[{index}]"

    # ------------------------------------------------------------------ #
    # 定位：两条路径
    # ------------------------------------------------------------------ #
    def locate(
        self,
        frame: Frame,
        hint: PageId | None = None,
        *,
        expected: PageId | None = None,
        now: float = 0.0,
    ) -> ActionResult[PageMatch]:
        """定位当前帧是哪个状态（**快路径**：自顶向下找最深命中）。

        ## 两条路径，别混用

        * **快路径（本方法）**：正常一轮用它。``expected`` 是流程层自己的预期，
          先精确验它一下；不成再按 ``hint`` 优化过的顺序自顶向下走一遍。
          代价是"一两次匹配"。
        * **慢路径（:meth:`recover`）**：自检不过、或者快路径认不出来时才用它。
          从"最近的末梢"开始逐步扩大范围。代价高，但能把脚本救回来。

        每轮都跑慢路径等于每帧探测全树 —— 那和树存在的意义（剪枝）正好相反。

        ## 算法

        1. **``expected`` 优先**：它就是流程层说的"我应该在这儿"。
           命中就直接返回它（再扫一遍叠加层），一次匹配解决问题。
        2. 否则从 ``hint`` 的顶层祖先（或全部顶层）开始，**逐层下探**：
           ``GROUP`` 分类节点自己不匹配、直接下探子节点；命中的最深的那个
           **末梢状态**就是当前状态。
        3. 再扫叠加层：当前状态的 ``OVERLAY`` 子节点 + 全局叠加层。
        4. 一个都没命中 -> ``success(PageMatch(id=UNKNOWN_PAGE))``。

        ## 关键性质

        **``hint`` / ``expected`` 都不影响正确性。** ``expected`` 只决定
        "先试谁"，``hint`` 只决定"从哪一支开始试" —— 两者错了都只是多花几次
        匹配，结果和全量搜索一致。这是敢拿它们做优化的前提。

        ## 返回

        * ``success(PageMatch)`` —— 包括"认不出来"（``id=UNKNOWN_PAGE``）。
          **认不出来是有效结果，不是错误。**
        * ``error`` —— 只用于底层真出错（模板文件缺失、Matcher 抛异常）。
          把它当成"认不出来"会把配置错误伪装成游戏行为，极难排查。
        """
        attempts: list[PageAttempt] = []

        # ---- ① 先验流程层的预期（一次匹配） ----
        if expected and expected in self._pages:
            page = self._pages[expected]
            if isinstance(page, PageLeaf) and page.has_conditions:
                ok, _why, values = self._probe(frame, page, attempts)
                if ok:
                    overlays = self._scan_overlays(frame, expected, attempts, seen=set())
                    return ActionResult.success(
                        self._build_match(
                            frame, expected, values, overlays, attempts, now=now
                        )
                    )

        # ---- ② 自顶向下（hint 只用来少试几支） ----
        # pref_root：hint 的顶层祖先，用来把顶层候选压到一支。
        # 注意**不能**在这里就去 probe 顶层那个节点：它可能是 GROUP 分类节点
        # （探测必然不中），也可能只是 hint 的容器 —— 两种情况都会让
        # "hint 命中了"这个结论错误地建立在一个不成立的匹配上。
        pref_root: PageId | None = None
        if hint and hint in self._pages and not self._pages[hint].is_overlay:
            root = hint
            while self._parent.get(root) is not None:
                root = self._parent[root]  # type: ignore[assignment]
            if not self._is_guessable(f"{hint}/"):
                pref_root = root

        roots = self._searchable_children(None)
        if pref_root is not None:
            roots.sort(key=lambda p: p.id != pref_root)

        current_id = UNKNOWN_PAGE
        current_values: dict[str, Any] = {}
        hint_verified = False

        # 先精确验 hint 自己：它在"应该在这儿"这件事上比"顶层那一支"
        # 精确得多 —— 上一步的预期没命中时基本就是它变了。
        hint_page = self._pages.get(hint) if hint else None
        if (
            hint
            and isinstance(hint_page, PageLeaf)
            and not hint_page.is_overlay
        ):
            ok, _why, values = self._probe(frame, hint_page, attempts)
            if ok:
                current_id, current_values, hint_verified = hint_page.id, values, True

        # ---- 逐层下探：找到**最深的一个记录信息的状态** ----
        #
        # 分类节点（GROUP）**不参与匹配，但必须能穿过它**：它既不可能是结果，
        # 也不能挡住它的子节点。所以候选列表在进入循环前就把分类节点展开掉 ——
        # 让"穿过分类节点"和"命中了谁"彻底分开，循环里只剩一种情况（叶子状态）。
        candidates: list[PageLeaf] = self._expand_groups(
            self._searchable_children(current_id) if hint_verified else roots
        )
        while candidates:
            hit_page: PageLeaf | None = None
            hit_values: dict[str, Any] = {}
            for page in candidates:
                ok, _why, values = self._probe(frame, page, attempts)
                if ok:
                    hit_page, hit_values = page, values
                    break
            if hit_page is None:
                break  # 这一层全没中 -> 当前结果就是最深命中者
            current_id, current_values = hit_page.id, hit_values
            candidates = self._expand_groups(self._searchable_children(hit_page.id))

        overlays = self._scan_overlays(frame, current_id, attempts, seen=set())
        return ActionResult.success(
            self._build_match(frame, current_id, current_values, overlays, attempts, now=now)
        )

    def _expand_groups(self, pages: Iterable[PageNode]) -> list[PageLeaf]:
        """把候选里的分类节点就地展开成它们的子节点，返回**只剩状态节点**的列表。

        分类节点没有识别条件 —— 别说是匹配，它连 ``queries`` 字段都没有
        （见 :class:`PageGroup`）。所以它绝不能留在候选列表里：那会让整层搜索
        在第一项就"看起来失败"。它唯一的作用是提供 ROI 继承和组织结构。

        返回类型是 ``list[PageLeaf]`` 而不是 ``list[PageNode]`` —— 让**调用方**
        不必再对每个候选 ``isinstance`` 一次。收窄就发生在这里，一处。
        """
        expanded: list[PageLeaf] = []
        queue = list(pages)
        while queue:
            page = queue.pop(0)
            if isinstance(page, PageGroup):
                queue = self._searchable_children(page.id) + queue
                continue
            if isinstance(page, PageLeaf):
                expanded.append(page)
        return expanded

    #: 重定位最多搜几轮。**这是一个常数**（配 ``EngineOptions.recover_passes``
    #: 可以覆盖）：一轮落空说明"这一瞬间的画面不属于任何状态"，
    #: 但过场动画会持续几帧 —— 第二轮给画面一点时间变成可识别的样子。
    #: 再多就没有意义了：同一个画面探第二遍和第三遍没有区别。
    RECOVER_PASSES = 2

    def recover(
        self,
        frame: Frame,
        near: PageId | None = None,
        *,
        recent: Sequence[PageId] = (),
        passes: int | None = None,
        now: float = 0.0,
    ) -> ActionResult[PageMatch]:
        """**慢路径**：找真实状态。先查"最近待过的"队列，再沿树扩散。

        用途只有一个：**意外时的重定位**（自检不过、或者快路径认不出来）。
        正常一轮别调它。

        ## 搜索顺序（三圈，从最可能到最不可能）

        ```
        第 0 圈：near 自己（"我以为我在的那个"）
        第 1 圈：recent 队列 —— 最近待过的几个状态，最近的先试
        第 2 圈：沿树向上扩散（near 所在分组 → 上一层 → …→ 根），
                每层内部按 ROI 面积升序
        最后：  全局叠加层 + 认不出来
        ```

        **为什么队列插在扩散前面**：扩散是从"我以为什么"往外爬，而队列记的是
        "**我实际刚去过什么**"。游戏里绝大多数意外是"点了按钮、进了下一屏"——
        目标状态往往就在最近去过的那几个里，一两次匹配就找到了，
        不用把沿途每个分组都扫一遍。

        ## 去重

        每一轮内部，每个状态**最多探一次**（``probed`` 集合）。同一个状态既可能
        出现在队列里、又落在扩散路径上，不去重就会重复匹配 —— 白花开销，
        而且 ``attempts`` 里会出现两条一样的记录，排查时看着像"试了两次"。

        去重**不跨轮**：轮数存在的意义正是"画面可能在两次尝试之间变了，
        再探一遍"，跨轮共用的话第二轮一个状态都不会探、两轮等于一轮。

        ## 两轮，以及"真的没有了"怎么表达

        一轮搜完一个都没命中，就整体再搜一遍（最多 :attr:`RECOVER_PASSES` 轮）。
        全部落空时返回 ``unknown``，并且把 :attr:`PageMatch.exhausted` **标起来** ——
        它区分两种情况：

        * ``unknown`` 但 ``exhausted=False``：**没搜完**（比如快路径先短路了）；
        * ``unknown`` 且 ``exhausted=True``：**树里所有状态都试过了**，
          画面确实不属于任何已知状态。

        :param near: 从哪附近开始找。一般是"我以为我在的那个状态"。
            给了不存在的 id 就退化成从根开始的全量搜索。
        :param recent: 最近待过的状态 id，**最近的排前面**（见
            ``PageTracker.recent_ids``）。空的就跳过那一圈。
        :param passes: 搜几轮。``None`` 用 :attr:`RECOVER_PASSES`。
        :return: 和 :meth:`locate` 同构；认不出来是 ``success(UNKNOWN_PAGE)``。
            ``PageMatch.attempts`` 记录**试过谁、结果如何** ——
            "为什么最后认成了这个"必须能直接读出来。
        """
        attempts: list[PageAttempt] = []
        near_page = self._pages.get(near) if near else None
        rounds = max(1, self.RECOVER_PASSES if passes is None else passes)

        for round_index in range(rounds):
            found = self._recover_once(
                frame,
                near_page=near_page,
                recent=recent,
                probed=set(),  # 每一轮用新的 —— 见上面"去重不跨轮"
                attempts=attempts,
                now=now,
            )
            if found is not None:
                return found
            if round_index + 1 < rounds:
                log.info(
                    "重定位第 %d 轮没找到（已试 %d 次），再来一轮",
                    round_index + 1,
                    len(attempts),
                )

        # ---- 全部落空 ----
        # 最后再扫一遍叠加层：主状态认不出来，但可能只是弹了个窗 / 掉线了
        overlays = self._scan_overlays(frame, UNKNOWN_PAGE, attempts, seen=set())
        match = self._build_match(
            frame, UNKNOWN_PAGE, {}, overlays, attempts, now=now
        )
        match.exhausted = True
        log.warning(
            "重定位失败：%d 次匹配（%d 轮、每轮都把树里所有状态试一遍）都没命中",
            len(attempts),
            rounds,
        )
        return ActionResult.success(match)

    def _recover_once(
        self,
        frame: Frame,
        *,
        near_page: PageNode | None,
        recent: Sequence[PageId],
        probed: set[PageId],
        attempts: list[PageAttempt],
        now: float,
    ) -> ActionResult[PageMatch] | None:
        """走完三圈。命中就返回结果，全落空返回 ``None``（交给下一轮）。"""

        def try_page(page: PageLeaf) -> ActionResult[PageMatch] | None:
            """探一页；命中就组装结果，否则 None。**已探过的直接跳过。**"""
            if page.id in probed or not page.has_conditions:
                return None
            probed.add(page.id)
            ok, _why, values = self._probe(frame, page, attempts)
            if not ok:
                return None
            overlays = self._scan_overlays(frame, page.id, attempts, seen=set())
            return ActionResult.success(
                self._build_match(frame, page.id, values, overlays, attempts, now=now)
            )

        # ---- 第 0 圈：near 自己 ----
        if isinstance(near_page, PageLeaf):
            hit = try_page(near_page)
            if hit is not None:
                return hit

        # ---- 第 1 圈：最近待过的队列（最近的先试）----
        for page_id in recent:
            page = self._pages.get(page_id)
            if isinstance(page, PageLeaf):
                hit = try_page(page)
                if hit is not None:
                    return hit

        # ---- 第 2 圈：沿树向上扩散：每层把"这一层分组的全部末梢"试一遍 ----
        # 起点是 near 的父分组（near 自己试过了）；near 不在树里就从根开始。
        level = self._parent.get(near_page.id) if near_page is not None else None
        visited_levels: set[PageId | None] = set()
        while level not in visited_levels:
            visited_levels.add(level)
            for page in self._states_below(level, exclude_ids=set()):
                hit = try_page(page)
                if hit is not None:
                    return hit
            if level is None:
                break
            level = self._parent.get(level)

        return None

    # ------------------------------------------------------------------ #
    # 定位用的内部件
    # ------------------------------------------------------------------ #
    def _searchable_children(self, page_id: PageId | None) -> list[PageNode]:
        """下一层该试哪些节点。

        排除**叠加层**（它是"盖在某一页上的一层"，由 :meth:`_scan_overlays` 单独
        处理；当成主状态候选的话，一个断线弹窗会把主状态整个顶掉，位置校验随即
        认为"期望 home、实测 net"）。

        分类节点**保留**在结果里 —— 它会被正常下探（:meth:`locate` 的循环），
        只是自己不进结果。
        """
        return [p for p in self.children_of(page_id) if not p.is_overlay]

    def _states_below(
        self, page_id: PageId | None, *, exclude_ids: set[PageId]
    ) -> list[PageLeaf]:
        """某一层分组的**全部末梢状态**（不含 group / 叠加层），按"看起来更便宜"排序。

        排序目的是让扩散搜索**先试成本低的**（ROI 小 = 匹配像素少）：既快，
        也更不容易误判。"看得少"是这套设计一贯的偏好。

        两个必须排除的东西：

        * **group 分类节点** —— 它自己不记录信息，把它当状态报出去，
          定位结果里就会出现一个"永远认不出"的假状态（而且它还没节点认领）；
        * **叠加层** —— 它由 :meth:`_scan_overlays` 单独处理，不是主状态。
        """
        collected: list[PageLeaf] = []
        queue = list(self._searchable_children(page_id))
        while queue:
            page = queue.pop(0)
            if page.id in exclude_ids:
                continue
            if isinstance(page, PageGroup):
                queue.extend(self._searchable_children(page.id))
                continue
            if isinstance(page, PageLeaf) and page.queries:
                collected.append(page)
        return sorted(collected, key=self._cost)

    def _cost(self, page: PageNode) -> tuple[int, int, int]:
        """越小的越先试：ROI 面积 -> 查询个数 -> 深度。"""
        roi = self.effective_roi(page.id)
        area = roi.area if roi is not None else 1 << 30
        count = len(page.queries) if isinstance(page, PageLeaf) else 0
        return (area, count, self.depth_of(page.id))

    def _state_confidence(self, page_id: PageId) -> float:
        """某个状态的阈值；未知 / 分类节点给 0.0（PageMatch 只是记录用）。"""
        page = self._pages.get(page_id)
        return page.confidence if isinstance(page, PageLeaf) else 0.0

    def _probe(
        self,
        frame: Frame,
        page: Page,
        attempts: list[PageAttempt],
    ) -> tuple[bool, str, dict[str, Any]]:
        """试一个页面，把痕迹写进 ``attempts``。

        :return: ``(命中?, 说明, values)``。求值出错按**未命中**处理并留下
            一条带 "求值出错" 的说明 —— 单帧定位没法用返回值表达"这一页的
            配置坏了"，而整棵树为了一页的配置错误停摆也不对。
            这种痕迹会出现在 ``PageMatch.attempts`` 里，排查时一眼能看到。
        """
        result = self.match(frame, page)
        if result.status is ActionStatus.ERROR:
            attempts.append(PageAttempt(page.id, False, result.message))
            log.warning("页面 %r 识别出错（按未命中处理）: %s", page.id, result.message)
            return False, result.message, {}
        if not result.ok:
            attempts.append(PageAttempt(page.id, False, result.message))
            return False, result.message, {}
        payload = result.value or {}
        scores = payload.get("scores") or {}
        best = max(scores.values()) if scores else 0.0
        attempts.append(PageAttempt(page.id, True, "命中", best))
        return True, "命中", dict(payload.get("values") or {})

    def _scan_overlays(
        self,
        frame: Frame,
        page_id: PageId,
        attempts: list[PageAttempt],
        *,
        seen: set[PageId],
    ) -> tuple[PageId, ...]:
        """扫叠加层：当前状态的 ``OVERLAY`` 子节点 + 顶层全局叠加层。

        两者**都收**：前者是"这一页专属的弹窗"，后者是"哪一页都可能出现的
        弹窗"（断线重连、网络错误）。按 ``priority`` 降序。
        """
        candidates: list[Page] = []
        if page_id != UNKNOWN_PAGE:
            candidates.extend(self.overlays_of(page_id))
        candidates.extend(self.global_overlays())

        matched: list[PageId] = []
        for page in sorted(candidates, key=lambda p: p.priority, reverse=True):
            if page.id in seen:
                continue
            seen.add(page.id)
            ok, _why, _values = self._probe(frame, page, attempts)
            if ok:
                matched.append(page.id)
        return tuple(matched)

    def _build_match(
        self,
        frame: Frame,
        page_id: PageId,
        values: dict[str, Any],
        overlays: tuple[PageId, ...],
        attempts: list[PageAttempt],
        *,
        now: float,
    ) -> PageMatch:
        return PageMatch(
            id=page_id,
            path=self.path_of(page_id) if page_id != UNKNOWN_PAGE else (),
            overlays=overlays,
            confidence=self._state_confidence(page_id),
            observed_at=now,
            frame_id=getattr(frame, "frame_id", -1),
            values=values,
            attempts=attempts,
            message="" if page_id != UNKNOWN_PAGE else "没有任何状态命中",
        )

    def _is_guessable(self, prefix: str) -> bool:
        """有没有页面的 id 真的以 ``prefix`` 打头（hint 能不能真省下工作）。

        **按 id 前缀判断，而不是按 parent 链**：id 的前缀是硬约束
        （"a/b" 的子页面只能写成 "a/b/..."），parent 链不是 ——
        一个页面完全可以写成 ``Page("battle", parent="home")`` 而 id 是
        ``home/jingji/battle``。按 parent 链判断会以为 hint 下面还有东西，
        白跑一趟"必然不成立"的确认。
        """
        return any(page_id.startswith(prefix) for page_id in self._pages)

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
        5. **状态节点必须有识别条件**：没有条件的叶节点永远不会被认出来
           （多半是忘了写 ``queries``）。只想做组织结构就标 ``kind: group`` ——
           分类节点按定义不记录信息，给它写 ``queries`` 反而是配置错误；
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
            problems.append("状态树是空的")
        if not self._roots:
            problems.append("没有任何顶层页面")

        for page_id in self._pages:
            if not page_id or not page_id.strip():
                problems.append("存在空 id 的页面")

        for page in self._pages.values():
            children = [c for c in self._children.get(page.id, []) if c in self._pages]
            label = repr(page.id) if page.id else "<空 id>"

            if isinstance(page, PageGroup):
                # 分类节点**不可能**有 queries（那是 PageLeaf 才有的字段），
                # 所以这里不再有"给它写 queries"那条检查 —— 它变成了 TypeError。
                if not children:
                    problems.append(
                        f"分类节点 {page.id!r} 没有任何子节点 —— "
                        "空分组没有任何意义，要么给它加子节点，要么删掉它"
                    )
                continue

            if not isinstance(page, PageLeaf):  # pragma: no cover - 进不了树
                continue

            if not children and not page.queries:
                problems.append(
                    f"状态节点 {page.id!r} 既没有识别条件又是叶节点 —— "
                    "它永远不会被认出来（多半是忘了写 queries）。"
                    "只想做分组的话请用 PageGroup。"
                )
            if page.is_overlay and children:
                problems.append(
                    f"叠加层 {page.id!r} 不该有子页面 —— 弹窗里套层级会让定位结果无法解释"
                )
            if page.terminal and children:
                problems.append(f"终态页面 {label} 不该有子页面")

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
            raise StateError("状态树校验失败:\n  - " + "\n  - ".join(problems))

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


def _impossible(query: Any, roi: Region) -> NoReturn:
    """页面 roi 和查询自己的 region 完全不重叠时抛出去。

    为什么这必须是**错误**而不是"未命中"：这两块区域都是脚本作者显式写的，
    交为空说明配置自相矛盾 —— 这一页从此永远认不出来。静默返回 not_found
    会让现象表现为"这个页面有时候认不出"，而真正的原因是它**从来没有**
    被搜索过。message 里把两个框都打出来，一眼就能看到错在哪。
    """
    mine = getattr(query, "region", None)
    label = getattr(query, "template", None) or repr(query)
    raise ValueError(
        f"页面 roi {roi.to_tuple()} 与查询 {label!r} 的 region "
        f"{mine.to_tuple() if mine is not None else 'None'} 没有交集"
    )
