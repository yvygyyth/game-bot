"""步骤 —— **就是一个函数**。

## 一个步骤长什么样

```python
def click_skill(ctx: RunContext) -> ActionResult[Any]:
    found = ctx.frame().find_image("jingji/skill.png", region=TEAM_ROI, confidence=0.85)
    if not found.ok:
        return found
    return actions.click_source_point(ctx.session, found.value)
```

没有基类、没有 ``__init__``、没有 ``self``。想带参数就用 ``functools.partial``：

```python
Node("battle", steps=[partial(click_image, "skill.png", region=TEAM_ROI), sleep(0.5)])
```

## 为什么改了（原来是一套类体系）

原来每个步骤是个 ``Step`` 子类，实测**壳占了 53%**：``WaitStep`` 55 行里
31 行是壳、真正的逻辑只有 2 行（一个参数校验），其余全在把参数搬进 ``self``。
而"一个步骤"要回答的问题只有一个 —— **做什么**。

改成函数之后：

* **写一个步骤 = 写一个函数**，想做什么一目了然；
* 参数就是函数参数，编辑器能提示、`mypy` 能查（类那套要靠 ``__init__`` 签名，
  也能查，但要先写十几行才轮得到）;
* 名字就是 ``func.__name__``，不用再传 ``name=`` 或者覆写 ``describe()``。

## 步骤**不**管什么

* **不管重试 / 超时 / 失败处理** —— 失败了（多半是识图没命中）就让结果如实返回，
  上层会拿实测状态去重定位（见 ``flow/engine.py``）。这是这套设计的核心：
  **流程写的是"理想的执行状态"**，偏离了就归位，而不是在步骤里补重试；
* **不管轮询等待** —— "等某张图出现"是原子层的能力
  （``atomic/combinators.py`` 的 ``wait_any_of`` / ``wait_disappear`` /
  ``wait_until`` / ``wait_stable``，它们自带 ``timeout`` / ``interval``）。
  以前有个 ``WaitStep`` 把 ``wait_disappear`` 原样转了一手 —— 那是重复，删了；
* **不管记账** —— 想记就调 ``ctx.log(...)``（见 ``context.py``），
  框架不在每步后面偷偷写日志。

## 契约：只有两条

1. 签名是 ``(ctx: RunContext) -> ActionResult[Any]``；
2. **失败用返回值表达，不要抛异常** —— 异常只留给真正的意外
   （后端崩了、装配错了），以及 ``Cancelled``（表示"别再继续了"）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from gamebot.types import ActionResult

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["StepFunc", "describe_step", "step_name"]


@runtime_checkable
class StepFunc(Protocol):
    """步骤的接口 —— **就是一个可调用对象**。

    用 ``Protocol`` 而不是基类：函数天然满足它，不需要继承任何东西。
    需要带参数时用 ``functools.partial`` 包一层，它同样满足。
    """

    def __call__(self, ctx: RunContext) -> ActionResult[Any]: ...


def step_name(step: Any) -> str:
    """这一步叫什么（进日志和报告）。

    依次看 ``functools.partial`` 包着的那个函数、``__name__``、最后退回类型名 ——
    ``partial`` 自己没有 ``__name__``，不看里面就会显示成 "partial"，
    日志里一片 "partial" 等于没有名字。
    """
    inner = getattr(step, "func", None)
    if inner is not None:
        return step_name(inner)
    return getattr(step, "__name__", None) or type(step).__name__


def describe_step(step: Any) -> str:
    """给日志用的单行描述。

    函数没有 docstring 时退回名字 —— 不编造内容。
    """
    doc = (getattr(step, "__doc__", None) or "").strip()
    if doc:
        return doc.splitlines()[0]
    inner = getattr(step, "func", None)
    if inner is not None:
        return describe_step(inner)
    return step_name(step)
