"""千里单骑 —— 模板路径索引。

路径相对本目录（``games/mingjiangsha/scripts/qianlidanqi/templates/``）。
状态锚点与点击目标都写在这里，改路径只改这一处。
"""

from __future__ import annotations

__all__ = [
    "T_CAMPAIGN",
    "T_CAMPAIGN_CARD",
    "T_CLAIM_REWARD",
    "T_CONFIRM",
    "T_CONGRATS",
    "T_EVENT_CHOICE_FEIFEI",
    "T_EVENT_GIFT",
    "T_EVENT_INTRO_BACK",
    "T_FIGHT_AUTO",
    "T_FIGHT_AUTO_OFF",
    "T_FIGHT_CANCEL",
    "T_FIGHT_END",
    "T_FIGHT_MENU",
    "T_FIGHT_NEXT",
    "T_FIGHT_SETTING",
    "T_FLOW",
    "T_FLOW_BAG",
    "T_FLOW_MAP",
    "T_FLOW_SWITCH",
    "T_FLOW_UP",
    "T_GIFT_KIND_TITLE",
    "T_GIFT_TITLE",
    "T_HOME",
    "T_MOZI_CHOICE",
    "T_NEXT",
    "T_NODE_BATTLE",
    "T_NODE_BATTLE_HELP",
    "T_NODE_FEI_FEI",
    "T_NODE_KA_KA",
    "T_NODE_MO_ZI",
    "T_NODE_POCKET",
    "T_NODE_REST",
    "T_NODE_SHI_CHANG",
    "T_NODE_SHOP_BA_QING",
    "T_NODE_SURPRISE",
    "T_NODE_ZHUGE",
    "T_NODE_ZUO_CI",
    "T_PICK_TITLE",
    "T_PLACEHOLDER",
    "T_POCKET_CONFIRM",
    "T_POCKET_TITLE",
    "T_QIANLI_CARD",
    "T_REST_TITLE",
    "T_REWARD_BUFF",
    "T_REWARD_CARD",
    "T_REWARD_HELP",
    "T_REWARD_JOINT",
    "T_REWARD_TOKEN",
    "T_SEARCH",
    "T_SELECT_TITLE",
    "T_SHI_ATTACK",
    "T_SHI_CHOICE",
    "T_SHOP_BUY_TITLE",
    "T_SHOP_CONFIRM",
    "T_SHOP_EXIT",
    "T_SHOP_EXIT_PROMPT",
    "T_SHOP_TITLE",
    "T_SKILL_INFO",
    "T_SKILL_TITLE",
    "T_START",
    "T_START_BATTLE",
    "T_START_DISABLED",
    "T_ZHUGE_CONTINUE",
    "T_ZHUGE_TITLE",
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

#: 点节点后的战斗预览「开始对局」。
T_START_BATTLE = "flow/start_battle.png"
#: 赠礼第一屏标题「请选择接受谁的赠礼？」。
T_GIFT_TITLE = "flow/gift_title.png"
#: 赠礼第二屏标题「请选择一项赠礼？」。
T_GIFT_KIND_TITLE = "flow/gift_kind_title.png"
#: 本局结束「领取奖励」。
T_CLAIM_REWARD = "flow/claim_reward.png"

# ---- 奇遇 ----
#: 奇遇介绍页的「再想一想」按钮（三个奇遇共用）。
T_EVENT_INTRO_BACK = "flow/event_back.png"
#: 奇遇选完后的「请选择一项赠礼」提示。
T_EVENT_GIFT = "flow/event_gift.png"
#: 妃妃选择页顶部标题「偶遇朏朏」（和赠礼类别屏区分）。
T_EVENT_CHOICE_FEIFEI = "flow/event_choice_feifei.png"

# ---- 墨子选择 ----
#: 墨子「请选择一种制造」。
T_MOZI_CHOICE = "flow/mozi_choice.png"

# ---- 属性变更弹窗 ----
#: 属性变更弹窗的「武将技能」。
T_SKILL_TITLE = "flow/skill_title.png"
#: 属性变更弹窗的「武将信息」。
T_SKILL_INFO = "flow/skill_info.png"

# ---- 诸葛亮（占星术士） ----
#: 「占星术士」标题。
T_ZHUGE_TITLE = "flow/zhuge_title.png"
#: 「请点击继续」（第二张牌翻开后出现）。
T_ZHUGE_CONTINUE = "flow/zhuge_continue.png"

# ---- 十常侍 ----
#: 十常侍选择页「请选择一项蛊惑」。
T_SHI_CHOICE = "flow/shi_choice.png"
#: 十常侍左边人物插画（点 5 次进战斗彩蛋）。
T_SHI_ATTACK = "flow/shi_attack.png"

# ---- 锦囊（奇遇） ----
#: 「三顾茅庐」标题（锦囊当前这一种）。
T_POCKET_TITLE = "flow/pocket_title.png"
#: 锦囊确认页的「确认」按钮。
T_POCKET_CONFIRM = "flow/pocket_confirm.png"

# ---- 休息 ----
#: 「安营驻寨」标题。
T_REST_TITLE = "flow/rest_title.png"

# ---- 巴清商店 ----
#: 「巴清小铺子」标题。
T_SHOP_TITLE = "flow/shop_title.png"
#: 购买弹窗标题「购买」。
T_SHOP_BUY_TITLE = "flow/shop_buy_title.png"
#: 商店右上角退出箭头。
T_SHOP_EXIT = "flow/shop_exit.png"
#: 退出提示「是否结束购买？」。
T_SHOP_EXIT_PROMPT = "flow/shop_exit_prompt.png"
#: 退出提示里的「确认」。
T_SHOP_CONFIRM = "flow/shop_confirm.png"
#: 领奖后的「恭喜获得」浮层。
T_CONGRATS = "flow/congrats.png"

#: 通用「确定」（点节点后的确认、局内结束）。
T_CONFIRM = "flow/confirm.png"

#: 地图上的战斗节点（剑）。
T_NODE_BATTLE = "flow/challenge.png"
#: 地图上的战斗节点（卷轴 / 求助）。
T_NODE_BATTLE_HELP = "flow/challenge_help.png"
#: 地图上的「意外」节点。
T_NODE_SURPRISE = "flow/yi_wai.png"
#: 地图上的巴清商店节点。
T_NODE_SHOP_BA_QING = "flow/node_ba_qing.png"
#: 地图上的休息（火堆）节点。
T_NODE_REST = "flow/node_rest.png"
#: 地图上的锦囊节点。
T_NODE_POCKET = "flow/node_pocket.png"
#: 地图上的奇遇节点：妃妃 / 十常侍 / 墨子 / 左慈 / 卡卡。
T_NODE_FEI_FEI = "flow/node_feifei.png"
T_NODE_ZUO_CI = "flow/node_zuoci.png"
T_NODE_KA_KA = "flow/node_kaka.png"
T_NODE_MO_ZI = "flow/node_mozi.png"
T_NODE_SHI_CHANG = "flow/node_shichang.png"
T_NODE_ZHUGE = "flow/node_zhuge.png"

#: 战斗界面「取消」。
T_FIGHT_CANCEL = "flow/cancel.png"
#: 战斗界面「设置」。
T_FIGHT_SETTING = "flow/setting.png"
#: 战斗右上角的菜单（麻花结）。
T_FIGHT_MENU = "flow/menu.png"
#: 战斗结束「点击空白区域到下一步」。
T_FIGHT_END = "flow/challenge_end.png"
#: 结算「下一步」条。
T_FIGHT_NEXT = "flow/next_step.png"
#: 战斗「托管」（未托管，点了才托管）。
T_FIGHT_AUTO = "flow/auto.png"
#: 战斗「取消托管」（已经托管中，不要再点）。
T_FIGHT_AUTO_OFF = "flow/auto_cancel.png"

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
