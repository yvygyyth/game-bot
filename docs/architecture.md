# 架构说明

## 一、为什么分四层

传统识图脚本烂掉的典型路径是这样的：

```python
# 第一天，能用
while True:
    if find("start.png"): click("start.png")
    elif find("attack.png"): click("attack.png")
    time.sleep(1)

# 两周后，没人敢动
while True:
    if find("start.png", 0.85) and not find("loading.png") and tick > 3:
        click(find("start.png", 0.85), offset=(2, 2))   # 为什么 +2？不知道
        time.sleep(0.7)                                  # 为什么 0.7？不知道
        if fails > 3: restart_game()
    elif ...
```

问题不在代码风格，在于**四种不同的决策被搅在了一起**：

| 决策 | 例子 | 变化频率 |
|---|---|---|
| 我看到什么 | "按钮在 (960,540)" | 游戏改版时 |
| 这是什么状态 | "现在是主界面" | 游戏改版时 |
| 该做什么 | "进战斗" | 玩法变了时 |
| 怎么可靠地做 | "点 3 次，间隔 0.5s" | 电脑变慢时 |

分四层的直接目的就是让这四种修改**互不牵连**。

## 二、层次与依赖

```
┌──────────────────────────────────────────────────────────────────┐
│ 流程层 flow/            "接下来做什么"                            │
│   Scenario = PageTree + Graph + EngineOptions                     │
│   Node / Edge / Graph（蓝图）/ GraphCursor（运行游标）/ Engine     │
│   StateBinding = 状态 ↔ 节点 的关联表（两层唯一的桥）              │
│   · 有向图 + 主循环 + 节奏与预算控制                              │
│   · 不认图、不点鼠标                                              │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 依赖
┌───────────────────────────▼──────────────────────────────────────┐
│ 状态层 state/           "我现在在哪个状态"                        │
│   page.py    Page / PageTree / PageMatch（单帧的纯匹配）          │
│   tracker.py PageTracker / PageState / PageChange（跨帧持续性）    │
│   store.py   Blackboard（业务共享数据）                           │
│   · 状态按模块组成树，子状态继承父节点的 ROI                       │
│   · 分类节点（PageGroup）不记录信息、不参与匹配，只做组织与 ROI    │
│   · 叠加层（弹窗）和主状态**同时成立**                            │
│   · 定位两条路径：locate（快，只探预期）/ recover（慢，扩散）      │
│   · 认不出来是常态，有显式策略                                    │
│   · 不做决定                                                      │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 依赖
┌───────────────────────────▼──────────────────────────────────────┐
│ 执行层 execution/       "做一次，并如实记账"                       │
│   步骤函数 / Executor / Journal                                   │
│   · 落盘记账、失败帧留存 · **不重试**（失败由上层重定位）           │
│   · 不判断游戏状态，不决定下一步                                   │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 依赖
┌───────────────────────────▼──────────────────────────────────────┐
│ 原子化方法层 atomic/    "怎么做"                                   │
│   L5 actions  ── 点/拖/滚/按键（13）                               │
│   L4 combinators ── 多查询协作 + 跨帧等待（10）                    │
│   L3 query    ── 可序列化的查询描述符（11）                        │
│   L2 frame    ── 一帧截图 + 12 个查询方法                          │
│   L1 session  ── 截图 + 坐标换算 + 输入通道（3）                    │
│   L0 types    ── ActionResult / Point / Region                     │
└──────────────────────────────────────────────────────────────────┘
```

**依赖只能向下。** 这条规则由 `tests/test_structure.py::test_layer_does_not_import_upward`
用 AST 静态检查强制，不是靠自觉。

横切关注点（不属于任何一层）：

- `config/`   —— YAML -> 有类型的 `AppConfig`
- `context.py`—— `RunContext`，三层共享的唯一对象
- `bootstrap.py` —— 装配与启动前的检查
- `vision/`   —— `Matcher` / `TextReader` 的具体实现（opencv / OCR）
- `utils/`    —— 日志、计时

## 三、关键设计决策

### 1. 失败用返回值表达，不用异常

原子层的 50 个方法全部返回 `ActionResult`，四种状态：`SUCCESS` / `NOT_FOUND` /
`TIMEOUT` / `ERROR`。

理由：识图脚本里"没找到"是**正常情况**（平均每帧要找 5 次，其中 4 次找不到），
用异常表达正常流程，性能和可读性都很糟。只有装配期错误（配置写错、模板不存在）
才抛异常 —— 那些应该启动时就炸。

