# `RunContext` 上挂着什么

**什么时候读这份**：写一个步骤函数（`(ctx) -> ActionResult`）的时候。
这是步骤能拿到东西的**唯一**入口 —— 没有全局变量、没有单例、没有 `self`。

源码：`src/gamebot/context.py`。这份文档是它的**索引**，
细节（为什么这么设计）写在源码的 docstring 里，不在这儿重复。

---

## 一眼看完

```python
def my_step(ctx: RunContext) -> ActionResult:
    # ① 看画面
    found = ctx.frame().find_image("jingji/skill.png", region=TEAM_ROI)
    if not found.ok:
        return found

    # ② 动手（动作在原子层，收 session 不收 ctx）
    actions.click_source_point(ctx.session, found.value)

    # ③ 点完画面变了 —— 必须作废帧，否则下一步看的是旧图
    ctx.invalidate_frame()
    return ActionResult.success(found.value)
```

三件事：**读画面** → **用 `ctx.session` 动手** → **作废帧**。

---

## 实例属性（`ctx.xxx`，不带括号）

| 成员 | 类型 | 是什么 | 什么时候用 |
|---|---|---|---|
| `ctx.session` | `Session` | L1 截图层 + 输入通道的**唯一句柄** | 调原子层动作时传它：`actions.click_source_point(ctx.session, p)` |
| `ctx.config` | `AppConfig` | 应用配置（窗口、分辨率、阈值、路径、后端） | 读阈值/路径；**别改它**（跑起来之后是共享的） |
| `ctx.blackboard` | `Blackboard` | **跑出来的**键值存储 | 步骤之间传数据（"这次读到的体力"） |
| `ctx.pages` | `PageTracker` | 状态跟踪器（连续几帧、换过几次） | 排查用；见下面的"跟踪器" |
| `ctx.executor` | `Executor \| None` | 步骤执行器 | 一般不用碰（引擎自己调） |
| `ctx.recorder` | `Any \| None` | 识图记录器 | **可能是 `None`**（没开记录时），用之前判空 |
| `ctx.frame_ttl` | `float` | 帧的新鲜度上限（秒） | 调"多久算过期" |
| `ctx.capture_count` | `int` | 这个上下文一共抓了几帧 | 排查"是不是反复抓屏" |

### 不在 `ctx` 上的两个，别找错地方

| 想干什么 | 去哪儿 |
|---|---|
| **空跑**（不真的下发输入） | `ctx.session.dry_run`（不是 `ctx.dry_run`） |
| **状态树** | 不在上下文里。状态层的归属是 `scenario.tree`，上下文只管"当前观测" |

> 为什么 `dry_run` 在 `session` 上：动作函数只拿得到 `session`、拿不到 `ctx`,
> 而"别真的动游戏"必须在**动作下发那一刻**拦住。

---

## 方法

### 运行参数（这次运行的**输入**）

| 方法 | 说明 |
|---|---|
| `ctx.param(name, default=None)` | 读一个运行参数。**跑的过程中不变**，`reset()` 也不清 |
| `ctx.params` | 全部参数的只读视图（`Mapping`） |
| `ctx.set_params(values)` | 覆盖参数。**装配期/开跑前**调；跑起来再改没意义 |

**参数 vs 黑板**（最容易混的一对）：

|  | 参数 | 黑板 |
|---|---|---|
| 什么时候有值 | **点开始之前**就定了 | 跑的过程中写出来 |
| 会变吗 | 不变 | 一直在变 |
| `reset()` | **不动它** | 清空 |
| 谁写 | 外面（表单 / `--param` / 测试） | 步骤自己 |
| 判断方法 | "用户还没点开始时它就有值了吗？" —— 有就是参数 | |

```python
def click_with_param(ctx):
    settle = ctx.param("jingji.settle", 1.0)   # 表单里可调
    ...
```

⚠️ **步骤里不要再写一遍默认值。** `FORM.fill()` 保证每个声明过的字段都有值，
默认值只有 `FORM` 一处出处 —— 两处迟早不一致。

---

### 画面

