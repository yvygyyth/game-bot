# 竞技场脚本 —— 模板

**按父状态分目录**，跟 `pages.py` 里那棵状态树的**分组节点**走：

```
lobby/lobby.png            首页（「竞技」卡上的熊猫头）
jj/before_create.png       竞技场 · 建队前（右下角「创建队伍」）
jj/after_create.png        竞技场 · 建队后（右下角「添加伙伴」）
jj/after_add.png           竞技场 · 加完伙伴（右下角「开始匹配」）
jj/tip.png                 提示框本体（1065×360，含标题栏那条）
jj/tip_check.png           提示框 · 复选框（未勾，60×60）
jj/tip_checked.png         提示框 · 复选框（已勾，60×60）
select/screen.png          选将界面锚点（「换座」按钮；灰/金两态都长这样）
select/select_first.png    选将 · 血条勾玉那一列（每张卡都有）
fight/hand.png             战斗 · 换牌（「是否需要更换初始手牌？」）
fight/space.png            战斗 · 完胜「点击空白区域到下一步」（金色笔画 mask）
fight/space.png            「点击空白区域到下一步」那行提示文字
fight/fight_menu.png       右上角金色圆结（展开投降菜单）
fight/fight_surrender.png  菜单里的「投降」
fight/fight_next.png       结算中间底部「下一步」

clicks/fight_confirm.png    ← 只用来**点**、不对应状态

rawMaterial/                ← 你的原始截图，别动
```

> 完整清单（含每张的裁剪框）见下面两张表 —— 这里只画目录结构，
> 免得两处各列一份、迟早对不上。

**目录 = 分组节点**：`clicks/` 只放"不对应任何状态"的点击目标，
属于某个状态的一律放它自己目录下（所以 `fight/fight_menu.png`
不叫 `clicks/…`）。

## 为什么这样分（以及为什么不更细）

**按父状态分**：`select/` 里就是那两张「确定」按钮，`fight/` 里就是那两张
战斗快照 —— 找图时进对目录，一眼看到全部候选。

**不给每个叶子单独建目录**：试过 `select/picked/picked.png` 那种，
那层目录名和文件名永远一样，只是把路径写长了一遍，反而更碎。

**文件名不带 `jingji__` / `select__` / `fight__` 前缀**：目录已经表达了。

⚠️ **改模板路径要同步改四处**（同一个真相的四份写法）：

1. `games/mingjiangsha/scripts/jingji/templates/__init__.py` 的 `T_*` 常量 —— **权威**
2. `logs/tools/build_templates.py` 的 `CROPS` 键
3. `tests/test_jingji_states.py` 的 `TEMPLATE_OF`
4. 本文档

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

## 状态锚点（9 张）—— 决定"脚本知不知道自己在哪"

| 模板 | 从哪张截图裁 | 裁什么 | 裁剪框（客户区） | 尺寸 |
|---|---|---|---|---|
| `lobby/lobby.png` | `home.png` | 「竞技」卡里的**熊猫头** | 你自己定的（已裁好 ✓ 0.987） | 268×274 |
| `jj/before_create.png` | `jingji1.png` | 「**创建队伍**」按钮本体 | **(2223, 836, 2443, 926)** | 220×90 |
| `jj/after_create.png` | `jingji2.png` | 「**添加伙伴**」按钮本体 | **(2223, 837, 2443, 926)** | 220×89 |
| `jj/after_add.png` | `jingji3.png` | 「**开始匹配**」按钮本体 | **(1930, 1155, 2290, 1255)** | 360×100 |
| `jj/tip.png` | `tip1.png` | 提示框本体（1065×360） | 已裁好 | 1065×360 |
| `jj/tip_check.png` | `tip1.png` | 复选框（未勾） | **(1104, 816, 1164, 876)** | 60×60 |
| `jj/tip_checked.png` | `tip2.png` | 复选框（已勾） | 同上 | 60×60 |
| `select/screen.png` | 真机选将截图 | 「**换座**」按钮（灰/金两态都在） | **(320, 730, 470, 810)** | 150×80 |
| `fight/hand.png` | `zhandou1.png` | 弹窗里「**是否需要更换初始手牌？**」那行字 | 你自己定（现 440×177 偏大，可只留文字那一行） | ~380×50 |
| `fight/space.png` | `zhandou5.png` | 「**点击空白区域到下一步**」（金色笔画 + 半透明底，用 `mask="gold"`） | 已裁好 | 394×37 |

> 上面那几个精确框是**从截图里量出来的**（找金色像素的包围盒，见
> `logs/tools/measure_buttons.py`），不是估的。

> **选将不再用「确定」按钮当锚点。** 真机上那个按钮的尺寸和旧截图不一样
> （实拍 435×89 vs 旧模板 401×105），灰/金两态的模板都匹配不上；改用
> 两态都一样的「换座」按钮（实测 1.000），**点卡 + 确定合成一步**
> （见 `steps/pick_general.py`：确定在界面里居中固定）。
> 提示框两态仍然靠复选框区分 —— 但复选框只在 `TIP_CHECKBOX_ROI` 小块里找。

