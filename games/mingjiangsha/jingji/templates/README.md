# 竞技场脚本 —— 模板

**按父状态分目录**，跟 `pages.py` 里那棵状态树的**分组节点**走：

```
lobby/lobby.png        首页（「竞技」卡上的熊猫头）
jj/before_create.png   竞技场 · 建队前（右下角「创建队伍」）
jj/after_create.png    竞技场 · 建队后（右下角「添加伙伴」）
jj/after_add.png       竞技场 · 加完伙伴（右下角「开始匹配」）
select/idle.png        选将 · 未选（「确定」灰的）
select/picked.png      选将 · 已选（「确定」金的）
fight/hand.png         战斗 · 换牌（「是否需要更换初始手牌？」）
fight/done.png         战斗 · 结算（结算页「确认」）

clicks/select_first.png     ← 只用来**点**，不对应状态
clicks/fight_menu.png
clicks/fight_surrender.png
clicks/fight_confirm.png
clicks/fight_next.png

rawMaterial/                ← 你的原始截图，别动
```

## 为什么这样分（以及为什么不更细）

**按父状态分**：`select/` 里就是那两张「确定」按钮，`fight/` 里就是那两张
战斗快照 —— 找图时进对目录，一眼看到全部候选。

**不给每个叶子单独建目录**：试过 `select/picked/picked.png` 那种，
那层目录名和文件名永远一样，只是把路径写长了一遍，反而更碎。

**文件名不带 `jingji__` / `select__` / `fight__` 前缀**：目录已经表达了。

⚠️ **改模板路径要同步改四处**（同一个真相的四份写法）：

1. `games/mingjiangsha/jingji/pages.py` 的 `T_*` 常量 —— **权威**
2. `logs/tools/build_templates.py` 的 `CROPS` 键
3. `tests/test_jingji_states.py` 的 `TEMPLATE_OF`
4. 本文档

改完跑 `uv run python logs/tools/check_template_paths.py` ——
它两个方向都查：**常量指向的文件在不在** + **有没有图没人引用**。

---

## 裁剪基准

**客户区坐标，原点 = 客户区左上角。模板直接从 `rawMaterial/` 的截图上裁。**

> **不要减 23。** 截图的左上角就是客户区的左上角（标题栏在截图**内部**的
> 上方，不在负半轴）。"减 23"只适用于"拿整窗坐标换算客户区坐标"的场合。

## 裁剪要求

| 项 | 要求 |
|---|---|
| 内容 | 只裁**元素本体**（按钮/文字/图标），**别带周边背景** |
| 边距 | 元素四周留 2~4px |
| 格式 | PNG，路径严格按上表 |

> **为什么强调"别带背景"**：早先给的框普遍偏大，结果
> `jj/after_add`（480×157 一大块）在**别的竞技场画面**上拿到了 **0.984** ——
> 两块背景几乎一样，把按钮上那点差异淹没了。裁小之后差异才占主导。

---

## 状态锚点（8 张）—— 决定"脚本知不知道自己在哪"

| 模板 | 从哪张截图裁 | 裁什么 | 裁剪框（客户区） | 尺寸 |
|---|---|---|---|---|
| `lobby/lobby.png` | `home.png` | 「竞技」卡里的**熊猫头** | 你自己定的（已裁好 ✓ 0.987） | 268×274 |
| `jj/before_create.png` | `jingji1.png` | 「**创建队伍**」按钮本体 | **(2223, 836, 2443, 926)** | 220×90 |
| `jj/after_create.png` | `jingji2.png` | 「**添加伙伴**」按钮本体 | **(2223, 837, 2443, 926)** | 220×89 |
| `jj/after_add.png` | `jingji3.png` | 「**开始匹配**」按钮本体 | **(1930, 1155, 2290, 1255)** | 360×100 |
| `select/idle.png` | `select1.png` | 「确定」按钮（**灰的**） | **(1085, 715, 1480, 810)** | 395×95 |
| `select/picked.png` | `select2.png` | 「确定」按钮（**金的**） | **(1078, 707, 1481, 813)** | 403×106 |
| `fight/hand.png` | `zhandou1.png` | 弹窗里「**是否需要更换初始手牌？**」那行字 | 你自己定（现 440×177 偏大，可只留文字那一行） | ~380×50 |
| `fight/done.png` | `zhandou7.png` | 结算页「**确认**」按钮本体 | **(1147, 1205, 1452, 1304)** | 305×99 |

