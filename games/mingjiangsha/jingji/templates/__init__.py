"""竞技场 —— 模板路径索引。

路径相对本目录（``games/mingjiangsha/jingji/templates/``）。
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
    "T_FIGHT_DONE",
    "T_FIGHT_HAND",
    "T_FIGHT_MENU",
    "T_FIGHT_NEXT",
    "T_FIGHT_SPACE",
    "T_FIGHT_SURRENDER",
    "T_LOBBY",
    "T_SELECT_HEALTH",
    "T_SELECT_IDLE",
    "T_SELECT_PICKED",
    "T_TIP",
]

# ---- 状态锚点（也常复用为点击目标）----
T_LOBBY = "lobby/lobby.png"
T_BEFORE_CREATE = "jj/before_create.png"
T_AFTER_CREATE = "jj/after_create.png"
T_AFTER_ADD = "jj/after_add.png"
T_SELECT_IDLE = "select/idle.png"
T_SELECT_PICKED = "select/picked.png"
T_FIGHT_HAND = "fight/hand.png"
T_FIGHT_DONE = "fight/done.png"

# ---- 步骤点击 / 识别（不进状态树）----
T_TIP = "jj/tip.png"
T_SELECT_HEALTH = "select/select_first.png"
T_FIGHT_SPACE = "fight/space.png"
T_FIGHT_MENU = "fight/fight_menu.png"
T_FIGHT_SURRENDER = "fight/fight_surrender.png"
T_FIGHT_NEXT = "fight/fight_next.png"
T_CLICK_FIGHT_CONFIRM = "clicks/fight_confirm.png"
