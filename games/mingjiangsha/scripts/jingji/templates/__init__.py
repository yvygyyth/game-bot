"""竞技场 —— 模板路径索引。

路径相对本目录（``games/mingjiangsha/scripts/jingji/templates/``）。
状态锚点与点击目标都写在这里，改路径只改这一处。

目录约定见同目录 ``README.md``：``父状态/文件名.png``；
``clicks/`` 只放不对应任何状态的点击目标。
"""

from __future__ import annotations

__all__ = [
    "T_AFTER_ADD",
    "T_AFTER_CREATE",
    "T_BEFORE_CREATE",
    "T_CLICK_FIGHT_CONFIRM",
    "T_FIGHT_HAND",
    "T_FIGHT_MENU",
    "T_FIGHT_NEXT",
    "T_FIGHT_SPACE",
    "T_FIGHT_SURRENDER",
    "T_LOBBY",
    "T_SELECT_HEALTH",
    "T_SELECT_SCREEN",
    "T_TIP",
    "T_TIP_CHECK",
    "T_TIP_CHECKED",
]

# ---- 状态锚点（只给状态识别；按钮点击走游戏级家族模板）----
T_LOBBY = "lobby/lobby.png"
T_BEFORE_CREATE = "jj/before_create.png"
T_AFTER_CREATE = "jj/after_create.png"
T_AFTER_ADD = "jj/after_add.png"
T_SELECT_SCREEN = "select/screen.png"
T_FIGHT_HAND = "fight/hand.png"
# 提示框：框体（证明是这个弹窗）+ 复选框两态（未勾 / 已勾，证明勾没勾）。
T_TIP = "jj/tip.png"
T_TIP_CHECK = "jj/tip_check.png"
T_TIP_CHECKED = "jj/tip_checked.png"

# ---- 步骤点击 / 识别（不进状态树）----
T_SELECT_HEALTH = "select/select_first.png"
T_FIGHT_SPACE = "fight/space.png"
T_FIGHT_MENU = "fight/fight_menu.png"
T_FIGHT_SURRENDER = "fight/fight_surrender.png"
T_FIGHT_NEXT = "fight/fight_next.png"
T_CLICK_FIGHT_CONFIRM = "clicks/fight_confirm.png"
