# 千里单骑 · 模板与状态

模板根就是本目录。`rawMaterial/` 是真机整屏截图，**运行时不使用**（审计会跳过）。

## 四个 select 状态

| 状态 | 怎么认 | 缺什么 |
|---|---|---|
| `qianli/select1` | 千里单骑标题 + **灰色**开始挑战 + 「选择武将」占位卡 | 选将面板 |
| `qianli/select2` | 标题 + 「武将选择」面板标题 + 搜索按钮 + 占位卡 | — |
| `qianli/select3` | 标题 + 面板标题 + 搜索按钮 | **占位卡**（被武将卡替换了） |
| `qianli/select4` | 标题 + **红色**开始挑战 | 占位卡、面板 |

`select2` / `select3` 的差别就是那张占位卡；`select3` 用 `exclude` 判它不在。

## 模板表

位置是**源坐标 2560x1369**（游戏客户区，不含 Windows 任务栏）。分数是裁图在原图上的实测。

| 文件 | 来源 | 裁的是什么 | 位置（x,y,w,h） | 分数 |
|---|---|---|---|---|
| `first/status-select-1-1.png` | `rawMaterial/first1.png` | 首页右上角小图标（首页锚点） | 2427,257,62,61 | 1.000 |
| `first/status-select-2.png` | `rawMaterial/first2.png` | 战役界面：战旗 + 战役商店 | 6,40,518,361 | 1.000 |
| `first/select-1-1.png` | `rawMaterial/first1.png` | 首页「战役」卡（点击用固定坐标，见下） | 1854,512,282,343 | 0.885 |
| `first/select-2-1.png` | `rawMaterial/first2.png` | 战役页「千里单骑」卡（点击） | 727,517,256,319 | 1.000 |
| `select/status-1.png` | `rawMaterial/select1.png` | 千里单骑标题（select1~4） | 5,28,461,85 | 1.000 |
| `select/status-wujiang-select-title.png` | `rawMaterial/select2.png` | 「武将选择」面板标题 | 1099,838,347,64 | 1.000 |
| `select/select-wujiang.png` | `rawMaterial/select1.png` | 「选择武将」占位卡 | 主界面 2013,533 / 面板 2013,257 | 0.998 / 0.971 |
| `select/search-wujiang.png` | `rawMaterial/select2.png` | 「搜索」按钮 | 2327,944,139,56 | 1.000 |
| `select/start.png` | `rawMaterial/select4.png` | 红色「开始挑战」（可开局） | 1999,1208,391,91 | 1.000 |
| `select/status-start-disable.png` | `rawMaterial/select1.png` | 灰色「开始挑战」（没选将） | 2004,1210,391,84 | 1.000 |
| `flow/status-1.png` | `rawMaterial/flow1.png` | 局内标题「千里单骑 · 无尽」 | 18,28,501,92 | 1.000 |

## 固定坐标（步骤里用）

| 位置 | 坐标（源） | 说明 |
|---|---|---|
| 首页「战役」卡中心 | `1995, 683` | 模板 0.885，光照一变就可能掉到阈值下；位置固定，直接点 |
| 搜索框 | 「搜索」按钮中心左移 160px | 面板布局固定 |
| 搜索结果第一张卡 | `200, 1100` | 搜索后结果只剩一张，固定在这个位置 |

## 状态目录

```
home（容器）
├── root
├── campaign
└── qianli
    ├── qianli/select1
    ├── qianli/select2
    ├── qianli/select3
    ├── qianli/select4
    └── qianli/flow        （terminal 占位，局内后续实现）
```
