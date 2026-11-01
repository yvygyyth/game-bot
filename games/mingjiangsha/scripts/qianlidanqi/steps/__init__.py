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
| `qianli/map` | :func:`choose_node` | 地图上点一个战斗节点 |
| `qianli/pre_battle` | :func:`start_battle` | 点「开始对局」 |
| `qianli/fight` | :func:`run_battle` | 取消换牌 → 托管 → 等结束 → 下一步 |
| `qianli/gift` | :func:`pick_gift` | OCR 三个武将名 → 按优先表点一个 |
| `qianli/gift_kind` | :func:`pick_kind` | 按优先表选信物/资助/驰援… |
| `qianli/shop/ba_qing` | :func:`buy_ba_qing` | 按 TOKEN_PRIORITY 买信物 → 退出 → 确认 |
| `qianli/rest` | :func:`choose_rest` | 随便点一个休息选项 → 回地图 |
| `qianli/pocket/choice` | :func:`choose_pocket` | 锦囊三选一随便点一个 |
| `qianli/pocket/confirm` | :func:`confirm_pocket` | 锦囊确认页点「确认」 |
| `qianli/end` | :func:`claim_reward` | 点「领取奖励」 |
| `qianli/end2` | :func:`close_congrats` | Esc 关「恭喜获得」，回选将 |

局内已实现：map → pre_battle → fight → gift → gift_kind，
结束走 end → end2 → 回 select1。商店/事件节点后续再补。
"""

from __future__ import annotations

from .enter import continue_run, enter_campaign, enter_qianli, open_pick, start_run
from .leave import leave_pick
from .pick import pick_general
from .run import (
    buy_ba_qing,
    choose_node,
    choose_pocket,
    choose_rest,
    claim_reward,
    close_congrats,
    close_skill_panel,
    confirm_pocket,
    pick_gift,
    pick_kind,
    run_battle,
    start_battle,
)

__all__ = [
    "buy_ba_qing",
    "choose_node",
    "choose_pocket",
    "choose_rest",
    "claim_reward",
    "close_congrats",
    "close_skill_panel",
    "confirm_pocket",
    "continue_run",
    "enter_campaign",
    "enter_qianli",
    "leave_pick",
    "open_pick",
    "pick_general",
    "pick_gift",
    "pick_kind",
    "run_battle",
    "start_battle",
    "start_run",
]
