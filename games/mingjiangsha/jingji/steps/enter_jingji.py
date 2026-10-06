"""在首页点「竞技」入口，进竞技场。

**一个步骤就是一个函数** —— 没有基类，参数就是函数参数，
名字就是函数名。见 :mod:`gamebot.execution.step`。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.types import ActionResult

from ..shortcuts import click_jingji_entry

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["DEFAULT_SETTLE", "enter_jingji"]

#: 点完默认等多久（秒）。**只作为声明的镜像** —— 真正生效的值来自表单参数
#: ``jingji.settle``，这里留着是为了"没填表单直接跑"时仍有个合理行为。
DEFAULT_SETTLE = 1.2


def enter_jingji(ctx: RunContext) -> ActionResult[Any]:
    """在首页点「竞技」入口。找不到就**如实返回**，绝不"就近点一下试试"。

    点完**等一下再让出**：点下去到竞技场渲染出来有个过渡，不等的话下一轮
    还在首页（视觉上"多点了一下"），而且会白跑一轮识别。

    等多久来自**运行参数** ``jingji.settle``（表单可调）—— 它在步骤执行时现读，
    所以同一个函数在两次运行里可以用不同的值。
    """
    result = click_jingji_entry(ctx)
    if not result.ok:
        return result
    ctx.sleep(ctx.param("jingji.settle", DEFAULT_SETTLE))
    # 画面变了，作废旧帧 —— 下一轮必须重新截，否则会拿旧图判断
    ctx.invalidate_frame()
    return result
