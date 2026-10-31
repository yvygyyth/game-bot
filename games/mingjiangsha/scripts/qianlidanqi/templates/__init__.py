"""千里单骑 —— 模板路径索引。

路径相对本目录（``games/mingjiangsha/scripts/qianlidanqi/templates/``）。
状态锚点与点击目标都写在这里，改路径只改这一处。
"""

from __future__ import annotations

__all__ = [
    "T_CAMPAIGN",
    "T_CAMPAIGN_CARD",
    "T_CONFIRM",
    "T_FIGHT_AUTO",
    "T_FIGHT_CANCEL",
    "T_FIGHT_END",
    "T_FIGHT_NEXT",
    "T_FIGHT_SETTING",
    "T_FLOW",
    "T_FLOW_BAG",
    "T_FLOW_MAP",
    "T_FLOW_SWITCH",
    "T_FLOW_UP",
    "T_HOME",
    "T_NEXT",
    "T_NODE_BATTLE",
    "T_NODE_BATTLE_HELP",
    "T_NODE_SURPRISE",
    "T_PICK_TITLE",
    "T_PLACEHOLDER",
    "T_QIANLI_CARD",
    "T_REWARD_BUFF",
    "T_REWARD_CARD",
    "T_REWARD_HELP",
    "T_REWARD_JOINT",
    "T_REWARD_TOKEN",
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
#: 红色「继续挑战」（已有进行中的挑战，点了直接进局内）。
T_NEXT = "select/nextt.png"
#: 灰色「开始挑战」（没选将）。
T_START_DISABLED = "select/status-start-disable.png"
#: 局内标题「千里单骑 · 无尽」（flow 界面）。
T_FLOW = "flow/status-1.png"

# ---- 局内（flow）----
#: 局内地图右侧的「背包 / 图鉴」小图标（和标题一起认地图）。
T_FLOW_MAP = "flow/battle_interface.png"
#: 地图左侧背包图标。
T_FLOW_BAG = "flow/bag.png"
#: 地图上的「切换」按钮。
T_FLOW_SWITCH = "flow/switch.png"
#: 地图上弹出的「武将技能」面板（先点空白关掉）。
T_FLOW_UP = "flow/up.png"

#: 通用「确定」（点节点后的确认、局内结束）。
T_CONFIRM = "flow/confirm.png"

#: 地图上的战斗节点（剑）。
T_NODE_BATTLE = "flow/challenge.png"
#: 地图上的战斗节点（卷轴 / 求助）。
T_NODE_BATTLE_HELP = "flow/challenge_help.png"
#: 地图上的「意外」节点。
T_NODE_SURPRISE = "flow/yi_wai.png"

#: 战斗界面「取消」。
T_FIGHT_CANCEL = "flow/cancel.png"
#: 战斗界面「设置」。
T_FIGHT_SETTING = "flow/setting.png"
#: 战斗结束「点击空白区域到下一步」。
T_FIGHT_END = "flow/challenge_end.png"
#: 结算「下一步」条。
T_FIGHT_NEXT = "flow/next_step.png"
#: 战斗「自动」。
T_FIGHT_AUTO = "flow/auto.png"

#: 赠礼类别：信物。
T_REWARD_TOKEN = "flow/token.png"
#: 赠礼类别：并肩作战。
T_REWARD_JOINT = "flow/joint.png"
#: 赠礼类别：武将牌。
T_REWARD_CARD = "flow/card.png"
#: 赠礼类别：资助。
T_REWARD_HELP = "flow/help.png"
#: 赠礼类别：驰援。
T_REWARD_BUFF = "flow/buff.png"

# ---- 点击目标 ----
#: 首页的「战役」卡。
T_CAMPAIGN_CARD = "first/select-1-1.png"
#: 战役页的「千里单骑」卡。
T_QIANLI_CARD = "first/select-2-1.png"
#: 选将面板的「搜索」按钮。
T_SEARCH = "select/search-wujiang.png"
