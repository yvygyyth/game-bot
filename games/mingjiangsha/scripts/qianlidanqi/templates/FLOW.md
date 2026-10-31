# 千里单骑 · 局内（flow）实现

## 状态

```
qianli/map --战斗节点--> qianli/pre_battle --开始对局--> qianli/fight
fight --打完--> qianli/gift --选武将--> qianli/gift_kind --选类别--> qianli/map
fight --无赠礼--> qianli/map
fight/gift_kind --本局结束--> qianli/end --领取奖励--> qianli/end2 --Esc--> qianli/select1（下一轮）
```

| 状态 | 靠什么认 | 步骤 |
|---|---|---|
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

## 还没做

* 商店节点（巴清商店 / 锦囊 / 休息）—— 地图上目前只找战斗节点；
* 事件节点（妃妃 / 墨子 / 十常侍）；
* 中途失败/退出的兜底（现在靠引擎的重定位 + 用户 F9）。

这些旧图和旧逻辑都在旧工程 `flows/pick_shop.py` / `pick_event.py` 等里，
需要时再按同样方式搬。