### 2. `not_found` 与 `success(False)` 是两回事

- `find_image()` 找不到 -> `not_found`（这是个**失败**，可能需要重试）
- `is_image_visible()` 不可见 -> `success(False)`（这是个**有效答案**）

混用会写出 bug：流程守卫里判断"这个弹窗不在"时，如果用 `find_image`，
每次弹窗正常消失都会记一次失败，统计和重试逻辑全部失真。

### 3. 帧是显式的，且有 TTL

`RunContext` 缓存当前帧，同一 tick 内的步骤看同一张图。需要新图必须显式声明
（`CaptureStep` 或 `needs_fresh_frame=True`）。

同时帧有 TTL（默认 `2 × tick_interval`）：卡在某个界面 30 秒后，
一帧旧图会骗过所有查询。TTL 到期自动重截，不需要人工干预。

### 4. 入参和"跑出来的状态"是两件东西

`RunContext` 上有两个容器，一字之差但语义完全不同，混用会出**很难查**的错：

| | `ctx.param(name, default)` | `ctx.blackboard` |
|---|---|---|
| 是什么 | **入参**：这次运行的输入 | **跑出来的状态** |
| 谁写 | 外面（CLI / 界面 / 测试） | 步骤自己 |
| 跑的过程中变吗 | **不变** | 一直在变 |
| `ctx.reset()` 会清吗 | **不会** | 会 |

为什么需要入参：`Scenario` 是在 `build_scenario()` 里构造的**静态对象** ——
那次调用拿不到任何运行期信息，而"这次刷几局""用哪套阈值""开不开某个分支"
要等到点开始才知道。没有入参，这些值只能写死在脚本里。

```python
# 命令行
uv run python -m games run mingjiangsha/jingji --param rounds=5 --param target=battle

# 步骤里读（给了默认值就是"可选参数"）
rounds = ctx.param("rounds", 3)
```

参数名建议点分层级（`"farm.rounds"`）避免撞名。CLI 的值会尽量转成
int / float / 布尔 —— 否则步骤里拿到的是字符串，`range("5")` 直接炸，
而报错点在步骤、跟命令行看不出关系。

### 5. 一次运行以"清干净"开始

`FlowEngine.run()` 一开头会清掉上一次留下的运行期状态：引擎自己的
`_stop_reason`、节点的"首次进入"记录、访问计数、跟踪器、黑板、中止标志、
缓存的帧、执行器攒的步骤结果。**运行参数不动**（见上一条）。

这不是洁癖，是踩出来的：

* `_stop_reason` 不清 → `running` 就是"它是不是 None"，而循环是
  `while self.running` → **第二遍一进循环就退出、一个步骤都不做**，
  报告还写着 COMPLETED；
* 执行器的 `outcomes` 不清 → 第二遍报告的步数算上第一遍，
  表现是"跑 3 轮却报了 7 步"，越跑越多；
* 黑板不清 → 第一次和第二次跑行为不同，而代码看起来一模一样。

副作用（正确的那种）：跟踪器被清掉之后，第二次运行要**重新确认**状态
（`require_confirmed` 要连续几帧），所以开头几轮不动手。这是有意的 ——
"刚开跑就照着上一遍的印象点"比"多看两帧"危险得多。

### 6. "认不出来"是一等公民

认不出状态不是异常，是最常见的情况（过场动画、加载、切场景）。所以：

- `PageTree.locate()` 即使什么都没认出来也返回 `success`，
  value 是 `PageMatch(id=UNKNOWN_PAGE)`；
- `unknown_grace` 给一段宽容期，期间只等不动作；
- 之后按 `on_unknown` 策略走（`wait` / `reload_tick` / `recovery` / `stop`）。

没有这套东西，脚本会在每次场景切换时误判并开始乱点。

### 7. 状态是树，流程是图 —— 两者不能合并

游戏界面分模块，所以"我在哪"是棵树；但"接下来做什么"是带环的有向图
（`结算 → 首页` 这种跨分支跳回，树里没有这条边）。反过来，图的层级剪枝
和 ROI 继承也是树独有的。

**树管空间、图管时间**，唯一的接口是 `Node.page`（以及同状态多节点时用来
挑主节点的 `Node.priority`），查表在 `flow/binding.py` 的关联表里。三件事
都走它：动前校验、重定位去向、动后预期。

实测状态和节点声明不符时，引擎**不会硬着头皮执行**，但也**不是原地干等**：
它用慢路径找回真实状态，再问关联表该落到哪个节点，本轮不执行、下一轮执行，
并记一条 `Recovery`。详见 [state-and-flow.md](state-and-flow.md)。

