"""从选将面板退回主界面。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.types import ActionResult
from games.mingjiangsha.utils import go_back

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["leave_pick"]

#: 按 Esc 之后等主界面回来（秒）。
LEAVE_SETTLE = 0.8


def leave_pick(ctx: RunContext) -> ActionResult[Any]:
    """已选将 → 按 Esc 关闭选将面板。"""
    return go_back(ctx, settle=LEAVE_SETTLE)