> 上面那几个精确框是**从截图里量出来的**（找金色像素的包围盒，见
> `logs/tools/measure_buttons.py`），不是估的。
> `select/idle` 是灰按钮、量不到金色，所以借用 `select/picked` 的框 ——
> 两个按钮位置尺寸基本一致。

> **`select/idle` 和 `select/picked` 必须靠底色区分**（灰 vs 金）。
> 裁的时候**把按钮文字一起框进去**，别只裁底色 —— 只裁一块纯色的话，
> 两张模板会互相命中。

---

## 点击目标 —— 决定"点哪里"

`clicks/` 放**不对应任何状态**的点击目标；属于某个状态的放它自己目录下。

| 模板 | 从哪张截图裁 | 裁什么 | 现状 |
|---|---|---|---|
| `clicks/select_first.png` | `select1.png` | **第 1 张武将卡**（张飞那张） | 230×360 |
| `clicks/fight_menu.png` | `zhandou2.png` | 右上角那个**金色圆结** | 70×70 ✓ |
| `clicks/fight_surrender.png` | `zhandou3.png` | 展开菜单里的「**投降**」 | 70×70 ✓ |
| `clicks/fight_confirm.png` | `zhandou4.png` | 投降弹窗里的「**确认**」 | 240×75 |
| `clicks/fight_next.png` | `zhandou6.png` | 结算中间底部「**下一步**」 | 245×65 |
| `fight/space.png` | `zhandou5.png` | 「**点击空白区域到下一步**」那行提示文字 | 392×42 ✓ |

> `fight/space.png` 放在 `fight/` 而不是 `clicks/` —— 它**属于 `fight` 状态**
> （结算页，就是 `fight/done` 那个界面）。`clicks/` 只放不对应状态的。
> 它是**点击目标而不是状态锚点**，所以常量叫 `T_FIGHT_SPACE`。

### 还没接进流程的两张

| 模板 | 是什么 | 打算怎么用 |
|---|---|---|
| `fight/close.png` | 「**取消**」按钮（换牌弹窗里那个） | 它和投降弹窗的「确认」**长得一模一样**，不能单独拿去找。**先用状态确认**（走到这一步时已经是 `fight/hand`），再点 |
| `fight/faQiTouXiang.png` | 「**发起投降**」 | 投降链：`fight_menu`（金色圆结）→ `faQiTouXiang` → `fight_confirm`。现在这条链用的是 `clicks/fight_surrender.png` |

> **`FIGHT_HAND_CANCEL`**（固定坐标）暂时保留：状态已经保证"我在换牌弹窗里"，
> 所以点固定坐标是安全的。`close.png` 是配合状态使用的备选。


---

## 提示弹窗（tip）**不需要模板**

`tip1.png` / `tip2.png` 那两步（勾选「本次登录不再提示」+ 点「确定」）
用**固定坐标**，见 `pages.py` 的 `TIP_CHECKBOX` / `TIP_CONFIRM`。

判"弹窗在不在"用的是**复选框那一小块的平均亮度**（阈值
`TIP_SAMPLE_BRIGHTNESS`）—— 试过模板匹配，但复选框太素，
裁出来的模板在别处的空白块上能拿 0.89 分（高于 0.85）会误判。

---

## 裁完之后怎么验证

```bash
# ① 结构对不对（模板文件在不在、状态有没有节点认领）
uv run pytest tests/test_jingji_states.py

# ② 识别体检：打分数矩阵，看对角线高不高、非对角线低不低
uv run pytest tests/test_jingji_states.py -s -k Diagnostics

# ③ 裁完了要当验收门（认错/误命中直接失败）
JINGJI_CHECK_TEMPLATES=1 uv run pytest tests/test_jingji_states.py -v

# ④ 真机干跑：真抓屏、真识别，但不下发点击
uv run python -m games run mingjiangsha/jingji --dry-run --max-ticks 3
```

④ 那一步看界面上的「识图日志」：每次匹配的**带框图 + 分数**，
一眼能看出哪张模板对不上、差多少。
