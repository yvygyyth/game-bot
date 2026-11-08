"""千里单骑 —— 流程图（"做什么、何时换"）。

```
root --(进战役)--> campaign --(进千里单骑)--> open_pick --(打开选将)--> pick_general
                                                                          |
                                                                  (选好了，面板里已选)
                                                                          v
                                                                     leave_pick
                                                                          |
                                                                  (Esc 回主界面)
                                                                          v
                                                                     start_run --(开始挑战)--> map
continue_run --(继续挑战)--> map

map --(点战斗节点)--> pre_battle --(开始对局)--> fight
fight --(打完)--> gift --(选武将)--> gift_kind --(选类别)--> map
fight --(无赠礼)--> map
fight --(本局结束)--> end --(领取奖励)--> end2 --(Esc)--> open_pick（下一轮）
```

局内是**闭环**：打完/选完回 `map` 继续点节点；本局结束领完奖励按 Esc 回选将，
重新选将开下一局。要停就按 F9。
"""

from __future__ import annotations

from gamebot.flow import EngineOptions, Node, Transition
from gamebot.scenario_spec import ScenarioSpec
from games import on_page

from .bindings import BINDINGS
from .pages import FEATURE_TREE
from .steps import (
    buy_ba_qing,
    choose_event_option,
    choose_mozi,
    choose_node,
    choose_pocket,
    choose_rest,
    claim_reward,
    close_congrats,
    close_skill_panel,
    confirm_pocket,
    continue_run,
    do_zhuge,
    enter_campaign,
    enter_event,
    enter_qianli,
    fight_cancel_hand_swap,
    fight_choose_auto,
    fight_click_end,
    fight_click_next,
    fight_close_menu,
    fight_open_menu_or_wait,
    leave_pick,
    open_pick,
    pick_general,
    pick_gift,
    pick_kind,
    start_battle,
    start_run,
    trigger_shi_battle,
)

__all__ = ["SCENARIO"]


