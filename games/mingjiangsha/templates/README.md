# 名将杀 · 游戏级公共模板

跨脚本共用的图放这里。查找顺序是 **功能级优先、本目录兜底**：

```
games/mingjiangsha/scripts/<功能>/templates/   ← 先找（可以覆盖同名图）
games/mingjiangsha/templates/                  ← 再找（公共图）
```

## 按钮：**一个文件夹 = 一种按钮**

```
templates/shadowConfirm/     金色发光按钮：创建队伍 / 添加伙伴 / 确定 …
templates/patternConfirm/    金色花纹边框的大按钮：确定
templates/shadowCancel/      青色发光按钮：取消
templates/QJ/                蓝底金框按钮：下一步
```

> 同一家族里放的是**这种按钮的各种文字版本**。同一时刻、同一个位置只会出现一个，
> 所以"把家族里每张图都试一遍，谁命中就点谁"不会歧义。

调用时只说"点哪种按钮"，不说"点哪句字"：

```python
from games.mingjiangsha.templates import BUTTON_SHADOW_CANCEL, BUTTON_SHADOW_CONFIRM
from games.mingjiangsha.utils import click_button

click_button(ctx, BUTTON_SHADOW_CONFIRM)   # 创建队伍 / 添加伙伴 / 确定 都算
click_button(ctx, BUTTON_SHADOW_CANCEL)    # 取消
click_button(ctx, BUTTON_QJ_NEXT)          # 下一步
```

**加一种文字版本不用改代码**：裁一张这个按钮的图丢进对应文件夹即可。
**加一种新按钮**：新建文件夹，调用时传文件夹名。

### 裁图约定

1. **完整包含按钮**（四周留 2~3 像素），别带按钮之外的大片背景 —— 背景会随界面变；
2. 同一家族里不同文字版本**互不命中**（文字就是差异），所以不会"一个按钮算两个"；
3. **一种按钮一个文件夹**。混进两种不同按钮会让 `pick="only"` 频繁报错。
4. **同一个按钮的多张截图版本可以共存**（比如不同分辨率各裁了一张）——
   它们会同时命中同一个按钮，`find_buttons` 按位置去重、只留分数最高的那张。
   但**同一批截图里尽量只留一套**：混着放会让日志里的分数忽高忽低，不好判断阈值。

### 实测（15 张真机截图，灰度 + 金字塔）

| 截图 | 家族 | 命中 | 分数 |
|---|---|---|---|
| `tip1.png` | `shadowConfirm` | **1**（ok.png 确定） | 0.998 |
| `tip1.png` | `shadowCancel` | **1**（cancel.png 取消） | 0.999 |
| `jingji1.png` | `shadowConfirm` | **1**（before_create.png 创建队伍） | 0.999 |
| `jingji2.png` | `shadowConfirm` | **1**（after_create.png 添加伙伴） | 0.999 |
| `select2.png` | `patternConfirm` | **1**（ok1.png） | 0.998 |
| `zhandou6.png` | `QJ` | **1**（qj1.png 下一步） | 0.999 |
| `zhandou7.png` | `QJ` | **1**（qj2.png） | 0.999 |
| 其余 8 张 | 各家族 | **0**（不该有） | — |

所以 `click_button` 的默认阈值取 **0.90**（正例 0.998+，留足余量）。
`tests/test_button_families.py` 会每次都复算这张表 —— 模板裁歪、换分辨率、
游戏改版，提交前就红。

## 为什么**不用**一条边线模板统一所有按钮

试过：取一条 12x33 的竖边去匹配所有金框按钮。**裁剪图上**很漂亮（四类按钮
0.951~1.000，青色取消 0.678 分得开）。但在**整屏截图**上它命中 100 次 ——
面板边框、图标边缘全是"亮竖边"。这种误命中在裁剪图上一辈子看不出来，
到了真机上就是"偶发点错地方"。

整按钮模板的代价是"一种文字版本一张图"，收益是**不会误命中**：
上面那张表里，15 张真机截图每个家族最多命中 1 次。

## 原始素材

`shadowConfirm/` 等目录里的图**同时**是运行期模板和重裁素材 ——
换分辨率/改版后，从这里挑一张重新裁即可。界面选脚本时的检查会把它们归到
"游戏级另有 N 张没被 `T_*` 声明（按钮家族按文件夹约定使用，不算错）"，
只有**功能级**里没声明的图才会被当成"该删的旧图"列出来。
