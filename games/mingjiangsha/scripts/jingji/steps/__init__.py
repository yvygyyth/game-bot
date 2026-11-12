"""竞技场 —— 步骤（**一个步骤就是一个函数**）。

## 走一遍整个流程

| 状态 | 步骤 | 干什么 |
|---|---|---|
| `lobby` | :func:`enter_jingji` | 移到熊猫头 → 点它 → 进竞技场 |
| `jj/before_create` | :func:`create_team` | 点「创建队伍」 |
| `jj/after_create` | :func:`add_pet` | 点「添加伙伴」 |
| `jj/after_add` | :func:`start_match` | 点「开始匹配」 |
| `tip/unchecked` | :func:`check_tip` | 勾「本次登录不再提示」 |
| `tip/checked` | :func:`confirm_tip` | 点「确定」，关掉提示框 |
| `select` | :func:`pick_general` | 点第 1 张武将卡 + 点「确定」 |
| `fight/hand` | :func:`advance_fight` | 取消换牌 → 麻花结 → 投降 → 确认 |
| `fight/victory` | :func:`finish_round` | 点空白区 → 下一步 → 确认（+ 记一局） |

> 按钮点击走**四种家族方法**（``click_gold_glow`` / ``click_gold_frame``
> / ``click_cyan_glow`` / ``click_gold_frame``），只比**边框环**、不认文字，
> 所以步骤里不再为每句文案单独裁图。仍保留文字模板的两处是
> "等它出现再点"的 `wait_for`（下一步 / 投降序列）—— 那里的重点是**等待**。

## 这些步骤**不做**的三件事

1. **不重试** —— 失败（多半是识图没命中）如实返回，上层拿实测状态去**重定位**；
2. **不轮询等待** —— "等某个画面出现"是原子层 ``wait_*`` 的事；
3. **不判断游戏状态** —— ``if ctx.page_id == ...`` 属于流程层（边条件 / 关联表）。

提示框的"弹 / 没弹 / 勾没勾"是**状态**（`tip/*`），由流程图的边分流，
不再是步骤里的 if —— 见 :mod:`.start_match` 与 ``pages.py`` / ``graph.py``。
"""

from __future__ import annotations

from .advance_fight import advance_fight
from .enter_jingji import enter_jingji
from .finish_round import finish_round, noop
from .pick_general import pick_general
from .start_match import add_pet, check_tip, confirm_tip, create_team, start_match

__all__ = [
    "add_pet",
    "advance_fight",
    "check_tip",
    "confirm_tip",
    "create_team",
    "enter_jingji",
    "finish_round",
    "noop",
    "pick_general",
    "start_match",
]
