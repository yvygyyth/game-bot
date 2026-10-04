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
│   · 有向图 + 主循环 + 节奏与预算控制                              │
│   · 不认图、不点鼠标                                              │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 依赖
┌───────────────────────────▼──────────────────────────────────────┐
│ 状态层 state/           "我现在在哪个页面"                        │
│   page.py    Page / PageTree / PageMatch（单帧的纯匹配）          │
│   tracker.py PageTracker / PageState / PageChange（跨帧持续性）    │
│   store.py   Blackboard（业务共享数据）                           │
│   · 页面按模块组成树，子页面继承父页面的 ROI                       │
│   · 叠加层（弹窗）和主页面**同时成立**                            │
│   · 认不出来是常态，有显式策略                                    │
│   · 不做决定                                                      │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 依赖
┌───────────────────────────▼──────────────────────────────────────┐
│ 执行层 execution/       "可靠地做一次"                            │
│   Step / StepPolicy / RetryPolicy / Executor / Journal            │
│   · 重试、超时、跳过条件、失败代价、落盘记账                       │
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

原子层的 49 个方法全部返回 `ActionResult`，四种状态：`SUCCESS` / `NOT_FOUND` /
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

### 4. "认不出来"是一等公民

认不出页面不是异常，是最常见的情况（过场动画、加载、切场景）。所以：

- `PageTree.locate()` 即使什么都没认出来也返回 `success`，
  value 是 `PageMatch(id=UNKNOWN_PAGE)`；
- `unknown_grace` 给一段宽容期，期间只等不动作；
- 之后按 `on_unknown` 策略走（`wait` / `reload_tick` / `recovery` / `stop`）。

没有这套东西，脚本会在每次场景切换时误判并开始乱点。

### 4b. 页面是树，流程是图 —— 两者不能合并

游戏界面分模块，所以"我在哪"是棵树；但"接下来做什么"是带环的有向图
（`结算 → 首页` 这种跨分支跳回，树里没有这条边）。反过来，图的层级剪枝
和 ROI 继承也是树独有的。

**树管空间、图管时间**，唯一的接口是 `Node.page`：节点声明"我该在哪个页面上"，
实测不符就**一步动作都不做**。详见
[state-and-flow.md](state-and-flow.md)。

### 5. 平台差异收敛在后端

Windows（mss + pydirectinput）和 Android（adb）的差异被压到
`BackendBundle`（`ScreenBackend` / `InputBackend` / `WindowBackend`）三份协议里。
上面的所有层都不知道自己在哪跑。

坐标换算（逻辑分辨率 <-> 源分辨率）由 `CoordinateMapper` 做一次，
不散到后端里。

### 6. 配置驱动流程

状态、节点、转移、运行参数都能写进 YAML（`config/flows/*.yaml`）。
改流程不用改 Python，改完 `gamebot check` 就能验证。

新增一种 Query / Step 时，在注册表里登记一行即可参与配置化。

### 7. 现在就把 journal 的口子留出来

`execution/journal.py` 定义了落盘格式，虽然实现待写。原因：
**每步记录"看到什么 + 做了什么 + 结果如何"，攒够了就是模仿学习的样本。**
第一天就让格式带上帧路径、坐标、置信度，比事后补要便宜得多。

### 8. 中止（取消）挂在 Session 上，用异常传播

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
  ├─② PageTree.locate(frame, hint)   # 状态层：单帧、纯匹配
  │     ├─ 沿 hint 的路径逐层确认，不成立就退回最近的祖先
  │     │  （hint 只影响尝试顺序，不影响正确性）
  │     ├─ 每层在 effective_roi 算出的区域里跑 queries（默认 AND）
  │     ├─ 同级按 priority 降序试
  │     ├─ 走到走不动为止，最深命中者 = 当前页面
  │     └─ 再扫叠加层（OVERLAY 子节点 + 全局弹窗）
  │     -> PageMatch（一个主页面 + 若干叠加层）
  │
  ├─③ PageTracker.update(match)      # 跟踪层：连续几帧 / 从何时起
  │     -> PageChange | None（含"只换了叠加层"的情况）
  │
  ├─④ 终态判断（stop_pages / Page.terminal）
  │
  ├─⑤ 未知页面处理（宽容期内只等）
  │
  ├─⑥ 位置对齐                       # ★ 安全闸
  │     实测页面 == 当前节点声明的 page?
  │       否 -> graph.node_for_page(实测页面) 跳过去
  │             没人认领 -> 什么都不做
  │
  ├─⑦ GraphCursor.should_run(ctx)    # 确认进入 + 位置对 + 未超次数 + 冷却过
  │     └─ Executor.run_many(node.steps)   # 执行层
  │          每个 Step：precondition/skip_if -> 重试 -> on_error -> journal
  │
  ├─⑧ GraphCursor.step(ctx)          # 流程层：条件满足就换目标
  │     -> Decision（含"为什么没走这条边"的痕迹）
  │     没挑到 -> 原地不动（正常分支，不是失败）
  │
  └─⑨ 检查预算（max_runtime / max_ticks）-> ctx.sleep(tick_interval)
```

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

> **类型层（L0）完整实现；其余各层是"接口 + 契约 + 已实现的无风险部分"；
> 视觉算法（模板匹配 / OCR）和三层里真正的业务逻辑待写。**

这是刻意的顺序：先把**接口**和**分层**钉死，再填实现。
接口一旦定了，实现可以一点点长，而且每长一块都有测试兜着。
