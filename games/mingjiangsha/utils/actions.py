"""名将杀 —— 跨功能共用的动作。

判断标准见 :mod:`games.mingjiangsha.game`：第二个功能也会原样用，才放这里。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.execution.builtins import press
from gamebot.types import ActionResult

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["go_back"]


def go_back(ctx: RunContext, *, settle: float = 0.0) -> ActionResult[Any]:
    """返回上一步（按 Esc）。"""
    return press(ctx, "esc", settle=settle)