---

## 点击目标 —— 决定"点哪里"

`clicks/` 放**不对应任何状态**的点击目标；属于某个状态的放它自己目录下。

| 模板 | 从哪张截图裁 | 裁什么 | 现状 |
|---|---|---|---|
| `select/select_first.png` | `select1.png` | **血条勾玉那一列**（每张卡都有） | 25×84 ✓ |
| `fight/fight_menu.png` | `zhandou2.png` | 右上角那个**金色圆结** | 70×70 ✓ |
| `fight/fight_surrender.png` | `zhandou3.png` | 展开菜单里的「**投降**」 | 70×70 ✓ |
| `clicks/fight_confirm.png` | `zhandou4.png` | 投降弹窗里的「**确认**」 | 240×75 |
| `fight/fight_next.png` | `zhandou6.png` | 结算中间底部「**下一步**」 | 245×65 |
| `fight/space.png` | `zhandou5.png` | 「**点击空白区域到下一步**」那行提示文字 | 392×42 ✓ |

### 选将那张是**血条**，不是"第一张卡"

`select/select_first.png` 是**每张武将卡都有**的血条勾玉列，所以用法是
``find_all_images``（一次命中多张卡各一处），挑一个点 —— 点哪张卡都行。

**为什么拿血条当特征**：卡面上每局都变的是**立绘和名字**，拿它们当模板
下一局就失效；而每个武将**必定有血条**，长相和位置都不变。

实测（`logs/tools/check_select_health.py`）：`select1.png` 在阈值 0.85 下
命中 **22** 个点（同卡竖直方向能错开落位），按 x 聚成 **7 列** ——
列中心 `410 / 678 / 945 / 1213 / 1537 / 1805 / 2072`，
相邻间距 267~268，中间有一处 324（**真实的界面空隙**，4+4 两排之间）。
`pick_general` 取**最左那一列**的中点 `(410, 525)`：
挑最左而不是"第一个命中的"，因为 `find_all_images` 按分数降序返回，
分数会浮动 —— 按 x 挑才是确定的。

### 只有"被状态树 / 步骤引用"的图才留

没被 `pages.py` 引用的图（原来的 `fight/close.png`、`fight/faQiTouXiang.png`、
`jj/check.png`、`jj/check_yes.png`）已经删了 —— 按设计，**没进状态树就不是状态识别图**，
点击也早就不用它们了。以后裁了图但没接进流程，先别放进这个目录。

---

---

## 提示框（tip）—— 一个状态组，两个叶子

「开始匹配」之后**可能**弹的框。现在它是**状态**，不是步骤里的 if：

| 状态 | 认什么（两个 query 同时成立） | 节点 / 步骤 |
|---|---|---|
| `tip/unchecked` | `jj/tip.png`（框体）+ `jj/tip_check.png`（复选框未勾，60×60） | `tip_check` / `check_tip` |
| `tip/checked` | `jj/tip.png` + `jj/tip_checked.png`（复选框已勾） | `tip_confirm` / `confirm_tip` |

* 框体证明"是这个弹窗"，复选框证明"勾没勾" —— **AND**，两者都要中；
* 复选框必须**单独框住**（`pages.py` 的 `TIP_CHECKBOX_ROI`）：整框范围里还有
  别处像灰方块，未勾模板在"已勾"图上别处能到 **0.96**；收进 checkbox 那一小块
  后，两态互匹只有 **0.70**，自匹 1.0，阈值 0.9 分得干净；
* 提示框是**模态**的：它盖住竞技场时 `jj/after_add` 用 exclude 否决它，
  否则底下那张「开始匹配」还会被认出来，流程会以为没弹框；
* 点「确定」走 `click_shadow_confirm`（和别的金色确认按钮同家族）；
* **没弹框是正常分支**：`match` 直接走 `pick_general`，不重定位。

> 早先的教训仍然成立：**"模板太素会误命中"是针对那张裁法的**。
> 复选框单独当判据会误判（灰白方格在别处能到 0.89），所以它只做
> "勾没勾"的第二判据，框体负责"弹没弹"。

---

## 裁完之后怎么验证

```bash
# ① 结构对不对（模板文件在不在、状态有没有节点认领）
uv run pytest tests/test_jingji_states.py

# ② 识别体检：打分数矩阵，看对角线高不高、非对角线低不低
uv run pytest tests/test_jingji_states.py -s -k Diagnostics

# ③ 裁完了要当验收门（认错/误命中直接失败）
JINGJI_CHECK_TEMPLATES=1 uv run pytest tests/test_jingji_states.py -v

# ④ 真机干跑：开界面、选脚本、勾「空跑」再点开始
uv run python -m gamebot
```

④ 那一步看界面上的「识图日志」：每次匹配的**带框图 + 分数**，
一眼能看出哪张模板对不上、差多少。