| 方法 | 说明 |
|---|---|
| `ctx.frame(region=None, *, fresh=False)` | 拿当前帧。**过期或 `fresh=True` 时自动重截** |
| `ctx.capture(region=None)` | **强制**截一张新帧并替换当前帧 |
| `ctx.current_frame` | 当前帧，**可能是过期的**（`None` = 还没截过） |
| `ctx.frame_age` | 当前帧的年龄（秒）；没帧时是 `inf` |
| `ctx.invalidate_frame()` | 标记当前帧作废 |

**`invalidate_frame()` 是最容易漏的一个。** 点完按钮 / 切了场景之后必须调，
否则下一步会拿**点击之前**那张图去判断，得出"还在原界面"的错误结论。

`builtins` 里的 `click_image` / `click_point` / `press` 已经替你调了 ——
所以**优先用它们**，别自己重写"找到 → 点 → 作废帧"（三个动作各错各的）。

```python
# 推荐：内置步骤已经处理好帧
from gamebot.execution.builtins import click_image
def click_skill(ctx):
    return click_image(ctx, "jingji/skill.png", region=TEAM_ROI)

# 自己写的时候，别忘了最后那句
def click_skill_manual(ctx):
    found = ctx.frame().find_image("jingji/skill.png", region=TEAM_ROI)
    if not found.ok:
        return found
    actions.click_source_point(ctx.session, found.value)
    ctx.invalidate_frame()          # ← 漏了这句就会看旧图
    return ActionResult.success(found.value)
```

---

### 便捷查询

| 方法 | 说明 |
|---|---|
| `ctx.query(query, *, fresh=False)` | 在当前帧上跑一个 `Query` |
| `ctx.find_image(template, region=None, confidence=None)` | 在当前帧上找一个模板图 |

这两个是 `ctx.frame().xxx` 的短写法，给 **hooks / 临时逻辑**用。
**步骤实现里请直接用原子层** —— 那样区域、阈值、命中后的动作都在眼前。

---

### 状态（"我现在认成了什么"）

| 方法 / 属性 | 说明 |
|---|---|
| `ctx.page_id` | 当前状态 id；认不出来时返回 `"unknown"` |
| `ctx.page` | 当前页面的**单帧观测**（`PageMatch \| None`） |
| `ctx.is_(page_id)` | 当前状态（或任一叠加层）是不是它 |

⚠️ **这三个只回答"画面被认成了什么"，不回答"我该在哪儿"。**
"该在哪儿"在**关联表**里（`scenario.bindings`）。想知道两者对不对得上，
问引擎的 `FlowEngine.check_state()` —— 别在步骤里自己比，
那会让"位置对不对"多出一个出处。

---

### 中止（停止按钮 / 超时）

| 方法 / 属性 | 说明 |
|---|---|
| `ctx.stop_requested` | 有没有人请求中止 |
| `ctx.stop_reason` | 中止原因（字符串） |
| `ctx.request_stop(reason="")` | 请求中止。**可从任意线程调** |
| `ctx.raise_if_stopped()` | 已请求中止就抛 `Cancelled` |

**`Cancelled` 不是"失败"**，它表示"别再继续了"，直接向上穿透。
这也是唯一该用异常的地方 —— 业务失败一律用**返回值**（`ActionResult`）。

**等待一律走 `ctx.sleep()`**，不要 `time.sleep()`：前者可被中止立刻唤醒，
后者点了停止还要等满这一觉。

```python
ctx.sleep(0.5)     # ✅ 点停止能立刻醒
time.sleep(0.5)    # ❌ 点停止要等它睡完
```

---

### 时间与路径

| 方法 | 说明 |
|---|---|
| `ctx.now()` | 单调时钟。**上下文里所有时间都走它**（方便注入假时钟） |
| `ctx.sleep(seconds)` | 可被中止打断的等待（转发给 `session.sleep`） |
| `ctx.screenshot_path(name, *, suffix=".png")` | 生成截图存档路径（目录自动创建） |
| `ctx.journal_path(name=None)` | 生成 journal 文件路径 |

