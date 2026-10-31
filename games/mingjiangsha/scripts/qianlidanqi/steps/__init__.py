"""千里单骑 —— 步骤（一个步骤一个函数）。

| 状态 | 步骤 | 干什么 |
|---|---|---|
| `root` | :func:`enter_campaign` | 首页 → 点「战役」卡 |
| `campaign` | :func:`enter_qianli` | 战役页 → 点「千里单骑」卡 |
| `qianli/select1` | :func:`open_pick` | 点「选择武将」占位卡 |
| `qianli/select2` | :func:`pick_general` | 搜索入参武将 → 点第一个结果 |
| `qianli/select3` | :func:`leave_pick` | 按 Esc 退回主界面 |
| `qianli/select4` | :func:`start_run` | 点红色「开始挑战」 |
| `qianli/select5` | :func:`continue_run` | 点红色「继续挑战」，直接进局内 |

局内（`qianli/flow`）先做终态占位，步骤为空；后续再补。
"""

from __future__ import annotations

from .enter import continue_run, enter_campaign, enter_qianli, open_pick, start_run
from .leave import leave_pick
from .pick import pick_general

__all__ = [
    "continue_run",
    "enter_campaign",
    "enter_qianli",
    "leave_pick",
    "open_pick",
    "pick_general",
    "start_run",
]
