# game-bot

传统识图游戏脚本框架。不依赖任何 AI/模型，就是**截图 → 找图 → 判断 → 点击**。

分四层：**状态层 / 流程层 / 执行层 / 原子化方法层**，加一个 L0 类型层。
目的是让"游戏改版了要换模板""玩法变了要改流程""电脑变慢了要加等待"
这三类修改互相不牵连。

> **新会话 / 新协作者先读 [AGENTS.md](AGENTS.md)** —— 它是入口文件：
> 命令、该读哪几份文档、现在卡在哪、以及几条容易违反的规矩。
>
> 当前状态：**框架里已经没有"忘了实现"的桩了**。唯一一个**显式**的桩是
> `PageTree.from_nested`（理由写在它的 docstring 里，见下），"看图"到"动手"
> 整条链的代码都在。
> 原子层 L0~L5 + 视觉 + 平台后端全部实现并在真机验证过；
> 状态层（`locate` 快路径 / `recover` 慢路径）、流程层（`tick` 的重定位语义）、
> 执行层（`Executor.run` + 10 个 `Step.run()`）、YAML 加载与 journal 落盘都已实现；
> 业务层已有 `mingjiangsha/jingji`（名将杀 · 竞技场）跑通识别；
> 还差的只有**结构化事件流、UI 阶段 2 接线、OCR 实测，以及一轮真机端到端**。
> 详见下方[进度](#进度)与[下一步](#下一步)。

---

## 怎么启动（**先读这一节**）

### 界面

**双击桌面的 `gamebot 界面（管理员）`** → 点一下 UAC 的"是" → 界面出来。
没有命令行、没有控制台窗口。

### 开发

**以管理员身份启动 VS Code**，之后集成终端里跑什么都够权限。
不想提权 VS Code 的话，需要真机操作时用它：

```powershell
.\dev.ps1                                              # 管理员开发终端（自动提权）
.\dev.ps1 -Command "python -m games doctor mingjiangsha/jingji"
```

### ⚠️ 为什么必须管理员：UIPI

Windows 有一条硬规则：**发送方进程的完整性级别必须 >= 目标窗口的级别**。
**这台机器上游戏是提权运行的**，所以：

| 启动方式 | 级别 | 结果 |
|---|---|---|
| 普通终端 / AI 工具自带的终端 | Low | ✗ |
| 普通双击 | Medium | ✗ |
| **以管理员身份运行** | **High** | **✓** |

级别不够时**一切都是静默失效的** —— 程序退出码 0、识别命中、
动作层返回 `success`，**只有游戏没反应**：

* 鼠标指针**会**移到正确位置（`SetCursorPos` 不受 UIPI 限制）；
* 点击**不生效**（`SendInput` 返回成功，消息被丢掉）；
* 失焦后全局快捷键也收不到（低级键盘钩子收不到高权限窗口的按键）。

表现和"坐标算错了""模板裁错了"一模一样，所以极易查错方向
（这个项目在这上面绕了很久）。

### 跑真机操作前先自检

```bash
uv run python -m games doctor mingjiangsha/jingji
```

一次查完：**权限级别 / 前台窗口 / 模板能不能读到 / 抓屏通不通**，
有问题就非零退出并说清是哪一条。

> 单元测试（`pytest tests/`）**不需要管理员** —— 它不碰真机输入。

---

## 目录结构

```
game-bot/
├── config/                      # 框架级配置样板（app.yaml / regions.yaml）
│   ├── app.yaml                 #   主配置：后端 / 视觉 / 节奏 / 路径
│   ├── regions.yaml             #   命名区域：把坐标从代码里挪出来
│   └── flows/example_flow.yaml   #   脚本定义样板（状态树 + 流程图）
├── assets/templates/            # 框架自带模板目录（业务层的图在自己的目录里）
├── docs/
│   ├── architecture.md          #   分层理由、关键设计决策、一次 tick 的数据流
│   ├── atomic-inventory.md      #   50 个原子方法的清单与语义
│   ├── run-context.md           #   ★ RunContext 上挂着什么（写步骤时读这份）
│   ├── state-and-flow.md        #   ★ 状态树与流程图怎么结合（关联表 / 两条定位路径）
│   └── ui.md                    #   ★ 本地控制台 UI 的设计（布局 / 线程 / 分阶段）
├── games/                       # ★ 业务层：具体游戏的脚本（见 games/README.md）
│   └── mingjiangsha/            #   名将杀：游戏级定义 + 各功能脚本
│       ├── templates/           #     游戏级公共模板
│       └── jingji/              #     竞技场脚本：状态 / 流程 / 步骤
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
│   ├── execution/               # ★ 执行层：跑步骤 + 记账
│   │   ├── step.py              #   步骤契约（就是一个函数）+ 命名
│   │   ├── builtins.py          #   常用步骤：click_image / wait_for / run_all …
│   │   ├── executor.py          #   Executor（只调函数 + 记账，不重试）
│   │   └── journal.py           #   落盘记录（JSONL 契约）
│   ├── state/                   # ★ 状态层：我在哪个状态
│   │   ├── page.py              #   状态树 Page / PageTree / PageMatch + 定位两条路径
│   │   ├── tracker.py           #   PageTracker / PageState / PageChange（跨帧）
│   │   └── store.py             #   Blackboard（业务共享数据）
│   ├── flow/                    # ★ 流程层：做什么、何时换
│   │   ├── scenario.py          #   Scenario（状态树+流程图+参数）/ EngineOptions
│   │   ├── graph.py             #   Node / Edge / Graph / GraphCursor
│   │   ├── binding.py           #   ★ 关联表 StateBinding：两层唯一的桥
│   │   ├── engine.py            #   FlowEngine 主循环 + RunReport（含 Recovery）
│   │   └── loader.py            #   YAML -> Scenario
│   ├── vision/                  # 视觉算法实现（opencv / OCR）
│   ├── config/                  # 配置模型与加载
│   └── utils/                   # 日志、计时
├── tests/                       # 框架的结构测试 + 单元测试
└── main.py                      # 不安装也能跑：uv run python main.py run
```

**框架和业务是分开的**：`src/gamebot/` 不认识任何具体游戏；
`games/` 才是认识游戏的地方（一级按游戏、二级按脚本功能）。
写业务代码只碰 `games/`，改框架才碰 `src/gamebot/`。

`tests/` 放的是**框架自己**的单元测试（层级依赖、类型契约、决策逻辑）；
（图齐不齐、ROI 框得对不对、状态之间有没有区分度）。两边职责不同。

## 虚拟环境和"怎么执行命令"

**这个项目的命令一律走 `uv run`。** 它会自动用 `.venv`，所以：

* 不需要先 `activate`；
* 也不会用错解释器。

```bash
uv sync --extra windows --extra ui    # 第一次：装依赖（顺便建好 .venv）
uv run gamebot ui                     # 以后每条命令都在前面加 uv run
uv run python -m games list
```

### 为什么特意说这件事

`uv run` 的设计就是**省掉激活那一步**，但它有个前提：**所有命令都得走它**。
少写了 `uv run`、直接敲 `python -m games ...` 的话，用的是 PATH 里那个
`python` —— 而本机它是 **3.10.8**、项目要求 **>=3.11**，于是崩在一个
`runpy` 的堆栈里，报错内容跟你想跑的东西毫无关系。

不想每次都打 `uv run` 也可以，那就**激活一次**（一个终端里有效）：

```bash
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

python -m games list      # 激活之后才这么写
```

激活之后不带 `uv run` 是对的；**没激活就是错的**。文档里统一用 `uv run`
就是为了不依赖"你记不记得激活过"这个状态。

## 快速开始

**每条命令都走 `uv run`** —— 它自动用 `.venv`，不需要先激活，也不会
用错解释器（原因见下面"虚拟环境"那一节）。

```bash
cd game-bot
uv sync --extra windows --extra ui    # 装依赖（第一次）

# 先确认能看到窗口、能截到图 —— 这一步能省掉后面 80% 的瞎猜
uv run gamebot windows
uv run gamebot capture -o logs/screenshots/first.png

# 把窗口标题填进 config/app.yaml 的 screen.window_title，然后
uv run gamebot check              # 校验配置 + 流程 + 模板文件
uv run gamebot run --dry-run      # 空跑：只识别状态，不操作游戏
uv run gamebot run                # 真跑
```

> `gamebot check` 查的是 `config/app.yaml` 里那份**示例流程**，它引用的 10 张
> 模板图**没有入库**（`assets/templates/` 只有一个 `.gitkeep`）。所以它报
> "缺失 10 个模板文件"、退出码 1 是**预期的** —— 那是让人照着抄格式的样例，
> 不是能直接跑的东西。要查一个真脚本用
> `uv run python -m games check <脚本>`。

不装包也能用（`main.py` 自动把 `src/` 加进 `sys.path`）：

```bash
uv run python main.py capture -o a.png
```

### 写脚本（业务层）

```bash
uv run python -m games list                          # 有哪些脚本
uv run python -m games describe mingjiangsha/jingji  # 状态树 + 流程图（不连游戏）
uv run python -m games check    mingjiangsha/jingji  # 定义对不对、缺哪些图

# 真的跑起来。建议按 check -> --dry-run -> 真跑 的顺序来
uv run python -m games run mingjiangsha/jingji --dry-run --max-ticks 20   # 空跑：不碰键鼠
uv run python -m games run mingjiangsha/jingji --max-runtime 300          # 真跑
uv run python -m games run mingjiangsha/jingji --node jingji              # 从中间某个节点开始调
```

`run` 跑完会打三样最该看的东西：**停止原因**、**每次重定位**
（`expected -> actual => node`）、**失败的步骤**。
逐步骤的记录在 `logs/journals/<功能>.jsonl` 里。

> 退出码有意义：预算跑完算成功（0），而"一个步骤都没执行、从头到尾 unknown"
> 算失败（1）—— 那基本就是窗口标题不对 / 游戏没开 / 没站在预期界面上。

业务层按**一级游戏、二级功能**组织，脚本永远在功能目录里
（`games/<游戏>/<功能>/`）。约定见 [games/README.md](games/README.md)；
`mingjiangsha/jingji`（名将杀 · 竞技场）是一份完整的真机样板，
里面记着几个**用数据定下来**的结论：悬浮态怎么处理、状态标识该选什么、
阈值怎么定 —— 见 [games/mingjiangsha/jingji/README.md](games/mingjiangsha/jingji/README.md)。

### 图形界面

```bash
uv sync --extra ui         # 界面依赖（PySide6，约 150MB，可选）
gamebot ui                 # 打开本地控制台
gamebot ui --script none   # 不选脚本，只用 config/app.yaml 看画面
```

现在的界面能 **按三步选完就把脚本跑起来**：

```
① 选软件（下拉框列出可见窗口，并显示它的客户区坐标）
② 选游戏
③ 选脚本（再挑一个起始节点，调试用）
   → 检查 / ▶ 开始 / ■ 停止
```

**为什么"选软件"排第一**：坐标是从窗口来的 —— 截图和点击都以那个窗口的客户区
左上角为原点。窗口没定，后面两步选什么都换算不到屏幕坐标。选完立刻把坐标显示
出来，是因为它错了的表现是"每次点击都偏一个窗口位置"，而大目标看不出来。

跑起来之后：**引擎在工作线程**（界面不卡），右侧实时显示当前/期望状态、当前节点、
轮次、以及**每次重定位**（"我以为在 A，实际在 B，已落到节点 C"）。「停止」是毫秒级的。

左上那三页是调脚本时真正要看的东西：

| 页 | 里面是什么 |
|---|---|
| **状态 / 流程** | 状态树、流程图**画成图**，**当前状态描红加粗、当前节点描红**；两者不一致时一个红一个绿边 —— 那正是重定位的瞬间 |
| **识图日志** | **每次匹配的带框图**（红框=命中、橙框=未命中、蓝框=搜索范围）+ 结构化表格（查了什么、在哪搜、几分、中没中）。点某一行直接跳到它那一帧的图 |
| **检查输出** | 检查 / 每次运行的结论 |

> **没有实时画面。** 试过，但它回答不了真问题：同一帧上"logo 在左上角 0.98"和
> "在右下角 0.91"在缩略图里长得一样，而一个是命中、一个是偶然相似。
> 能看出差别的是**把框画在图上**。带框的图最多留 20 张
> （`vision.record_keep`），只清理框架自己写的 `match_*.png`。

设计、线程模型、以及做完之后回填的坑见 [docs/ui.md](docs/ui.md)。

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
from gamebot.bootstrap import run_scenario

report = run_scenario("config/app.yaml")
print(report.summary())          # 脚本/停止原因/轮数/耗时/状态与节点轨迹
print(report.to_dict())          # 可直接 JSON 化落盘
```

## 分层与依赖规则

```
flow (流程层)  ──  做什么、何时换  有向图 + 主循环 + 节奏与预算
  ↑
state (状态层) ──  我在哪个状态    状态树（单帧定位）+ 跟踪层（跨帧）+ 黑板
  ↑
execution (执行层) ── 可靠地做一次  步骤 + 重试 + 失败代价 + 记账
  ↑
atomic (原子层) ── 怎么做        L0~L5 共 50 个原子方法
```

**依赖只能向下**，由 `tests/test_structure.py` 用 AST 静态检查强制。

六条容易踩的边界（详见 [docs/architecture.md](docs/architecture.md)
和 [docs/state-and-flow.md](docs/state-and-flow.md)）：

1. 状态层**只回答"是什么"**，认不出来也要如实说，不猜、不做决定；
2. 流程层**只回答"去哪儿"**，不直接碰键鼠；
3. 状态是**树**、流程是**图**，两者不能合并 —— 树管空间，图管时间；
4. 节点声明的 `page` 和实测状态不符时，**本轮一个动作都不做**，而是走重定位
   （慢路径找回真实状态 → 关联表查出该去哪个节点 → 游标落过去，下一轮才执行），
   并且**每次都记进 `RunReport.recoveries`** —— 自动跳可以，隐形不行
   （这条推翻了早期的"只拦不跳"，见 [docs/state-and-flow.md](docs/state-and-flow.md)）；
5. 不写 `page` 的节点**不校验状态**（"流程图只写正常流程"），但状态侧反过来是硬的：
   每个记录信息的状态都必须有节点认领，否则启动期就 `ConfigError`；
6. 执行层**只回答"怎么可靠地做一次"**，不决定做不做。

## 启动开发环境

**这个项目没有"启动"这一步** —— 它不是 web 服务，没有 dev server、没有构建、
没有热重载。`src/gamebot/` 是纯 Python 包，改完存盘，下一条命令就是新代码。
所以"起环境"只有三件事：**依赖装好、自检绿、想跑的入口跑得起来**。

```bash
cd game-bot
uv sync --extra windows --extra ui    # ① 依赖（已齐时约 1 秒，纯校验）
uv run ruff check . && uv run pytest  # ② 自检：必须全绿（实测约 5 秒 / 664 用例）
uv run gamebot ui                     # ③ 起界面（约 2 秒起来，然后常驻）
```

**这三步都不需要游戏开着**（`uv sync` / 测试用假后端 / 界面不管游戏在不在），
所以即使手头没游戏也能确认环境是好的。第 ③ 步的无头版本：

```bash
QT_QPA_PLATFORM=offscreen uv run gamebot ui --snapshot out.png   # 渲染一张就退出
```

### 按你要做的事选入口

| 要做什么 | 命令 | 要游戏开着吗 |
|---|---|---|
| **写一个步骤函数** | 先读 [docs/run-context.md](docs/run-context.md)（`ctx` 上有什么） | 不用 |
| 改界面 | `uv run gamebot ui`（可加 `--script mingjiangsha/jingji` 预选） | **不用** |
| 跑测试 | `uv run pytest` | **不用**（假后端） |
| 改识图/流程 | `uv run python -m games run mingjiangsha/jingji --dry-run --max-ticks 20` | **要** |
| 只跑某一条分支 | 上面加 `--node <节点>`：把游戏手动摆到那一步，不用从头玩 | **要** |
| 看定义对不对 | `uv run python -m games check mingjiangsha/jingji` | 不用 |
| 调真机识别 | 起来跑一次，看界面的「识图日志」（带红框的图 + 分数表） | **要** |
| 无头环境（CI / 没显示器） | `QT_QPA_PLATFORM=offscreen uv run gamebot ui --snapshot out.png` | 不用 |

**"要游戏开着"的意思是"那个窗口得存在"**：连 `--dry-run` 和
`gamebot capture` 都会先去抓屏，所以窗口不在时它们报的是

```
✗ BackendError: 未找到标题包含 '名将杀' 的窗口        （退出码 2）
```

**这不是环境坏了**，是没开游戏。先 `uv run gamebot windows` 看当前有哪些窗口，
用 `--window <标题片段>` 覆盖。**没有游戏时能验证的东西仍然不少**：界面能起来、
测试能全过、`check` 能过、`describe` 能看状态树和流程图。

### 需要知道的几件事

* **哪些 extra 要装**：PC 游戏要 `--extra windows`，界面要 `--extra ui`；
  不读文字就不用装 OCR 那两个（`--extra ocr-rapid` / `--extra ocr-tesseract`），
  没装时 `find_text` / `read_text` 返回 `not_found`，**不影响其他功能**。
* **`uv run gamebot check` 会退出 1**，这是**预期的**：它查的是
  `config/app.yaml` 里那份示例流程，而示例引用的 10 张模板图没入库。
  查真脚本用 `uv run python -m games check <脚本>`。
* **没有构建步骤、没有热重载**：改完存盘，下一条命令就是新代码。
  唯一例外是**已经开着的界面** —— Python 只在启动时加载模块，所以改完
  界面代码要**关掉重开**（曾经以为是 bug：界面上还留着已经删掉的按钮）。
* **真机上有环境可能拦掉鼠标注入**（连 `SetCursorPos` 都返回 0 且无错误码）。
  遇到别怀疑代码，先 `uv run gamebot capture -o a.png` 看截屏通不通。

## 进度

| 模块 | 状态 | 说明 |
|---|---|---|
| L0 类型层 | ✅ 完整 | `ActionResult` / `Point` / `Region`，含全部便捷方法 |
| L1 Session | ✅ 完整 | 截图编排、坐标换算、生命周期、平台分发 |
| L2 Frame | ✅ 完整 | 12 个查询方法全部实现，含帧内缓存与子帧坐标换算 |
| L3 Query | ✅ 完整 | 11 个描述符 + 注册表；`query_from_dict` 已实现（在 `atomic/query.py`，由流程层 loader 调用） |
| L4 组合子 | ✅ 完整 | 5 个帧内 + 5 个跨帧，统一 error 透传语义 |
| L5 动作 | ✅ 完整 | 14 个动作（含 `click_source_point`），逻辑坐标自动换算，`click_image` 找不到不点 |
| 视觉算法 | ✅ OpenCV 完整 | `OpenCvMatcher`：模板缓存/多尺度/NMS/NaN 兜底；OCR 两个实现已写但未装依赖验证 |
| 平台后端 | ✅ 完整 | windows（mss + pydirectinput/pyautogui）、android（adb） |
| fake 后端 | ✅ 完整 | 内存实现，记录所有输入调用 —— 测试与空跑用 |
| 状态层 | ✅ 完整 | ★ 状态树（`Page`/`PageTree`/`PageMatch`）、分类节点（`PageKind.GROUP`）、ROI 继承、两条定位路径（`locate` 快 / `recover` 慢）、跟踪层、校验全部实现 |
| 流程层 | ✅ 完整 | ★ 流程图（`Graph`/`Node`/`Edge`/`GraphCursor`）、关联表（`StateBinding`）、`Scenario` 跨树图校验、`FlowEngine.tick` 的重定位、YAML 加载全部实现 |
| 执行层 | ✅ 完整 | 策略对象/步骤构造（`step_from_dict`）/结果记录/`Executor.run`/10 个 Step 的 `run()`/journal JSONL 落盘全部实现 |
| 配置层 | ✅ 完整 | `merge_dataclass` / YAML 加载 / 区域表 / 校验 |
| 业务层 | 🟡 部分 | ★ 一级游戏 / 二级功能，注册表自动发现，`check`/`describe`/`run` 已实现；`mingjiangsha/jingji`（名将杀 · 竞技场）是真机样板 |
| 日志 | 🟡 部分 | 控制台 + 文件 handler、内存环形缓冲、界面回调桥、journal JSONL 已实现；每次运行独立日志、结构化事件流待实现 |
| UI | ✅ 阶段 2 完成 | PySide6 本地控制台：**① 软件（含客户区坐标）→ ② 游戏 → ③ 脚本**、开始/停止真的能跑、运行状态面板（含每次重定位）、实时画面（跑起来时复用引擎那一帧）、日志大框、检查。设计见 [docs/ui.md](docs/ui.md)；`gamebot ui` 打开 |
| 测试 | ✅ 536 个用例 | 框架的结构契约与单元测试 |

> **原子化方法层（L0~L5 + 视觉 + 平台后端）已全部实现并在真机上验证过**
> （真实截图 2560x1440、窗口枚举、模板匹配坐标、坐标换算、组合子调度、动作下发）。
> **整条链现在都通了**：状态层两条定位路径、流程层的重定位语义、执行层的
> `Executor.run` 与 10 个 `Step.run()`、YAML 加载、journal 落盘都已实现，
> 并且在 fake 后端上端到端跑通过（`verify_new_model.py` + `tests/test_flow.py`）。
> 真机上验过的仍然只有识别与输入这条链 —— 端到端一轮真机运行还没做过。
>
> **唯一剩下的显式桩是 `PageTree.from_nested`**：配置怎么解析故意留在流程层的
> `flow.loader.parse_pages` —— 状态层不许 import 流程层，所以它自己不能解析配置。
> 桩里写了这条理由，不是忘了实现。

### 下一步

原子层已封板，业务层、状态层/流程层/执行层的实现也齐了。按依赖顺序还剩：

1. **`events.py`（结构化事件流）+ 每次运行独立日志** —— UI 阶段 2 与 journal 的数据源
2. **UI 阶段 2 接线** —— 开始/停止、状态面板（预览要改成复用引擎那一帧），
   顺手把窗口里那几句"尚未实现"的 tooltip 改成事实
3. **OCR 实测** —— 装 `--extra ocr-rapid` 后跑一遍 `find_text`
4. **真机端到端** —— 现在只验到识别；拿 `mingjiangsha/jingji` 真跑一轮，
   看 `RunReport` 的轨迹（含 `recoveries`）是不是符合预期

## 开发约定

- **失败用返回值，不用异常**。原子层与执行层返回 `ActionResult`；
  异常只留给装配期错误（配置写错、模板不存在、依赖没装）。
- **唯一例外是 `Cancelled`**：它表示"别再继续了"，不是"失败了"。
  它继承 `BaseException` 而不是 `Exception` —— 这样它不会被
  `except Exception` 的兜底逻辑吞掉。**永远不要写裸 `except:`**。
- **中止不能被重试**。`RetryPolicy.retry_on` 是枚举而不是"非成功即可重试"，
  请保持这个写法。
- **不要在另一个线程里 `close()` session**。停止只设标志（`request_stop`），
  等工作线程自己退出后再关。
- **不要绕过 `ctx.frame()` 直接截图**。同一 tick 内的步骤必须看同一张图。
- **坐标一律源分辨率**，逻辑分辨率只在写脚本时用，由 `CoordinateMapper` 换算。
- **新增 Query / Step 类型必须登记注册表**，否则 YAML 里写不出来。
- **状态树里父节点一律 `kind: group`（分类节点），只有末梢状态节点写 `queries`** ——
  分类节点自己不记录信息、不参与匹配；给它写 `queries` 或让它空着，校验都会报出来。
- **YAML 里那一节叫 `states:`**（旧键 `pages:` 仍兼容，但新配置别再写）。
- 提交前跑：`uv run ruff check . && uv run pytest`

## 依赖

| 类别 | 包 | 何时需要 |
|---|---|---|
| 基础 | numpy, opencv-python, mss, Pillow, PyYAML | 总是 |
| Windows 后端 | `--extra windows`：pywin32, pydirectinput | PC 游戏 |
| Android 后端 | `--extra android`：adbutils | 手游 |
| OCR | `--extra ocr-rapid` 或 `--extra ocr-tesseract` | 需要读文字时 |