⚠️ `screenshot_path` **不在留存清理范围内**（文件名不带 `fail_` / `match_`
前缀，两条清理规则都扫不到）。手工用可以，**别在循环里调它**，否则就是无限的图。
框架自己存失败帧走执行器，带前缀 + 有上限。

---

### 生命周期

| 方法 | 说明 |
|---|---|
| `ctx.reset()` | 清**运行期状态**，准备下一次运行。**不动参数** |
| `ctx.close()` | 关执行器 + 关 session |

`reset()` 清什么：跟踪器的当前状态与历史、黑板、中止标志、缓存的帧、
抓帧计数、执行器攒下的步骤结果。由 `FlowEngine.run()` 在开跑时调一次 ——
同一个引擎跑第二遍时，黑板不该带着上一遍的数据。

`RunContext` 是上下文管理器（`__enter__` / `__exit__`），`with` 用完自动 `close()`。

---

## `ctx.pages`（跟踪器）—— 排查用

步骤里一般不需要它，但想知道"这个状态连续几帧了""换过几次"就有用：

| 成员 | 说明 |
|---|---|
| `.current_id` | 当前状态 id |
| `.current` | 当前观测（`PageState \| None`）；**没定位过时是 `None`** |
| `.overlays` | 当前状态上的叠加层 |
| `.confirmed` | 是否已"确认进入"（连续命中帧数够了） |
| `.is_(page_id)` | 当前（含叠加层）是不是它 |
| `.is_current_exactly(page_id)` | **不含叠加层**的精确判断 |
| `.tick` | 第几轮 |
| `.changes` | 状态变更历史 |
| `.recent` | 最近的观测记录 |
| `.elapsed(now)` | 在这个状态上待了多久 |
| `.change_count(page_id)` | 这个状态换过几次 |
| `.to_dict()` | 全部导出（给报告 / 界面） |

---

## 没有的东西（故意的）

| 你可能想找 | 为什么没有 |
|---|---|
| `ctx.dry_run` | 在 `ctx.session.dry_run` 上（动作层要能直接看到） |
| `ctx.tree` | 状态树是 `scenario.tree`；上下文只管当前观测 |
| `ctx.binding` / `ctx.expected` | 关联表是流程层的东西，步骤不该知道自己是哪个状态 |
| `ctx.log(...)` / `ctx.log_click(...)` | **还没做** —— 见下面"已知缺口" |
| `ctx.click(...)` / `ctx.press(...)` | 动作在原子层，收 `session`；上下文不转发一遍 |

### 已知缺口

**`ctx.log(...)` 还没有。** 现在的记账是**执行器每步自动往 journal 写一行**
（`logs/journals/<脚本>.jsonl`），不是"你想记才记"。计划中的接口：

```python
ctx.log("技能按钮没找到")
ctx.log_click(found, template="jingji/skill.png")   # 带上图 / 坐标 / 分数
```

框架会自动带上 tick / 节点 / 当前状态 / 时间戳 —— 你只写"发生了什么"。

---

## 写步骤时的三条纪律

1. **失败用返回值，不用异常。** 返回 `ActionResult.not_found(...)` / `.error(...)`。
   上层会拿实测状态去**重定位**，而不是在原地重试 —— 所以步骤里**不要写重试循环**。
2. **不要在这里等待某个画面出现。** "等某张图出现"是**原子层**的能力
   （`wait_any_of` / `wait_disappear` / `wait_until` / `wait_stable`，
   都自带 `timeout` / `interval`）。步骤是"把原子方法串起来的大方法"。
3. **不要判断游戏状态。** `if ctx.page_id == "..."` 这种判断属于流程层
   （边条件 / 关联表）—— 步骤里写了，同一件事就有了两个出处。

---

## 相关文档

| 想知道什么 | 读 |
|---|---|
| 一个步骤长什么样、为什么是函数 | `src/gamebot/execution/step.py` 的模块 docstring |
| 内置步骤有哪些 | `src/gamebot/execution/builtins.py` |
| 原子层 50 个方法 | `docs/atomic-inventory.md` |
| 状态树和流程图怎么结合（关联表、重定位） | `docs/state-and-flow.md` |
| 业务层怎么写一个脚本 | `games/README.md` |
