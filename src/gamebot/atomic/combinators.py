"""L4 组合子层 —— 多个查询之间如何协作。

两个子族：

**帧内组合子**（同步、快、只吃一帧）::

    find_all_of     # Promise.all   全部命中才成功
    find_any_of     # Promise.race  任一命中即成功
    find_first_of   # 按顺序取第一个成功的
    find_none_of    # 全部失败才成功（判断"这些都不在"）
    count_hits      # 统计命中数量

**跨帧组合子**（内部自己循环截图，慢、吃时间预算）::

    wait_any_of     # 等到任一命中
    wait_all_of     # 等到全部命中
    wait_until      # 等到任意谓词成立
    wait_stable     # 等到画面稳定（连续 N 帧相似）
    wait_disappear  # 等到某查询不再命中

设计约定：

* 帧内组合子**绝不截图**。帧必须由调用方传进来，保证一致性。
* 跨帧组合子**自己截图**，所以签名里第一个参数是 ``session``。
* 所有组合子统一返回 ``ActionResult``；跨帧失败返回 ``timeout``，
  帧内失败返回 ``not_found``（语义不能混）。
* ``wait_*`` 的失败结果里会带 ``meta["last"]``，即最后一次子结果 ——
  debug 时非常有用，不要丢。
* **效率提示**：五个查询用 ``find_all_of`` 是一帧一次匹配（共 5 次匹配、1 次截图），
  比"5 个查询各截一次图"快且正确。能用帧内组合子就别写 5 行独立查询。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from ..types import ActionResult, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from .frame import Frame
    from .query import Query
    from .session import Session

log = get_logger("atomic.combinators")

__all__ = [
    "count_hits",
    "find_all_of",
    "find_any_of",
    "find_first_of",
    "find_none_of",
    "wait_all_of",
    "wait_any_of",
    "wait_disappear",
    "wait_stable",
    "wait_until",
]


# --------------------------------------------------------------------------- #
# 帧内组合子
# --------------------------------------------------------------------------- #
def find_all_of(
    frame: Frame,
    queries: Sequence[Query],
) -> ActionResult[list[ActionResult[Any]]]:
    """全部命中才成功（``Promise.all`` 语义）。

    :return: 成功 ``success(value=[每个子结果, ...], **{})``；
             失败 ``not_found(value=None, results=[所有子结果])``。
             **部分命中时也返回失败**，但要靠 ``meta["results"]`` 告诉调用方哪些中了。
    """
    raise NotImplementedError("待实现：逐个 run，遇到失败即 not_found(results=...)")


def find_any_of(
    frame: Frame,
    queries: Sequence[Query],
    short_circuit: bool = True,
) -> ActionResult[Any]:
    """任一命中即成功（``Promise.race`` 语义）。

    :param short_circuit: True 第一个成功就返回；False 跑完所有查询，
        把**所有**成功的子结果都放进 ``value``（做"多目标同时存在"统计时用）。
    """
    raise NotImplementedError("待实现：注意 short_circuit 分支的返回形状不同")


def find_first_of(
    frame: Frame,
    queries: Sequence[Query],
) -> ActionResult[Any]:
    """按列表顺序依次执行，返回第一个成功的。

    和 ``find_any_of(short_circuit=True)`` 的区别：这里**顺序是语义的一部分**，
    用于表达优先级（先找"确认弹窗"，再找"主界面按钮"）。
    """
    raise NotImplementedError("待实现：顺序遍历，第一个成功即返回")


def find_none_of(
    frame: Frame,
    queries: Sequence[Query],
) -> ActionResult[bool]:
    """全部失败才成功。用于判断"这些东西都不在屏幕上"。

    注意：子查询如果返回 ``error``（而不是 not_found），这里**必须**整体失败 ——
    错误不等于"不在"，把异常当成"没看到"会导致流程误判。
    """
    raise NotImplementedError("待实现：任一 success 或 error 都算整体失败")


def count_hits(
    frame: Frame,
    queries: Sequence[Query],
) -> ActionResult[int]:
    """统计命中的查询数量，返回 ``success(value=int)``。

    不关心是哪些中了。用于打分、投票、优先级排序。
    """
    raise NotImplementedError("待实现")


# --------------------------------------------------------------------------- #
# 跨帧组合子（自己循环截图）
# --------------------------------------------------------------------------- #
def wait_any_of(
    session: Session,
    queries: Sequence[Query],
    timeout: float = 10.0,
    interval: float = 0.3,
    short_circuit: bool = True,
) -> ActionResult[Any]:
    """轮询截图 + ``find_any_of``，直到任一命中或超时。

    每次轮询产生新 Frame（不缓存，必须重新截图）。
    失败时返回 ``timeout``，``meta["last"]`` 是最后一帧的子结果，
    ``meta["frames"]`` 是轮询次数。
    """
    raise NotImplementedError("待实现：循环 session.capture() + find_any_of + sleep")


def wait_all_of(
    session: Session,
    queries: Sequence[Query],
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[list[ActionResult[Any]]]:
    """轮询截图 + ``find_all_of``，直到全部命中或超时。

    **重要语义**：全部命中必须在**同一帧**里成立。跨帧"先看到 A、再看到 B"
    不算数 —— 否则会漏掉"加载动画一闪而过"这类竞态。
    """
    raise NotImplementedError("待实现")


def wait_until(
    session: Session,
    predicate: Callable[[Frame], bool],
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[Frame]:
    """轮询截图，执行谓词，直到返回 True 或超时。

    :return: 成功时 ``success(value=命中的那帧)`` —— 把帧交出去，
             调用方可以继续在同一帧上做后续判断，避免时序漂移。
    """
    raise NotImplementedError("待实现")


def wait_stable(
    session: Session,
    region: Region,
    threshold: float = 0.98,
    stable_frames: int = 3,
    timeout: float = 10.0,
    interval: float = 0.1,
) -> ActionResult[Frame]:
    """等待画面稳定：连续 ``stable_frames`` 帧区域内相似度都 >= ``threshold``。

    用途：点击"进入下一关"后，等动画播完、UI 不再变化，再开始识图。
    比死等 ``sleep(3)`` 可靠得多。

    :return: 成功时返回稳定后的帧（可直接复用做查询）。
    """
    raise NotImplementedError("待实现：逐帧比对 region 相似度，连续达标即成功")


def wait_disappear(
    session: Session,
    query: Query,
    timeout: float = 10.0,
    interval: float = 0.3,
) -> ActionResult[Frame]:
    """轮询直到 ``query`` 不再命中。

    用途：等 loading 转圈消失、等弹窗关闭。
    成功时返回"确认消失"的那一帧。
    """
    raise NotImplementedError("待实现")
