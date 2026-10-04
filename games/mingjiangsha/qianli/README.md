# 千里单骑刷本

名将杀 / 二级功能脚本。自动刷"千里单骑"：进副本 → 战斗中循环放技能 → 结算领奖 → 回首页再来一轮。

## 文件分工

| 文件 | 放什么 | 什么时候改 |
|---|---|---|
| `pages.py` | 这个玩法的**页面**（状态对象） | 游戏 UI 改版、识别不出来 |
| `graph.py` | 这个玩法的**流程**（节点 + 边） | 玩法策略变了 |
| `steps.py` | 这个玩法**专用**的步骤 | 要在某个页面上做一组新动作 |
| `shortcuts.py` | 这个玩法专用的**快捷方法** | 同一段操作被复制了两次 |
| `templates/` | 这个玩法的**图片资源** | 截图时 |
| `__init__.py` | 装配：配置 + 场景 | 调参数 |

## 图片命名

模板名相对 `templates/`，按"界面/元素"分目录：

```
templates/
├── enter_button.png          首页上的「千里单骑」入口
├── page_header.png           千里单骑页面的特征（页面顶部标题栏）
├── stage_button.png          关卡按钮（列表里重复排布）
├── start_challenge.png       「开始挑战」
├── battle/
│   ├── skill_bar.png         战斗页面特征（右下角技能栏）
│   └── skill.png             要点的那个技能
└── result/
    ├── victory.png           结算：胜利
    ├── defeat.png            结算：失败
    └── confirm.png           「确认」
```

**只用界面上稳定的元素做模板**：标题栏、图标、按钮常态。
别用带数字的（血量、倒计时）、带特效的（高亮、动画中间帧）——
它们每天都长得不一样，是最常见的"昨天还能跑今天就不行"的来源。

## 加一个页面要动的地方

1. `pages.py` 里加 `Page(...)`，父页面选对（id 是路径形式，会自动拼）；
2. `graph.py` 里加一个 `Node(page="...")` 说这个页面上做什么；
3. 加边决定什么时候进、什么时候走。

`page` 写错不会报错，只是那条流程**永远不执行**——所以一定跑
`python -m games check mingjiangsha/qianli`，它会校验每个 `page` 都真实存在。

## 调试顺序

```bash
python -m games check mingjiangsha/qianli     # 定义对不对、缺哪些图
python -m games describe mingjiangsha/qianli  # 页面树 + 流程图长什么样
gamebot windows                               # 窗口标题该填什么
gamebot grab --region 1180,620,680,500 -o roi.png   # 调 roi 用
```

## 几个刻意的设计

**`fight` 节点没有出边。** 战斗结束前就该一直待在那儿点技能。
`next_node` 返回 `None` 是"原地不动"，**不是失败** —— 这是最常见的分支。

**`result` 页面的 `min_stable_frames: 2`。** 结算面板有弹出动画，
第一帧可能只出来一半。要求连续 2 帧命中才认，能挡掉这种"闪现"。

**`battle` 页面带 `roi`。** 只看右下角技能栏那 `680x320`，
既快又不会被别处的相似图标骗到。子页面会继承这块区域。

**技能计数兜底。** `MAX_CASTS` 次还没结束就回本页重来 ——
防的是"卡在战斗页面无限循环"。这是 `EdgeKind.FALLBACK` 的典型用法。