### 8. 平台差异收敛在后端

Windows（mss + pydirectinput）和 Android（adb）的差异被压到
`BackendBundle`（`ScreenBackend` / `InputBackend` / `WindowBackend`）三份协议里。
上面的所有层都不知道自己在哪跑。

坐标换算（逻辑分辨率 <-> 源分辨率）由 `CoordinateMapper` 做一次，
不散到后端里。

### 9. 配置驱动流程

状态、节点、转移、运行参数都能写进 YAML（`config/flows/*.yaml`）。
改流程不用改 Python，改完 `gamebot check` 就能验证。

新增一种 Query / Step 时，在注册表里登记一行即可参与配置化。

### 10. 每步都记账（journal 已实现）

`execution/journal.py` 定义了落盘格式，`JsonlJournal` 已经按 JSONL 写盘
（`gamebot run` 默认落在 `paths.journals/run.jsonl`）。原因：
**每步记录"看到什么 + 做了什么 + 结果如何"，攒够了就是模仿学习的样本。**
第一天就让格式带上帧路径、坐标、置信度，比事后补要便宜得多。

### 11. 中止（取消）挂在 Session 上，用异常传播

`wait_any_of(timeout=60)` 卡在那里时点"停止"，**必须立刻响应**，否则用户会强杀进程 ——
而强杀会让 `finally` 不执行，于是 `hotkey` 不松键、`drag` 不做 `mouseUp`，
留下一个卡住的 Ctrl 或者被拖住的整个桌面。

**三条路里只有一条同时满足"立即"和"能收尾"**：

| 做法 | 立即？ | 能收尾？ |
|---|---|---|
| 协作式检查（本项目） | ✅ 0.1ms | ✅ `finally` 照常执行 |
| 跑在线程里直接弃掉 | ✅ | ❌ Python 没有安全的 `Thread.kill`，`finally` 不跑 |
| kill 子进程 | ✅ | ❌ kill 就是 kill，同样不跑 `finally` |

**状态放在 `Session` 上，而不是给方法加 `signal` 参数。** 因为 `Session`
是原子层**唯一**已经拿到手的上下文对象 —— 等价于 Go 的 `ctx`、
.NET 的 `CancellationToken`、前端的 `AbortSignal`，只不过"传参"这件事
早就做完了。于是：

* **零签名改动**：所有原子方法的对外契约一行没变 —— 中止是**新增的可选行为**
  （等待循环顺手看一眼标志），不是新参数、不是新返回值；
* **没有"忘了传"这个失败模式**：不需要调用方记得往下递；
* **L4 连异常类型都不用知道**：只调 `session.raise_if_stopped()` 和
  `session.sleep()`，中止机制整个封在 L1 里。

**传播靠 `Cancelled(BaseException)`，不靠返回值。** 返回值表达"这次尝试的结果"，
异常表达"别再继续了"。继承 `BaseException` 是关键 —— 框架里到处是
`except Exception: return ActionResult.error(...)`（用来兜后端故障），
中止绝不能被它们吞掉，否则"点了停止没反应"会变成最难查的一类 bug。
`KeyboardInterrupt` / `SystemExit` 出于同样的理由也是 `BaseException`。

实现细节：`threading.Event` 而不是 bool，因为 `Event.wait()` 能被 `set()`
**立刻唤醒** —— 既睡眠又无需分片轮询。实测响应 **0.1ms**。

⛔ **中止绝不能被重试。** `RetryPolicy.retry_on` 枚举的是 `ActionStatus`，
而中止是异常，天然不参与 —— 但这个性质很脆弱：一旦有人把重试条件改写成
"非成功即可重试"，中止就会变成死循环。所以 `policy.py` 里专门写了警告注释。

实测（另一个线程扮演 UI 停止按钮）：

```
wait_any_of(60s)       Cancelled(测试中止)   中止响应=0.1ms
wait_all_of(60s)       Cancelled(测试中止)   中止响应=0.1ms
wait_until(60s)        Cancelled(测试中止)   中止响应=0.1ms
wait_stable(60s)       Cancelled(测试中止)   中止响应=0.1ms
wait_disappear(60s)    Cancelled(测试中止)   中止响应=0.1ms
actions.sleep(30)      Cancelled(测试中止)   中止响应=0.1ms
```

**改不动的部分**（诚实记下来）：`adb exec-out screencap` 是子进程调用，
上限是 `AdbClient.timeout`（默认 20s）；OCR 推理中途也无法打断。
Windows 上单次抓屏是毫秒级，所以现实上限 ≈ 一次抓帧。

