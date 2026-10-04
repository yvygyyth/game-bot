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
│   FlowDefinition / FlowNode / Transition / FlowMachine / Engine   │
│   · 状态机 + 主循环 + 节奏与预算控制                              │
│   · 不认图、不点鼠标                                              │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 依赖
┌───────────────────────────▼──────────────────────────────────────┐
│ 状态层 state/           "现在是什么状态"                          │
│   StateDefinition / StateDetector / StateStore / Blackboard       │
│   · 识别 = 一组 Query 的组合，带优先级与连续帧确认                 │
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

### 4. "未知状态"是一等公民

认不出状态不是异常，是最常见的情况（过场动画、加载、切场景）。
所以：

- `detect()` 即使什么都没认出来也返回 `success`，value 是 `UNKNOWN_STATE` 快照；
- `unknown_grace` 给一段宽容期，期间只等不动作；
- 之后按 `on_unknown` 策略走（`wait` / `reload_tick` / `recovery` / `stop`）。

没有这套东西，脚本会在每次场景切换时误判并开始乱点。

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

## 四、一次 tick 的完整数据流

```
FlowEngine.tick()
  │
  ├─① ctx.frame()                    # 拿帧（TTL 内复用，否则重截）
  │
  ├─② StateDetector.detect(frame)    # 状态层
  │     ├─ 按 priority 降序遍历 StateDefinition
  │     ├─ 先求 exclude（否决），再求 queries（默认 AND）
  │     ├─ 子结果置信度取均值
  │     └─ 连续命中计数（min_stable_frames）
  │     -> StateSnapshot
  │
  ├─③ StateStore.update(snapshot)    # 记录 + 判断是否切换
  │     -> StateChange | None
  │
  ├─④ 终态判断（stop_states / terminal）
  │
  ├─⑤ FlowMachine.select(...)        # 流程层：挑转移
  │     ├─ candidates = transitions_from(current)，按 priority 降序
  │     ├─ 检查 max_times / cooldown
  │     ├─ 求 guard（在当前帧上跑 Query）
  │     └─ 挑到 -> apply() -> on_enter 子步骤
  │     没挑到 -> 继续做当前节点的事（正常分支）
  │
  ├─⑥ Executor.run_many(node.steps)  # 执行层
  │     └─ 每个 Step：precondition/skip_if -> 重试循环 -> on_error -> journal
  │
  └─⑦ 检查预算（max_runtime / max_ticks）-> ctx.sleep(tick_interval)
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
