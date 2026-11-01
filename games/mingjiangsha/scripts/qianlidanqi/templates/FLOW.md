# 千里单骑 · 局内（flow）实现

## 状态

```
qianli/skill_panel --点空白--> qianli/map
qianli/map --战斗节点--> qianli/pre_battle --开始对局--> qianli/fight
qianli/map --巴清商店节点(点两次)--> qianli/shop/ba_qing --买/退出--> qianli/map
qianli/map --休息节点(点两次)--> qianli/rest --点一个选项--> qianli/map
qianli/map --锦囊节点(点两次)--> qianli/pocket/choice --点选项--> 可能还是选/确认/直接战斗
qianli/map --奇遇节点(点一次)--> qianli/event/intro --金色按钮--> qianli/event/choice --选一项--> qianli/map
qianli/event/intro --十常侍--> qianli/event/shi_chang --点左边插画5次--> qianli/fight
qianli/map --诸葛亮节点--> qianli/event/zhuge --中间卡点两次/点任意处--> qianli/map
qianli/map --墨子节点--> qianli/event/intro --选择武将--> qianli/event/mo_zi --三选一--> qianli/map
fight --打完--> qianli/gift --选武将--> qianli/gift_kind --选类别--> qianli/map
fight --无赠礼--> qianli/map
fight/gift_kind --本局结束--> qianli/end --领取奖励--> qianli/end2 --Esc--> qianli/select1（下一轮）
```

| 状态 | 靠什么认 | 步骤 |
|---|---|---|
| `qianli/skill_panel` | 「武将技能」+「武将信息」两个标题 | `close_skill_panel`：点空白 (1300,1127) 回地图 |
| `qianli/shop/ba_qing` | 「巴清小铺子」标题 | `buy_ba_qing`：OCR 三信物 → `rank_token_slots` 按优先表排序 → 逐个点、能买就买（最多 3 个）→ 右上箭头 → 确认结束 |
| `qianli/rest` | 「安营驻寨」标题 | `choose_rest`：随便点一个选项（457,1150）→ 回地图 |
| `qianli/pocket/choice` | 「三顾茅庐」标题 | `choose_pocket`：三个选项随机点一个；可能还在本屏/到确认/直接进战斗 |
| `qianli/pocket/confirm` | 确认按钮 | `confirm_pocket`：点确认 → 地图/战斗/下一个锦囊 |
| `qianli/event/intro` | 「再想一想」按钮 | `enter_event`：点金色「选择事件/选择武将」（`click_pattern_confirm`，只认边框） |
| `qianli/event/choice` | 顶部「偶遇朏朏」 | `choose_event_option`：按妃妃优先级选一行（我来帮你 > 讨价还价） |
| `qianli/event/shi_chang` | 「请选择一项蛊惑」 | `trigger_shi_battle`：点左边人物插画 5 次 → 战斗彩蛋 |
| `qianli/event/zhuge` | 「占星术士」 | `do_zhuge`：中间卡点两次（间隔 2s）→ 请点击继续 → 点任意处回地图 |
| `qianli/event/mo_zi` | 「请选择一种制造」 | `choose_mozi`：三选一，选完回地图 |
| `qianli/map` | 标题「千里单骑 · 无尽」+ 右侧小图标 | `choose_node`：在 `NODE_REGION` 里找战斗节点（剑），点最上面那个 |
| `qianli/pre_battle` | 「开始对局」 | `start_battle`：点开始对局 |
| `qianli/fight` | 取消 / 设置 / 托管 任一 | `run_battle`：点「取消」关换牌 → 点「托管」→ 等「点击空白区域到下一步」（最多 1200s）→ 点它 → 点「下一步」≤5 次 |
| `qianli/gift` | 「请选择接受谁的赠礼？」 | `pick_gift`：OCR 三个标题 → `pick_reward_slot` → 点对应武将 |
| `qianli/gift_kind` | 「请选择一项赠礼？」 | `pick_kind`：扫信物/武将牌/并肩作战/资助/驰援标签 → `pick_reward_kind` → 点 |
| `qianli/end` | 「领取奖励」 | `claim_reward`：点领取奖励 |
| `qianli/end2` | 「恭喜获得」 | `close_congrats`：Esc 关闭，回选将 |

## 关键实现

* **地图节点**：`flow/challenge.png`（30x34 的剑）在 flow1 上三个节点都是 1.0
  （y=547/790/1032），flow2 是 0.95+ —— 所以不写死坐标，用 `find_all_images`
  找全部再点最上面一个。
* **战斗**：和竞技场一样先点「取消」关掉换牌弹窗，然后点「托管」；之后只等
  「点击空白区域到下一步」。不做出牌/取消等战斗操作。
* **赠礼**：第一屏 OCR 三个名字（`REWARD_TITLE_REGIONS`），按
  `store.rewards.pick_reward_slot` 选；OCR 没装时默认点第一个。第二屏用
  `flow/token.png` 等标签找可选项，按 `pick_reward_kind` 选。
* **本局结束**：`end.png` 点「领取奖励」→ `end2.png` 按 Esc → 回到 `select1`
  （武将选择界面），流程闭环，重新选将开下一局。要停按 F9。

## 节点优先级

战斗 > 其他（武将技能 / 意外）> 商店 > 奇遇。

* 商店：铜币够永远巴清；之后顺序待确认（吕不韦 / 锦囊 / 休息）；
* 奇遇：妃妃 > 十常侍 > 墨子 > 诸葛亮 > 左慈 > 卡卡。

## 还没做（缺图）

* 商店界面：吕不韦（巴清、休息、锦囊已做）；
* 奇遇：妃妃、十常侍、诸葛亮、墨子已做；左慈点「选择武将」后的界面还没给；
* 武将技能弹窗真机图（现在用旧 `up.png`）；
* 意外战斗（`qianli/surprise` 已注释占位）。

地图节点图标已用用户给的地图对过：左慈 0.979、妃妃 0.953、巴清 0.987、
吕不韦 0.955、锦囊 0.996。