**收尾顺序**（UI 必须遵守）：

```
session.request_stop("用户点了停止")   # 任意线程，只设标志
工作线程自己退出（Cancelled 穿透到 FlowEngine）
session.close()                       # 最后才关
```

⚠️ **不要在另一个线程里直接 `close()`** —— 那一刻可能正有一帧 `capture()` 在飞。

## 四、一次 tick 的完整数据流

```
FlowEngine.tick()
  │
  ├─① ctx.frame()                    # 拿帧（TTL 内复用，否则重截）
  │
  ├─② expected = binding.expects(游标当前节点)
  │   PageTree.locate(frame, expected=...)   # ★ 快路径：只探预期那一页
  │     ├─ 先精确验 expected，命中就返回（再扫一遍叠加层）
  │     ├─ 不成才自顶向下逐层下探，hint 只影响尝试顺序、不影响正确性
  │     ├─ GROUP 分类节点不匹配、直接下探它的子节点
  │     ├─ 每层在 effective_roi 算出的区域里跑 queries（默认 AND）
  │     ├─ 同级按 priority 降序试
  │     └─ 再扫叠加层（OVERLAY 子节点 + 全局弹窗）
  │     -> PageMatch（一个主状态 + 若干叠加层）
  │
  ├─③ PageTracker.update(match)      # 跟踪层：连续几帧 / 从何时起
  │     -> PageChange | None（含"只换了叠加层"的情况）
  │
  ├─④ 终态判断（stop_pages / Page.terminal）
  │
  ├─⑤ 状态自检：锚点 == 我以为我在的地方？
  │     是 -> 走正常路径
  │     否 -> ★ 重定位（不是干等，也不是硬着头皮执行）：
  │           a. PageTree.recover(frame, near=expected)  慢路径：末梢优先 + 扩散
  │           b. binding.node_for(真锚点) 问出"这归哪个节点管"
  │           c. 游标落到那个节点，本轮不执行（先把位置摆正）
  │           d. 记一条 Recovery（expected / actual / to_node / 试过谁）
  │
  ├─⑥ GraphCursor.should_run(ctx)    # 未超 max_visits + cooldown 已过
  │     （"状态确认进入"由引擎在它之前查：require_confirmed + tracker.confirmed）
  │     └─ Executor.run(step) 逐个跑   # 执行层
  │          每个 Step：precondition/skip_if -> 重试 -> on_error -> journal
  │
  ├─⑦ GraphCursor.step(ctx)          # 流程层：条件满足就换目标
  │     -> Decision（含"为什么没走这条边"的痕迹）
  │     没挑到 -> 原地不动（正常分支，不是失败）
  │
  └─⑧ 检查预算（max_runtime / max_ticks）-> ctx.sleep(tick_interval)
```

认不出来（`unknown`）不算"走错了"——那是"看不清"，由 `unknown_grace` 宽容期
和 `on_unknown` 策略处理，宽容期内**只等不动作**。

## 五、调试方法论（重要）

写识图脚本 80% 的时间花在"我截到的到底是不是我以为的画面"上。
所以最省时间的三个命令是：

```bash
gamebot windows                 # 窗口标题该填什么
gamebot capture -o a.png        # 全屏截一张，看后端对不对、DPI 有没有问题
gamebot grab --region 100,50,80,30 -o roi.png   # 调 ROI 的时候反复用
gamebot check                   # 模板文件齐不齐、配置有没有拼错
```

流程跑通之前先 `--dry-run`：只识别状态、不走动作，看流程走向对不对。

## 六、当前进度

见根目录 README 的进度表。一句话总结：

> **四层都实现了。** `grep -rn NotImplementedError src/` 还能搜到几处，但除了
> 一个之外全是**抽象方法的占位**（`Session` 的截图方法与两个属性、`Step.run`），
> 以及 CLI 里的异常处理。真正的桩只剩 `PageTree.from_nested` ——
> 配置解析故意留在流程层的 `flow/loader.py`：状态层不许 import 流程层，
> 所以它自己不能解析配置（那条依赖方向由 `tests/test_structure.py` 的 AST 检查盯着）。
> 还差的是 `events.py`（结构化事件流）、UI 阶段 2 接线、OCR 实测，
> 以及一轮真机端到端验证。

这是刻意的顺序：先把**接口**和**分层**钉死，再填实现。
接口一旦定了，实现可以一点点长，而且每长一块都有测试兜着。
