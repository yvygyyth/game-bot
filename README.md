# game-bot

传统识图游戏脚本框架。不依赖任何 AI/模型，就是**截图 → 找图 → 判断 → 点击**。

分四层：**状态层 / 流程层 / 执行层 / 原子化方法层**，加一个 L0 类型层。
目的是让"游戏改版了要换模板""玩法变了要改流程""电脑变慢了要加等待"
这三类修改互相不牵连。

> 当前状态：**结构已完成，类型层（L0）与各层"无风险部分"已实现，
> 视觉算法与三层业务逻辑待写**。详见下方[进度](#进度)。

---

## 目录结构

```
game-bot/
├── config/                      # 配置（YAML）—— 改流程不用改 Python
│   ├── app.yaml                 #   主配置：后端 / 视觉 / 节奏 / 路径
│   ├── regions.yaml             #   命名区域：把坐标从代码里挪出来
│   └── flows/example_flow.yaml   #   流程样板：状态 + 节点 + 转移
├── assets/templates/            # 模板图（按界面分子目录）
├── docs/
│   ├── architecture.md          #   分层理由、关键设计决策、一次 tick 的数据流
│   └── atomic-inventory.md      #   49 个原子方法的清单与语义
├── logs/                        # 运行产物（不入版本管理）
├── src/gamebot/
│   ├── types.py                 # ★ L0 类型层（完整实现）
│   ├── exceptions.py
│   ├── context.py               # RunContext：三层共享的唯一对象
│   ├── bootstrap.py             # 装配：配置 -> 对象图 -> 引擎
│   ├── __main__.py              # CLI
│   ├── atomic/                  # ★ 原子化方法层
│   │   ├── session.py           #   L1 截图 + 坐标换算 + 输入通道
│   │   ├── frame.py             #   L2 一帧 + 12 个查询方法
│   │   ├── query.py             #   L3 可序列化的查询描述符
│   │   ├── combinators.py       #   L4 多查询协作 + 跨帧等待
│   │   ├── actions.py           #   L5 点/拖/滚/按键
│   │   ├── vision.py            #   Matcher / TextReader 协议
│   │   └── backends/            #   平台后端：windows / android / fake
│   ├── execution/               # ★ 执行层：步骤 + 重试 + 记账
│   │   ├── step.py              #   Step 家族
│   │   ├── policy.py            #   RetryPolicy / StepPolicy / ErrorMode
│   │   ├── executor.py          #   Executor
│   │   └── journal.py           #   落盘记录（JSONL 契约）
│   ├── state/                   # ★ 状态层：识别 + 快照 + 黑板
│   │   ├── definition.py        #   StateDefinition
│   │   ├── detector.py          #   StateDetector
│   │   ├── snapshot.py          #   StateSnapshot / StateChange
│   │   └── store.py             #   StateStore / Blackboard
│   ├── flow/                    # ★ 流程层：状态机 + 主循环
│   │   ├── definition.py        #   FlowDefinition
│   │   ├── node.py              #   FlowNode
│   │   ├── transition.py        #   Transition
│   │   ├── machine.py           #   FlowMachine
│   │   ├── engine.py            #   FlowEngine
│   │   └── loader.py            #   YAML -> FlowDefinition
│   ├── vision/                  # 视觉算法实现（opencv / OCR）
│   ├── config/                  # 配置模型与加载
│   └── utils/                   # 日志、计时
├── tests/                       # 结构测试 + 已实现部分的测试
└── main.py                      # 不安装也能跑：python main.py run
```

## 快速开始

```bash
cd game-bot
uv sync                 # 装依赖（Windows 后端还需要 --extra windows）

# 先确认能看到窗口、能截到图 —— 这一步能省掉后面 80% 的瞎猜
uv run gamebot windows
uv run gamebot capture -o logs/screenshots/first.png

# 把窗口标题填进 config/app.yaml 的 screen.window_title，然后
uv run gamebot check              # 校验配置 + 流程 + 模板文件
uv run gamebot run --dry-run      # 空跑：只识别状态，不操作游戏
uv run gamebot run                # 真跑
```

不装包也能用（自动把 `src/` 加进 `sys.path`）：

```bash
python main.py capture -o a.png
```

### CLI 子命令

| 命令 | 用途 |
|---|---|
| `gamebot info` | 打印本次生效的完整配置（排查"配置到底读了没"） |
| `gamebot check` | 校验配置 / 流程定义 / 模板文件是否存在 |
| `gamebot windows` | 列出可见窗口（确定 `window_title` 填什么） |
| `gamebot capture` | 截一张全屏图存盘（验证后端与 DPI） |
| `gamebot grab --region x,y,w,h` | 只截一个区域存盘（调 ROI 用） |
| `gamebot run [--dry-run]` | 跑流程 |

## 用法示例

只做识图，不进流程：

```python
from gamebot.atomic.session import build_session
from gamebot.vision.opencv_matcher import OpenCvMatcher

session = build_session("windows", matcher=OpenCvMatcher("assets/templates"), window_title="游戏")
with session:
    frame = session.capture()                    # 截一次
    hp = frame.read_number(Region(100, 50, 80, 30))
    btn = frame.find_image("attack.png")         # 同一帧上查，时序一致
    if btn.ok:
        print("按钮在", btn.value, "相似度", btn.meta.get("score"))
```

一次判断多个目标（1 次截图 + N 次匹配）：

```python
from gamebot.atomic.combinators import find_any_of
from gamebot.atomic.query import ImageQuery

frame = session.capture()
result = find_any_of(frame, [
    ImageQuery("victory.png"),
    ImageQuery("defeat.png"),
    ImageQuery("disconnect.png"),
], short_circuit=True)
```

跑流程并拿到报告：

```python
from gamebot.bootstrap import run_flow

report = run_flow("config/app.yaml")
print(report.summary())          # 流程/停止原因/轮数/耗时/状态轨迹
print(report.to_dict())          # 可直接 JSON 化落盘
```

## 分层与依赖规则

```
flow (流程层)  ──  该做什么     状态机 + 主循环 + 节奏与预算
  ↑
state (状态层) ──  现在什么状态  识别 + 快照 + 黑板
  ↑
execution (执行层) ── 可靠地做一次  步骤 + 重试 + 失败代价 + 记账
  ↑
atomic (原子层) ── 怎么做        L0~L5 共 49 个原子方法
```

**依赖只能向下**，由 `tests/test_structure.py` 用 AST 静态检查强制。

三条容易踩的边界（详见 [docs/architecture.md](docs/architecture.md)）：

1. 状态层**只回答"是什么"**，认不出来也要如实说，不猜、不做决定；
2. 流程层**只回答"去哪儿"**，不直接碰键鼠；
3. 执行层**只回答"怎么可靠地做一次"**，不决定做不做。

## 进度

| 模块 | 状态 | 说明 |
|---|---|---|
| L0 类型层 | ✅ 完整 | `ActionResult` / `Point` / `Region`，含全部便捷方法 |
| L1 Session | ✅ 完整 | 截图编排、坐标换算、生命周期、平台分发 |
| L2 Frame | ✅ 完整 | 12 个查询方法全部实现，含帧内缓存与子帧坐标换算 |
| L3 Query | ✅ 完整 | 11 个描述符 + 注册表（`query_from_dict` 归流程层，未写） |
| L4 组合子 | ✅ 完整 | 5 个帧内 + 5 个跨帧，统一 error 透传语义 |
| L5 动作 | ✅ 完整 | 13 个动作，逻辑坐标自动换算，`click_image` 找不到不点 |
| 视觉算法 | ✅ OpenCV 完整 | `OpenCvMatcher`：模板缓存/多尺度/NMS/NaN 兜底；OCR 两个实现已写但未装依赖验证 |
| 平台后端 | ✅ 完整 | windows（mss + pydirectinput/pyautogui）、android（adb） |
| fake 后端 | ✅ 完整 | 内存实现，记录所有输入调用 —— 测试与空跑用 |
| 状态层 | 🟡 部分 | 定义/快照/黑板/存储已实现；`detect` / `update` 待实现 |
| 流程层 | 🟡 部分 | 定义/节点/转移/状态机骨架已实现；`select` / `apply` / `validate` / `tick` 待实现 |
| 执行层 | 🟡 部分 | 策略对象/步骤构造/结果记录已实现；`Executor.run` 待实现 |
| 配置层 | ✅ 完整 | `merge_dataclass` / YAML 加载 / 区域表 / 校验 |
| 测试 | ✅ 235 个用例 | 结构契约 + 已实现部分的行为 |

> **原子化方法层（L0~L5 + 视觉 + 平台后端）已全部实现并在真机上验证过**
> （真实截图 2560x1440、窗口枚举、模板匹配坐标、坐标换算、组合子调度、动作下发）。
> 剩下的就是状态层 / 流程层 / 执行层里那几个核心方法。

### 下一步

原子层已封板（L0~L5 + 视觉 + 平台后端全部实现并在真机验证过），
接下来按依赖顺序填上层：

1. `StateDetector.detect` + `StateStore.update` —— 状态层闭环
2. `FlowMachine.select/apply` + `FlowDefinition.validate` + `FlowEngine.tick` —— 流程跑通
3. `Executor.run` + `JsonlJournal.record` —— 可观测性
4. `flow/loader.py`（含 `query_from_dict`）—— 让 YAML 真正驱动流程
5. OCR 实测（装 `--extra ocr-rapid` 后跑一遍 `find_text`）

## 开发约定

- **失败用返回值，不用异常**。原子层与执行层返回 `ActionResult`；
  异常只留给装配期错误（配置写错、模板不存在、依赖没装）。
- **不要绕过 `ctx.frame()` 直接截图**。同一 tick 内的步骤必须看同一张图。
- **坐标一律源分辨率**，逻辑分辨率只在写脚本时用，由 `CoordinateMapper` 换算。
- **新增 Query / Step 类型必须登记注册表**，否则 YAML 里写不出来。
- 提交前跑：`uv run ruff check . && uv run pytest`

## 依赖

| 类别 | 包 | 何时需要 |
|---|---|---|
| 基础 | numpy, opencv-python, mss, Pillow, PyYAML | 总是 |
| Windows 后端 | `--extra windows`：pywin32, pydirectinput | PC 游戏 |
| Android 后端 | `--extra android`：adbutils | 手游 |
| OCR | `--extra ocr-rapid` 或 `--extra ocr-tesseract` | 需要读文字时 |