SCENARIO = ScenarioSpec(
    name="qianlidanqi",
    initial="root",
    tree=FEATURE_TREE,
    bindings=BINDINGS,
    nodes=(
        Node(
            "root",
            steps=[enter_campaign],
            description="首页：点「战役」卡",
            transitions=[
                Transition("campaign", on_page("campaign"), 10, "进入战役界面"),
            ],
        ),
        Node(
            "campaign",
            steps=[enter_qianli],
            description="战役界面：点「千里单骑」卡",
            transitions=[
                Transition("open_pick", on_page("qianli/select1"), 10, "进入千里单骑"),
                # 已经有进行中的局时，点「千里单骑」会直接到「继续挑战」界面。
                Transition("continue_run", on_page("qianli/select5"), 5, "已有进行中的局"),
            ],
        ),
        Node(
            "open_pick",
            steps=[open_pick],
            description="主界面：点「选择武将」占位卡",
            transitions=[
                Transition("pick_general", on_page("qianli/select2"), 10, "打开选将面板"),
            ],
        ),
        Node(
            "pick_general",
            steps=[pick_general],
            description="选将面板：搜索入参武将 → 点第一个结果",
            transitions=[
                Transition("leave_pick", on_page("qianli/select3"), 10, "武将已选中"),
            ],
        ),
        Node(
            "leave_pick",
            steps=[leave_pick],
            description="已选将：按 Esc 退回主界面",
            transitions=[
                Transition("start_run", on_page("qianli/select4"), 10, "回到主界面"),
            ],
        ),
        Node(
            "start_run",
            steps=[start_run],
            description="主界面：点红色「开始挑战」",
            transitions=[
                Transition("map", on_page("qianli/map"), 10, "进入局内地图"),
            ],
        ),
        Node(
            "continue_run",
            steps=[continue_run],
            description="已有进行中的局：点「继续挑战」，直接进局内",
            transitions=[
                Transition("map", on_page("qianli/map"), 10, "继续挑战进地图"),
            ],
        ),
        # ---------------- 局内 ----------------
        Node(
            "skill_panel",
            steps=[close_skill_panel],
            description="武将技能/属性变动弹窗：点一下关闭，回地图",
            transitions=[
                Transition("map", on_page("qianli/map"), 10, "关闭后回地图"),
            ],
        ),
        # 意外战斗先占位，等用户给图后再启用（见 FLOW.md）
        # Node(
        #     "surprise",
        #     steps=[],
        #     description="意外战斗（待补图）",
        # ),
        Node(
            "map",
            steps=[choose_node],
            description="地图：找一个战斗节点点它",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("shop_ba_qing", on_page("qianli/shop/ba_qing"), 20, "进巴清商店"),
                Transition("pocket_choice", on_page("qianli/pocket/choice"), 16, "进锦囊"),
                Transition("rest", on_page("qianli/rest"), 15, "进休息"),
                Transition("zhuge", on_page("qianli/event/zhuge"), 13, "进诸葛亮"),
                Transition("event_intro", on_page("qianli/event/intro"), 12, "进奇遇"),
                Transition("pre_battle", on_page("qianli/pre_battle"), 10, "点开战斗预览"),
            ],
        ),
        Node(
            "pre_battle",
            steps=[start_battle],
            description="战斗预览：点「开始对局」",
            transitions=[
                Transition(
                    "fight_hand_swap",
                    on_page("qianli/fight/hand_swap"),
                    12,
                    "进入战斗（换牌弹窗）",
                ),
                Transition("fight_main", on_page("qianli/fight/main"), 10, "进入战斗"),
            ],
        ),
        Node(
            "fight_hand_swap",
            steps=[fight_cancel_hand_swap],
            description="战斗：点掉换牌弹窗",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("fight_main", on_page("qianli/fight/main"), 20, "取消后回战斗主界面"),
                Transition("fight_menu_off", on_page("qianli/fight/menu_off"), 15, "菜单已开"),
                Transition("fight_menu_on", on_page("qianli/fight/menu_on"), 15, "菜单已开"),
                Transition("fight_ended", on_page("qianli/fight/ended"), 10, "战斗结束"),
            ],
        ),
        Node(
            "fight_main",
            steps=[fight_open_menu_or_wait],
            description="战斗主界面：开菜单，或托管后等结束",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("fight_hand_swap", on_page("qianli/fight/hand_swap"), 25, "换牌弹窗"),
                Transition(
                    "fight_menu_off",
                    on_page("qianli/fight/menu_off"),
                    20,
                    "菜单展开（托管未开）",
                ),
                Transition(
                    "fight_menu_on",
                    on_page("qianli/fight/menu_on"),
                    20,
                    "菜单展开（托管已开）",
                ),
                Transition("fight_ended", on_page("qianli/fight/ended"), 15, "战斗结束提示"),
                Transition("fight_result", on_page("qianli/fight/result"), 12, "战斗下一步"),
                Transition("gift", on_page("qianli/gift"), 10, "弹赠礼（选武将）"),
                Transition("gift_kind", on_page("qianli/gift_kind"), 9, "直接到赠礼类别"),
                Transition("end", on_page("qianli/end"), 8, "本局结束"),
                Transition("map", on_page("qianli/map"), 5, "回地图继续"),
            ],
        ),
        Node(
            "fight_menu_off",
            steps=[fight_choose_auto],
            description="战斗菜单：点托管",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition(
                    "fight_menu_on",
                    on_page("qianli/fight/menu_on"),
                    20,
                    "菜单还开着（已托管）",
                ),
                Transition("fight_main", on_page("qianli/fight/main"), 15, "菜单关闭"),
                Transition("fight_ended", on_page("qianli/fight/ended"), 10, "战斗结束"),
            ],
        ),
        Node(
            "fight_menu_on",
            steps=[fight_close_menu],
            description="战斗菜单：确认托管已开并关闭菜单",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("fight_main", on_page("qianli/fight/main"), 20, "菜单关闭"),
                Transition("fight_ended", on_page("qianli/fight/ended"), 10, "战斗结束"),
            ],
        ),
        Node(
            "fight_ended",
            steps=[fight_click_end],
            description="战斗结束：点空白区域",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("fight_result", on_page("qianli/fight/result"), 20, "下一步条"),
                Transition("gift", on_page("qianli/gift"), 15, "弹赠礼（选武将）"),
                Transition("gift_kind", on_page("qianli/gift_kind"), 14, "直接到赠礼类别"),
                Transition("end", on_page("qianli/end"), 10, "本局结束"),
                Transition("map", on_page("qianli/map"), 5, "回地图继续"),
            ],
        ),
        Node(
            "fight_result",
            steps=[fight_click_next],
            description="战斗下一步：点下一步，最多 5 次",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("gift", on_page("qianli/gift"), 20, "弹赠礼（选武将）"),
                Transition("gift_kind", on_page("qianli/gift_kind"), 15, "直接到赠礼类别"),
                Transition("end", on_page("qianli/end"), 10, "本局结束"),
                Transition("map", on_page("qianli/map"), 10, "回地图继续"),
            ],
        ),
        Node(
            "gift",
            steps=[pick_gift],
            description="赠礼第一屏：按优先表选武将",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("gift_kind", on_page("qianli/gift_kind"), 10, "进入类别选择"),
            ],
        ),
        Node(
            "gift_kind",
            steps=[pick_kind],
            description="赠礼第二屏：按优先表选类别",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("map", on_page("qianli/map"), 10, "回地图继续"),
                Transition("end", on_page("qianli/end"), 5, "本局结束"),
            ],
        ),
        Node(
            "shop_ba_qing",
            steps=[buy_ba_qing],
            description="巴清商店：买信物 → 退出 → 确认结束购买",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("map", on_page("qianli/map"), 10, "回地图"),
            ],
        ),
        Node(
            "event_intro",
            steps=[enter_event],
            description="奇遇介绍：点金色「选择事件/选择武将」",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("shi_chang", on_page("qianli/event/shi_chang"), 20, "十常侍选择页"),
                Transition("mo_zi", on_page("qianli/event/mo_zi"), 20, "墨子选择页"),
                Transition("event_choice", on_page("qianli/event/choice"), 20, "进选择页"),
                Transition("map", on_page("qianli/map"), 5, "直接回地图"),
            ],
        ),
        Node(
            "event_choice",
            steps=[choose_event_option],
            description="奇遇选择：按妃妃优先级选一项",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("map", on_page("qianli/map"), 10, "回地图"),
            ],
        ),
        Node(
            "mo_zi",
            steps=[choose_mozi],
            description="墨子三选一：点一行制造，回地图",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("map", on_page("qianli/map"), 10, "回地图"),
            ],
        ),
        Node(
            "zhuge",
            steps=[do_zhuge],
            description="诸葛亮占星：中间卡点两次 → 点继续 → 回地图",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("map", on_page("qianli/map"), 10, "回地图"),
            ],
        ),
        Node(
            "shi_chang",
            steps=[trigger_shi_battle],
            description="十常侍：点左边插画 5 次触发战斗",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition(
                    "fight_hand_swap",
                    on_page("qianli/fight/hand_swap"),
                    22,
                    "进战斗（换牌弹窗）",
                ),
                Transition("fight_main", on_page("qianli/fight/main"), 20, "进战斗"),
                Transition("map", on_page("qianli/map"), 10, "回地图"),
                Transition("end", on_page("qianli/end"), 5, "本局结束"),
            ],
        ),
        Node(
            "pocket_choice",
            steps=[choose_pocket],
            description="锦囊三选一：随便点一个；可能还在这屏/到确认/直接进战斗",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("pocket_confirm", on_page("qianli/pocket/confirm"), 20, "到确认页"),
                Transition(
                    "fight_hand_swap",
                    on_page("qianli/fight/hand_swap"),
                    17,
                    "直接进战斗（换牌弹窗）",
                ),
                Transition("fight_main", on_page("qianli/fight/main"), 15, "直接进战斗"),
                Transition("map", on_page("qianli/map"), 5, "回地图"),
            ],
        ),
        Node(
            "pocket_confirm",
            steps=[confirm_pocket],
            description="锦囊确认页：点确认",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("pocket_choice", on_page("qianli/pocket/choice"), 20, "又弹一个锦囊"),
                Transition(
                    "fight_hand_swap",
                    on_page("qianli/fight/hand_swap"),
                    17,
                    "进战斗（换牌弹窗）",
                ),
                Transition("fight_main", on_page("qianli/fight/main"), 15, "进战斗"),
                Transition("map", on_page("qianli/map"), 10, "回地图"),
                Transition("end", on_page("qianli/end"), 5, "本局结束"),
            ],
        ),
        Node(
            "rest",
            steps=[choose_rest],
            description="休息：随便点一个选项 → 回地图",
            transitions=[
                Transition("skill_panel", on_page("qianli/skill_panel"), 30, "武将技能弹窗"),
                Transition("map", on_page("qianli/map"), 10, "回地图"),
            ],
        ),
        Node(
            "end",
            steps=[claim_reward],
            description="本局结束：点「领取奖励」",
            transitions=[
                Transition("end2", on_page("qianli/end2"), 10, "领奖浮层"),
            ],
        ),
        Node(
            "end2",
            steps=[close_congrats],
            description="「恭喜获得」浮层：Esc 回选将，开下一局",
            transitions=[
                Transition("open_pick", on_page("qianli/select1"), 10, "回选将界面"),
            ],
        ),
    ),
    options=EngineOptions(
        tick_interval=0.2,
        # 点按钮到界面更新有过渡；连续命中再动手
        require_confirmed=True,
        # 一局可能打十几分钟；2 小时兜底（脚本是循环的，按 F9 停）
        max_runtime=7200.0,
    ),
)
