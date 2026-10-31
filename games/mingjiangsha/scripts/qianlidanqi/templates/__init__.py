"""千里单骑 —— 模板路径索引。

路径相对本目录（``games/mingjiangsha/scripts/qianlidanqi/templates/``）。
状态锚点与点击目标都写在这里，改路径只改这一处。
"""

from __future__ import annotations

__all__ = [
    "T_CAMPAIGN",
    "T_CAMPAIGN_CARD",
    "T_FLOW",
    "T_HOME",
    "T_PICK_TITLE",
    "T_PLACEHOLDER",
    "T_QIANLI_CARD",
    "T_SEARCH",
    "T_SELECT_TITLE",
    "T_START",
    "T_START_DISABLED",
]

# ---- 状态锚点 ----
#: 首页（还在首页时认它）。
T_HOME = "first/status-select-1-1.png"
#: 战役界面（战旗 + 战役商店那块）。
T_CAMPAIGN = "first/status-select-2.png"
#: 千里单骑标题（select1~select4 都有）。
T_SELECT_TITLE = "select/status-1.png"
#: 「武将选择」面板标题（select2/select3 才有）。
T_PICK_TITLE = "select/status-wujiang-select-title.png"
#: 选将面板里的「选择武将」占位卡（没选将时才有）。
T_PLACEHOLDER = "select/select-wujiang.png"
#: 红色「开始挑战」（已选将、可开局）。
T_START = "select/start.png"
#: 灰色「开始挑战」（没选将）。
T_START_DISABLED = "select/status-start-disable.png"
#: 局内标题「千里单骑 · 无尽」（flow 界面）。
T_FLOW = "flow/status-1.png"

# ---- 点击目标 ----
#: 首页的「战役」卡。
T_CAMPAIGN_CARD = "first/select-1-1.png"
#: 战役页的「千里单骑」卡。
T_QIANLI_CARD = "first/select-2-1.png"
#: 选将面板的「搜索」按钮。
T_SEARCH = "select/search-wujiang.png"
