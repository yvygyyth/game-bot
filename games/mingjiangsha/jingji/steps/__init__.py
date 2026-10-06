"""竞技场 —— 步骤（**一个步骤就是一个函数**）。

## 走一遍整个流程

| 状态 | 步骤 | 干什么 |
|---|---|---|
| `lobby` | :func:`enter_jingji` | 移到熊猫头 → 点它 → 进竞技场 |
| `jj/before_create` | :func:`create_team` | 点「创建队伍」 |
| `jj/after_create` | :func:`add_pet` | 点「添加伙伴」 |
| `jj/after_add` | :func:`start_match` | 点「开始匹配」+ 善后那个可能弹的提示框 |
| `select/idle` | :func:`pick_general` | 点第 1 张武将卡（→ 变成 `select/picked`） |
| `select/picked` | :func:`confirm_general` | 点「确定」 |
| `fight/hand` | :func:`advance_fight` | 取消换牌 → 麻花结 → 投降 → 确认 |
| `fight/done` | :func:`finish_round` | 点空白区 → 下一步 → 确认（+ 记一局） |

## 这些步骤**不做**的三件事

1. **不重试** —— 失败（多半是识图没命中）如实返回，上层拿实测状态去**重定位**；
2. **不轮询等待** —— "等某个画面出现"是原子层 ``wait_*`` 的事；
3. **不判断游戏状态** —— ``if ctx.page_id == ...`` 属于流程层（边条件 / 关联表）。

## 唯一的例外：`start_match` 里那段"可能弹窗"

「开始匹配」点下去**可能**弹一个提示框。它不用状态表达（理由见
`pages.py` 的模块 docstring），所以那段判断落在步骤里。
关键是它**不猜**：看不出弹窗就不做任何事，下一步照常按状态机走。
"""

from __future__ import annotations

from .advance_fight import advance_fight
from .enter_jingji import enter_jingji
from .finish_round import finish_round, noop
from .pick_general import confirm_general, pick_general
from .start_match import add_pet, create_team, start_match

__all__ = [
    "add_pet",
    "advance_fight",
    "confirm_general",
    "create_team",
    "enter_jingji",
    "finish_round",
    "noop",
    "pick_general",
    "start_match",
]
