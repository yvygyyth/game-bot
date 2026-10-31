# game-bot

传统识图游戏脚本框架。不依赖任何 AI/模型，就是**截图 → 找图 → 判断 → 点击**。

分四层：**状态层 / 流程层 / 执行层 / 原子化方法层**，加一个 L0 类型层。
目的是让"游戏改版了要换模板""玩法变了要改流程""电脑变慢了要加等待"
这三类修改互相不牵连。

> **新会话 / 新协作者先读 [AGENTS.md](AGENTS.md)** —— 它是入口文件：
> 该读哪几份文档、代码在哪、几条容易违反的规矩。
>
> 当前状态：**框架里已经没有"忘了实现"的桩了**，"看图"到"动手"整条链的代码都在。
> 原子层 L0~L5 + 视觉 + 平台后端全部实现并在真机验证过；
> 状态层（`locate` 快路径 / `recover` 慢路径）、流程层（`tick` 的重定位语义）、
> 执行层（步骤函数 + `Executor` + journal 落盘）都已完成；
> 业务层已有 `mingjiangsha/jingji`（名将杀 · 竞技场）跑通识别；
> 结构化事件流（`events.py`）与跨运行的**状态仓库**（`store/`，落在 `data/stores/`）
> 已实现 —— 见 [docs/store.md](docs/store.md)；
> 还差的只有**OCR 实测，以及一轮真机端到端**。
> 详见下方[进度](#进度)与[下一步](#下一步)。

---

## 怎么启动（**先读这一节**）

**整个项目只有一条命令**：

```powershell
uv run python -m gamebot
```

> 装依赖、界面每一步怎么看、出问题怎么办 —— 完整版在
> **[docs/getting-started.md](docs/getting-started.md)**。下面是精简版。

### 装依赖

```powershell
uv sync --extra windows --extra ui
```

> ⚠️ **两个 extra 要一起给** —— `uv sync` 会把没列出的 extra 卸掉，
> 只写一个另一个就没了。

### 启动界面

```powershell
uv run python -m gamebot
```

界面里**三步选完就能跑**：

```
① 选软件（下拉框列出可见窗口，并显示客户区坐标）
② 选游戏
③ 选脚本（再挑一个起始节点，调试用）
   → 勾不勾「空跑」→ ▶ 开始 / ■ 停止
```

* **选完脚本就自动检查**：定义对不对、模板图缺不缺，结论进「检查输出」页；
* **「空跑（只识别，不操作）」**：识别、决策、记账全走，唯独不碰键鼠 ——
  调脚本先勾它；
* 跑起来看「状态 / 流程」和「识图日志」（带框的图 + 分数表）。

**改代码立刻生效**，不用重新打包。

需要真机操作（点游戏、失焦按热键）时，换管理员终端跑同一条命令：

```powershell
.\dev.ps1                     # 自动提权 + venv 已激活，然后敲上面那条
```

> **为什么**：游戏是提权运行的，而 Windows 的 UIPI 要求"发送方级别 >=
> 目标窗口级别"。级别不够时点击和快捷键会**静默失效**（程序照跑、
> 日志正常，只有游戏没反应），详见 [docs/getting-started.md](docs/getting-started.md)。
> 界面上会弹一个框告诉你这件事（勾了「空跑」则不弹 —— 它不发输入）。

### 打包成 exe（可选）

**这是打包产物，不是启动方式。** 想双击就开、或发给别人用时才要：

```powershell
uv run python packaging/build_exe.py
```

产出 `dist/gamebot/gamebot.exe` + 项目根一份副本。双击它会弹 UAC（内嵌了
提权清单），点"是"就开。**改了代码要重跑**。

### 开发环境

**以管理员身份启动 VS Code** 最省事 —— 之后集成终端里跑什么都够权限。
顺序是：先在这里跑 `uv run python -m gamebot` 调脚本，需要真机操作了再提权重启。

不想提权 VS Code 的话，用这个（自动提权 + venv 已激活）：

```powershell
.\dev.ps1                                    # 管理员开发终端
.\dev.ps1 -Command "uv run python -m gamebot" # 提权后直接开界面
```

### ⚠️ 为什么真机操作要管理员：UIPI

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
（这个项目在这上面绕了很久）。界面会在开跑前弹框告诉你这件事。

**但日常开发不用管它** —— 改代码、跑测试、开界面、勾「空跑」都不碰真机输入，
普通权限就行。只有"真点游戏"才需要提权。

> 单元测试（`pytest`）**不需要管理员** —— 它不碰真机输入。

---

## 目录结构

```
game-bot/
├── assets/templates/            # 框架自带模板目录（业务层的图在自己的目录里）
├── docs/
│   ├── architecture.md          #   分层理由、关键设计决策、一次 tick 的数据流
│   ├── atomic-inventory.md      #   50 个原子方法的清单与语义
│   ├── run-context.md           #   ★ RunContext 上挂着什么（写步骤时读这份）
│   ├── state-and-flow.md        #   ★ 状态树与流程图怎么结合（关联表 / 两条定位路径）
│   ├── store.md                 #   ★ 状态仓库：跨运行的记忆（背包 / 累计局数）
│   └── ui.md                    #   ★ 本地控制台 UI 的设计（布局 / 线程 / 分阶段）
├── games/                       # ★ 业务层：具体游戏的脚本（见 games/README.md）
│   └── mingjiangsha/            #   名将杀：游戏级定义 + 各功能脚本
│       ├── templates/           #     游戏级公共模板
│       └── scripts/jingji/      #     竞技场：pages / graph / steps / store / templates
├── data/stores/<游戏>/          # ★ 跨运行的记忆（不入版本管理，别删）
├── logs/                        # 运行产物：截图 / journal / events（不入版本管理）
├── src/gamebot/
│   ├── types.py                 # ★ L0 类型层（完整实现）
│   ├── exceptions.py
│   ├── events.py                # ★ 结构化事件流（tick / 换页 / 换节点 / 步骤 / 仓库）
│   ├── feature.py               # ★ 业务层声明 FeatureSpec（一个脚本一个 SPEC）
│   ├── params.py                #   运行参数表单（FormSpec / ParamField）
│   ├── scenario_spec.py         #   状态树 + 流程图 + 关联表的**纯数据**声明
│   ├── context.py               # RunContext：三层共享的唯一对象
│   ├── bootstrap.py             # 装配：SPEC -> 事件流 / 仓库 / 对象图 -> 引擎
│   ├── __main__.py              # 唯一入口：开界面（--script / --snapshot）
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
│   │   ├── blackboard.py        #   Blackboard：**这次运行**的共享数据（开跑清空）
│   │   └── store.py             #   ★ Store：**跨运行**的记忆（一个仓库一个 JSON）
│   ├── flow/                    # ★ 流程层：做什么、何时换
│   │   ├── scenario.py          #   Scenario（状态树+流程图+参数）/ EngineOptions
│   │   ├── graph.py             #   Node / Edge / Graph / GraphCursor
│   │   ├── state_binding.py     #   ★ 关联表 StateBinding：两层唯一的桥（运行期查表）
│   │   ├── node_bindings.py     #   关联表的声明容器 NodeBindings（装配期校验）
│   │   └── engine.py            #   FlowEngine 主循环 + RunReport（含 Recovery）+ 发事件
│   ├── vision/                  # 视觉算法实现（opencv / OCR）
│   ├── config/                  # 运行期路径 / 后端种类
│   └── utils/                   # 日志、计时
├── tests/                       # 框架的结构测试 + 单元测试
├── gamebot.exe                  # 打包好的界面：双击它（见 docs/getting-started.md）
└── packaging/                   # 打包脚本（build_exe.py + 入口 entry.py）
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
uv run python -m gamebot              # 唯一那条命令
uv run pytest                         # 测试（不需要管理员、不需要游戏）
```

### 为什么特意说这件事

`uv run` 的设计就是**省掉激活那一步**，但它有个前提：**所有命令都得走它**。
少写了 `uv run`、直接敲 `python -m gamebot` 的话，用的是 PATH 里那个
`python` —— 而本机它是 **3.10.8**、项目要求 **>=3.11**，于是崩在一个
`runpy` 的堆栈里，报错内容跟你想跑的东西毫无关系。

不想每次都打 `uv run` 也可以，那就**激活一次**（一个终端里有效）：

```bash
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

python -m gamebot      # 激活之后才这么写
```

激活之后不带 `uv run` 是对的；**没激活就是错的**。文档里统一用 `uv run`
就是为了不依赖"你记不记得激活过"这个状态。

## 快速开始

```bash
cd game-bot
uv sync --extra windows --extra ui    # 第一次装依赖
uv run python -m gamebot              # 开界面，后面全在界面里
```

界面里按顺序做五件事（细节见 [docs/getting-started.md](docs/getting-started.md)）：

1. **① 软件** 选游戏窗口（下拉框里带客户区坐标，坐标错了点击会整体偏）；
2. **② 游戏 / ③ 脚本** 选脚本（可以另挑一个起始节点，调试某条分支用）；
3. **选完自动检查** —— 定义对不对、模板缺不缺，结论在「检查输出」页；
4. **勾上「空跑」点开始** —— 只识别、不碰键鼠，先确认状态和流程对不对；
5. **取消勾选，用管理员终端（`.\dev.ps1`）再开界面**，真跑。

跑完在「检查输出」里看三样最该看的东西：**停止原因**、**每次重定位**
（`expected -> actual => node`）、**失败的步骤**。逐步骤的记录在
`logs/journals/<功能>.jsonl` 里，运行流水在 `logs/events/<功能>.jsonl`。

### 写脚本（业务层）

写脚本时你会反复看三样东西，全在界面上：

| 要看什么 | 在界面哪里 |
|---|---|
| 这个脚本有哪些状态、怎么连的 | 「状态 / 流程」页（自动画成图，当前状态/节点描红） |
| 识别得准不准、框偏没偏 | 「识图日志」页（红=命中、橙=未命中、蓝=搜索范围 + 分数表） |
| 定义 / 模板有没有问题 | 「检查输出」页（选脚本时自动跑，缺图会逐张列出来） |

业务层按**游戏 → scripts → 功能**组织，脚本永远在 `scripts/<功能>/` 里
（`games/<游戏>/scripts/<功能>/`）。约定见 [games/README.md](games/README.md)；
`mingjiangsha/jingji`（名将杀 · 竞技场）是一份完整的真机样板，
里面记着几个**用数据定下来**的结论：悬浮态怎么处理、状态标识该选什么、
阈值怎么定 —— 见 [games/mingjiangsha/scripts/jingji/README.md](games/mingjiangsha/scripts/jingji/README.md)。

### 图形界面

```bash
uv sync --extra ui         # 界面依赖（PySide6，约 150MB，可选）
uv run python -m gamebot                    # 打开本地控制台
uv run python -m gamebot --script mingjiangsha/jingji   # 预选脚本
```

现在的界面能 **按三步选完就把脚本跑起来**：

```
① 选软件（下拉框列出可见窗口，并显示它的客户区坐标）
② 选游戏
③ 选脚本（再挑一个起始节点，调试用）
   → 勾不勾「空跑」/ ▶ 开始 / ■ 停止
```

**为什么"选软件"排第一**：坐标是从窗口来的 —— 截图和点击都以那个窗口的客户区
左上角为原点。窗口没定，后面两步选什么都换算不到屏幕坐标。选完立刻把坐标显示
出来，是因为它错了的表现是"每次点击都偏一个窗口位置"，而大目标看不出来。

**选完脚本就自动检查**（定义 + 逐张对模板文件），结论写进「检查输出」——
缺图会直接列 `缺模板: jj/xxx.png <- 状态 xxx`，不用等开跑才炸。

**「空跑（只识别，不操作）」**：识别、决策、记账全走，唯独不下发输入。
调脚本先勾它；勾着的时候也不弹 UIPI 警告（不发输入就没有这个问题）。

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

跑流程并拿到报告（和界面走**同一条**装配路径）：

```python
from gamebot.bootstrap import bootstrap_from_spec
from games import get_script

spec = get_script("mingjiangsha/jingji")
ctx, engine = bootstrap_from_spec(spec.feature)
try:
    report = engine.run()
finally:
    ctx.close()

print(report.summary())          # 脚本/停止原因/轮数/耗时/状态与节点轨迹
print(report.to_dict())          # 可直接 JSON 化落盘
```

## 分层与依赖规则

```
flow (流程层)  ──  做什么、何时换  有向图 + 主循环 + 节奏与预算
  ↑
state (状态层) ──  我在哪个状态    状态树（单帧定位）+ 跟踪层（跨帧）+ 黑板
  ↑
execution (执行层) ── 可靠地做一次  步骤 + 记账 + 失败留痕（不重试）
  ↑
atomic (原子层) ── 怎么做        L0~L5 共 50 个原子方法
```

**依赖只能向下**，由 `tests/test_structure.py` 用 AST 静态检查强制。

六条容易踩的边界（详见 [docs/architecture.md](docs/architecture.md)
和 [docs/state-and-flow.md](docs/state-and-flow.md)）：

1. 状态层**只回答"是什么"**，认不出来也要如实说，不猜、不做决定；
2. 流程层**只回答"去哪儿"**，不直接碰键鼠；
3. 状态是**树**、流程是**图**，两者不能合并 —— 树管空间，图管时间；
4. 绑定给节点的状态和实测不符时，**本轮一个动作都不做**，而是走重定位
   （慢路径找回真实状态 → 关联表查出该去哪个节点 → 游标落过去，下一轮才执行），
   并且**每次都记进 `RunReport.recoveries`** —— 自动跳可以，隐形不行
   （这条推翻了早期的"只拦不跳"，见 [docs/state-and-flow.md](docs/state-and-flow.md)）；
5. 没绑状态的节点**不校验状态**（"流程图只写正常流程"），但状态侧反过来是硬的：
   每个记录信息的状态都必须有节点认领，否则启动期就 `ConfigError`；
6. 执行层**只回答"怎么可靠地做一次"**，不决定做不做。

## 启动开发环境

**这个项目没有"启动"这一步** —— 它不是 web 服务，没有 dev server、没有构建、
没有热重载。`src/gamebot/` 是纯 Python 包，改完存盘，下一条命令就是新代码。
所以"起环境"只有三件事：**依赖装好、自检绿、界面起得来**。

```bash
cd game-bot
uv sync --extra windows --extra ui    # ① 依赖（已齐时约 1 秒，纯校验）
uv run ruff check . && uv run pytest  # ② 自检：必须全绿
uv run python -m gamebot              # ③ 起界面（约 2 秒起来，然后常驻）
```

**这三步都不需要游戏开着**（`uv sync` / 测试用假后端 / 界面不管游戏在不在），
所以即使手头没游戏也能确认环境是好的。第 ③ 步的无头版本：

```bash
uv run python -m gamebot --snapshot out.png   # 渲染一张就退出
```

### 按你要做的事选入口

| 要做什么 | 怎么做 | 要游戏开着吗 |
|---|---|---|
| **写一个步骤函数** | 先读 [docs/run-context.md](docs/run-context.md)（`ctx` 上有什么） | 不用 |
| 改界面 | `uv run python -m gamebot` | **不用** |
| 跑测试 | `uv run pytest` | **不用**（假后端） |
| 改识图/流程 | 界面勾「空跑」跑一轮，看「识图日志」 | **要**（窗口得存在） |
| 只跑某一条分支 | 界面上选「起始节点」 | **要** |
| 看定义/模板对不对 | 选脚本即自动检查，看「检查输出」 | 不用 |
| 调真机识别 | 跑一轮，看「识图日志」的带框图 + 分数表 | **要** |
| 无头环境（CI / 没显示器） | `uv run python -m gamebot --snapshot out.png` | 不用 |

**"要游戏开着"的意思是"那个窗口得存在"**：空跑也会先抓屏，所以窗口不在时界面里报

```
✗ BackendError: 未找到标题包含 '名将杀' 的窗口
```

**这不是环境坏了**，是没开游戏。窗口下拉框旁边的「重新检测」可以刷新列表。

### 需要知道的几件事

* **哪些 extra 要装**：PC 游戏要 `--extra windows`，界面要 `--extra ui`；
  不读文字就不用装 OCR 那两个（`--extra ocr-rapid` / `--extra ocr-tesseract`）。
  **装了就会自动启用**（`bootstrap` 按已装的包选 RapidOCR / Tesseract）；
  都没装时 `find_text` / `read_text` 返回 `not_found`，日志里会说清原因。
* **没有构建步骤、没有热重载**：改完存盘，下一条命令就是新代码。
  唯一例外是**已经开着的界面** —— Python 只在启动时加载模块，所以改完
  界面代码要**关掉重开**（曾经以为是 bug：界面上还留着已经删掉的按钮）。
* **真机上有环境可能拦掉鼠标注入**（连 `SetCursorPos` 都返回 0 且无错误码）。
  遇到别怀疑代码，先看「识图日志」里的图是不是正常画面（全黑 = 截屏就不通）。

## 进度

| 模块 | 状态 | 说明 |
|---|---|---|
| L0 类型层 | ✅ 完整 | `ActionResult` / `Point` / `Region`，含全部便捷方法 |
| L1 Session | ✅ 完整 | 截图编排、坐标换算、生命周期、平台分发 |
| L2 Frame | ✅ 完整 | 12 个查询方法全部实现，含帧内缓存与子帧坐标换算 |
| L3 Query | ✅ 完整 | 11 个描述符 + 注册表；`query_from_dict` 把数据还原成 Query（回放/测试用） |
| L4 组合子 | ✅ 完整 | 5 个帧内 + 5 个跨帧，统一 error 透传语义 |
| L5 动作 | ✅ 完整 | 14 个动作（含 `click_source_point`），逻辑坐标自动换算，`click_image` 找不到不点 |
| 视觉算法 | ✅ OpenCV 完整 | `OpenCvMatcher`：模板缓存/多尺度/NMS/NaN 兜底；OCR 两个实现**已接上装配**（装了包就自动启用），真机实测待做 |
| 平台后端 | ✅ 完整 | windows（mss + pydirectinput/pyautogui）、android（adb） |
| fake 后端 | ✅ 完整 | 内存实现，记录所有输入调用 —— 测试与空跑用 |
| 状态层 | ✅ 完整 | ★ 状态树（`Page`/`PageTree`/`PageMatch`）、分类节点（`PageKind.GROUP`）、ROI 继承、两条定位路径（`locate` 快 / `recover` 慢）、跟踪层、校验全部实现 |
| 流程层 | ✅ 完整 | ★ 流程图（`Graph`/`Node`/`Edge`/`GraphCursor`）、关联表（`StateBinding`）、`Scenario` 跨树图校验、`FlowEngine.tick` 的重定位全部实现 |
| 执行层 | ✅ 完整 | 步骤是函数 / 结果记录 / `Executor.run` / journal JSONL 落盘全部实现（重试策略已按"上层重定位"模型删掉） |
| 装配 | ✅ 完整 | `bootstrap_from_spec` 是**唯一**装配入口：SPEC → 事件流 / 仓库 / Matcher / Session / Context / Executor / Engine；有集成测试整条走一遍 |
| 业务层 | 🟡 部分 | ★ 游戏 → scripts → 功能，注册表自动发现；界面里选脚本即检查（定义 + 逐张对模板文件）；`mingjiangsha/jingji`（名将杀 · 竞技场）是真机样板 |
| 状态仓库 | ✅ 完整 | ★ 跨运行的记忆：一个脚本可用多个仓库，`games/…/store/` 一个仓库一个文件，落 `data/stores/<游戏>/<id>.json`；原子写、坏文件留证据不挡开跑；见 [docs/store.md](docs/store.md) |
| 事件流 | ✅ 完整 | ★ `events.py`：`run_started` / `tick` / `page_changed` / `node_changed` / `step_started` / `step_finished` / `recovery` / `store_changed` / `run_finished`，落 `logs/events/<功能>.jsonl`；监听器出错不影响流程 |
| 日志 | 🟡 部分 | 控制台 + 文件 handler、内存环形缓冲、界面回调桥、journal JSONL、事件流已实现；每次运行独立日志待实现 |
| UI | ✅ 完成 | PySide6 本地控制台：**① 软件（含客户区坐标）→ ② 游戏 → ③ 脚本**、选脚本即检查、**「空跑」勾选框**、开始/停止真的能跑、运行状态面板（含每次重定位）、识图日志（带框图）、检查输出。设计见 [docs/ui.md](docs/ui.md)；`python -m gamebot` 打开 |
| 测试 | ✅ 950+ 用例 | 框架的结构契约与单元测试（含 16 个跳过：依赖 UI/OCR 的可选环境） |

> **原子化方法层（L0~L5 + 视觉 + 平台后端）已全部实现并在真机上验证过**
> （真实截图 2560x1440、窗口枚举、模板匹配坐标、坐标换算、组合子调度、动作下发）。
> **整条链现在都通了**：状态层两条定位路径、流程层的重定位语义、执行层的
> `Executor.run`、journal / 事件流落盘都已实现，并且在 fake 后端上端到端跑通过
> （`tests/test_bootstrap_integration.py` 走的就是真实的装配入口）。
> 真机上验过的仍然只有识别与输入这条链 —— 端到端一轮真机运行还没做过。
>
> **显式的桩已经没有了**：原来那个 `PageTree.from_nested` 随"YAML 装配路径"
> （`flow/loader.py` + `config/`）一起删了 —— 那条路没有任何调用方，
> 现在装配只有 `bootstrap_from_spec` 一条。

### 下一步

原子层已封板，业务层、状态层/流程层/执行层的实现也齐了，事件流与状态仓库也已落地。
按依赖顺序还剩：

1. **UI 接事件流** —— 状态面板改成订阅 `EventBus`（现在还在用回调），
   加一页「记忆」按仓库分组显示 `ctx.stores`
2. **OCR 实测** —— 装 `--extra ocr-rapid` 后跑一遍 `find_text`
3. **真机端到端** —— 现在只验到识别；拿 `mingjiangsha/jingji` 真跑一轮，
   看 `RunReport` 的轨迹（含 `recoveries`）和 `logs/events/jingji.jsonl` 是不是符合预期
4. **拆大文件** —— `state/page.py`（约 1450 行）、`flow/engine.py`（约 1150 行）、
   `flow/graph.py`（约 810 行）按概念拆开；纯搬迁，靠测试兜底

## 开发约定

- **失败用返回值，不用异常**。原子层与执行层返回 `ActionResult`；
  异常只留给装配期错误（配置写错、模板不存在、依赖没装）。
- **唯一例外是 `Cancelled`**：它表示"别再继续了"，不是"失败了"。
  它继承 `BaseException` 而不是 `Exception` —— 这样它不会被
  `except Exception` 的兜底逻辑吞掉。**永远不要写裸 `except:`**。
- **失败了不重试**：失败（多半是识图没命中）由流程层拿实测状态**重定位**，
  不在步骤里补重试循环。
- **不要在另一个线程里 `close()` session**。停止只设标志（`request_stop`），
  等工作线程自己退出后再关。
- **不要绕过 `ctx.frame()` 直接截图**。同一 tick 内的步骤必须看同一张图。
- **坐标一律源分辨率**，逻辑分辨率只在写脚本时用，由 `CoordinateMapper` 换算。
- **先问"下次开还该记得吗"**：该 → `ctx.store(...)`（声明放 `store/` 目录，
  落 `data/stores/`）；不该 → `ctx.blackboard`（开跑清空）；是用户填进来的 →
  `ctx.param(...)`（表单校验）。三者混用是这里最容易犯的错。
- **仓库的 `get` 拿到的是副本**。改复合值要用 `set` / `patch` / `append`，
  不要指望"就地改一下就存下来了"。
- **新增 Query 类型要登记**（`atomic/query.py` 的注册表），否则 `query_from_dict`
  认不出它。
- **状态树里父节点一律是分类节点（`PageGroup`），只有末梢状态节点写 `queries`** ——
  分类节点自己不记录信息、不参与匹配；给它写 `queries` 或让它空着，校验都会报出来。
- 提交前跑：`uv run ruff check . && uv run mypy && uv run pytest`

## 依赖

| 类别 | 包 | 何时需要 |
|---|---|---|
| 基础 | numpy, opencv-python, mss, Pillow, PyYAML | 总是 |
| Windows 后端 | `--extra windows`：pywin32, pydirectinput | PC 游戏 |
| Android 后端 | `--extra android`：adbutils | 手游 |
| OCR | `--extra ocr-rapid` 或 `--extra ocr-tesseract` | 需要读文字时 |
