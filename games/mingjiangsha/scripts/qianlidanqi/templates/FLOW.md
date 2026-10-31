# 千里单骑 · 局内（flow）设计稿

> 这份是**设计稿**，不是最终实现。局内地地图之外的三张关键界面（点节点后的确认、
> 战斗、结算/赠礼）还没有真机整屏截图，状态锚点只能拿旧工程的小图硬猜；
> 先不写进 `pages.py`，免得"认错还乱点"。等补 3 张图（或跑一局抓帧）再落地。

## 已有证据

* `rawMaterial/flow1.png`：局内地 **地图**（当前挑战：1 层）。
  - 左侧：吕布卡、背包 0/8、仓库 0/99；
  - 中间：三个敌人头像（节点）；
  - 上面图例：战斗 / 商店 / 事件 / 休息 / 武将 / 伙伴；
  - 右下：结束挑战。
* 旧工程 `flows/*.py` + `data/ming_jiang_sha/qian_li_dan_qi/**` 的小图。
  已直接复制到 `templates/flow/`（见下表），并都在 `templates/__init__.py` 声明了。

## 地图怎么认

| 模板 | 含义 | 在 flow1 上的实测 |
|---|---|---|
| `flow/status-1.png` | 标题「千里单骑 · 无尽」 | 1.000 @ (18,28) |
| `flow/battle_interface.png` | 地图右侧小图标 | 1.000 @ (2471,568) |
| `flow/bag.png` | 左侧背包 | 1.000 @ (183,1136) |
| `flow/switch.png` | 切换按钮 | 0.971 @ (621,1024) |

状态锚点用 **标题 + 右侧小图标** 就够；`bag/switch` 是辅助。

## 节点（三选一）

旧代码用同一块区域找节点图标：

```python
CHOICE_REGION = (800, 350, 1630, 780)   # (left, top, width, height)
```

| 类型 | 旧图标（已复制） | 旧流程 |
|---|---|---|
| 战斗 | `flow/challenge.png`（剑）/ `challenge_help.png`（卷轴）/ `yi_wai.png`（意外） | `pick_battle.choose` → 确认 → `fight` |
| 商店 | `ba_qing_store.png` / `pocket_event.png` / `rest.png` / `lv_bu_wei_store.png` | `pick_shop.choose` |
| 事件 | `fei_fei.png` / `shi_chang_shi.png` / `mo_zi.png` | `pick_event.choose` |

> 商店/事件的小图还没复制（等这一步落地时再 copy，避免一次加太多没用到的图）。

## 建议的状态机

```
qianli/map  --(战斗节点)-->  qianli/fight  --(打完+结算)-->  qianli/reward
    |                              |                              |
    |                              +--(本局结束)--> qianli/run_end  |
    |                                                             |
    +<--------------------- 选完赠礼 / 无赠礼 ---------------------+
    |
    +--(商店节点)--> qianli/shop  --买完--> qianli/map
    +--(事件节点)--> qianli/event --选完--> qianli/map
    +--(休息节点)--> qianli/rest  --点完--> qianli/map
```

| 状态 | 锚点 | 步骤 | 出边 |
|---|---|---|---|
| `qianli/map` | `T_FLOW` + `T_FLOW_MAP` | `choose_node`：先关「武将技能」面板（`T_FLOW_UP`，点 1300,1150）；按 战斗→商店→事件 找图标并点；有 `T_CONFIRM` 就点它 | 按实测状态去 `fight` / `shop` / `event` / `rest` |
| `qianli/fight` | `T_FIGHT_CANCEL` 或 `T_FIGHT_SETTING` | `run_fight`：有 `T_FIGHT_AUTO` 就点 → 等 `T_FIGHT_END`（最多 1200s）→ 点它 → 点 `T_FIGHT_NEXT` 直到消失（≤5）→ 看 `T_CONFIRM` 判断本局结束 | `reward` 或 `run_end` |
| `qianli/reward` | `T_REWARD_TOKEN/JOINT/CARD/HELP/BUFF` 任一 | `pick_reward`：OCR 三个标题（`REWARD_TITLE_REGIONS`）→ `pick_reward_slot` → 点槽 → 扫 `T_REWARD_*` → `pick_reward_kind` → 点 → 记 `BattleState` | 回 `map` |
| `qianli/run_end` | `T_CONFIRM` | `finish_run`：点确认 → Esc×2 | 回 `select5`（继续挑战）或 `select4` |
| `qianli/shop` | `ba_qing_store` 等 | 见旧 `pick_shop` / `ba_qing_store` | 回 `map` |
| `qianli/event` | `fei_fei` / `shi_chang_shi` / `mo_zi` | 见旧 `pick_event` + 各事件 | 回 `map` |
| `qianli/rest` | `rest` | 点一个休息位（旧坐标三选一） | 回 `map` |

## 旧代码 → 新代码的对应

| 旧 | 新 |
|---|---|
| `battle_hub.relocate`（up/battle/shop/event 四类） | `pages.py` 的 `map` 状态 + `choose_node` 里按图标分流 |
| `pick_battle.choose` + `pre_confirm` | `choose_node` 点战斗图标 → 点 `T_CONFIRM` |
| `fight.wait_end` / `next_step` / `check_run_end` | `run_fight` |
| `fight.after_settle` / `choose_reward_title` / `choose_reward_kind` | `pick_reward`（store 的 `pick_reward_slot/kind` 已经搬好） |
| `run_ended.confirm` / `close` | `finish_run` |
| `utils/bag.py` / `utils/rewards.py` / `utils/priority.py` / `state.py` | `store/`（**已搬**） |

## 还缺的截图（有其中任意一张就能先做一段）

1. **点节点后的确认框**（以及地图上三个节点的实际样子）；
2. **战斗界面**（取消/设置/自动，或者至少"点击空白区域到下一步"）；
3. **结算/赠礼**（三个武将标题 + 信物/资助/驰援等图标）；
4. **本局结束**（确认 + 回到哪个界面）。

> 最快的方式：你手动跑一局，把上面 4 张整屏截图丢到 `rawMaterial/flow_*.png`，
> 我按 select1-5 的做法先钉状态测试、再写步骤。旧小图已经复制好，能直接用。
