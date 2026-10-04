# 页面树 与 流程图：怎么结合

## 一、为什么是两个对象，不是一个

游戏界面确实是分模块的，所以"我在哪"是棵树。但"接下来做什么"**不是**树 ——
它是一个带环的有向图。最典型的两条边，树里根本表达不了：

```
结算  ──确认按钮──▶ 首页        （跨分支跳回，树里没有这条边）
开始战斗 ──没体力──▶ 首页        （回到祖先的兄弟）
```

反过来，图也拿不到树的收益：

* **逐层剪枝**：树能只试"当前路径上的兄弟"，图没有"层级"概念，每帧都得把所有
  页面的识别条件跑一遍；
* **ROI 继承**：「战斗」的 8 个子状态只需要看右下角技能栏那 680×500 就能区分，
  这个"只需要看一块"的来源是父节点，图里无处安放；
* **消歧**：同一个"确认"图标在"战斗中"和"设置页"下含义不同，
  得靠父节点上下文才能区分。

所以：**树管空间，图管时间。** 合并成一个对象一定会丢掉其中一边的能力。

## 二、唯一的接口：`Node.page`

```python
@dataclass(slots=True)
class Node:
    id: NodeId
    steps: list[Step] = ...        # 这个节点做什么
    page: PageId | None = None     # ★ 我该在哪个页面上
```

这是两个对象之间**唯一**的耦合点。有了它，引擎每一轮可以这样走：

```
① frame = ctx.frame()
② match = tree.locate(frame, hint=上一轮的页面)     # 空间：我在哪
③ if match.id != cursor.current_node.page:          # 时间：对得上吗
       ⚠ 记一条警告，本轮一个动作都不做             #   **只拦不跳**
④ if cursor.should_run(ctx):                        # 位置对 + 未确认 + 冷却已过
       executor.run_many(node.steps)                #   干活
⑤ cursor.step(ctx)                                  # 时间：条件满足就换目标
```

第 ③ 步是这套设计**最重要的安全属性**：**实际页面 ≠ 节点期望的页面时，
一步动作都不做。** 识图脚本最危险的失败模式就是在错误页面上瞎点 ——
点错一个"确认"可能就是消耗道具或者进错关卡。用一句比较就把这类事故挡掉了。

### 为什么"只拦不跳"（这个岔路已经定了）

早期版本的第 ③ 步还有一个动作：不一致时**自动跳到**认领该页面的节点
（`graph.node_for_page(match.id)`）。现在去掉了，跳转必须由图里的边显式表达。

| | 自动跳 | **只拦不跳（现在的选择）** |
|---|---|---|
| 忘写边 | 也能跑（靠隐式规则） | 原地不动 + 一条警告 |
| "为什么它动了" | 在引擎的隐式规则里 | **永远能在图里找到答案** |
| 那次移动进 `RunReport.decisions` 吗 | 不进（隐形） | **进** |

代价是忘写边就跑不动 —— 但"不动"是**有解释的**：引擎会记一条警告，
而且同一组（节点，页面）只记一次，不会刷屏。相比之下，自动跳的代价更隐蔽：
它让一次控制流转移在报告里隐形，排查"它怎么跑那儿去了"时只能靠猜。

控制流只有一个出处，值这个代价。

> 想从中间某个节点开始调试时也一样：可以用 `FlowEngine(start_node=...)`
> 指定起点，但那**不解除位置守卫** —— 起点声明的 `page` 和实测不符时，
> 动作照样一个都不执行。起点决定"从哪开始试"，守卫决定"能不能动手"。

## 三、三种结合模式

| | 谁做主 | 适用 | 代价 |
|---|---|---|---|
| **模式 1（推荐）** | 两边分工：树定位、图决定 | 绝大多数情况 | 需要给每个 `Node` 填 `page` |
| **模式 2** | 树做主，图是附属 | 每个页面只做一件事的简单游戏 | 表达不了"同页面多阶段" |
| **模式 3** | 图做主，树只喂数据 | 逻辑高度自定义 | 退化成大片 `if ctx.page.id == ...` |

### 模式 1：树定位 + 图决定（推荐）

节点声明自己属于哪个页面，边用 `Query` 当条件。**没有任何一处需要手写页面判断**。

```python
tree = PageTree()
tree.add(Page("home", queries=(ImageQuery("home/logo.png"),)))
tree.add(Page("home/qianli", queries=(ImageQuery("qianli/entry.png"),)), parent="home")
tree.add(Page("home/qianli/battle", queries=(ImageQuery("battle/skillbar.png"),)), parent="home/qianli")
tree.add(Page("home/qianli/battle/result", queries=(ImageQuery("result/victory.png"),)),
         parent="home/qianli/battle")

g = Graph(initial="home")
g.add_node(Node("home", page="home", steps=[ClickImageStep("qianli/entry.png")]))
g.add_node(Node("battle", page="home/qianli/battle", steps=[ClickImageStep("battle/skill.png")]))
g.add_node(Node("result", page="home/qianli/battle/result", steps=[ClickImageStep("result/confirm.png")]))

g.connect("battle", "result", condition=ImageQuery("result/victory.png"), priority=30)
g.connect("result", "home",   condition=ImageQuery("home/logo.png"),     priority=20)
g.connect("home",   "battle", priority=10)
```

注意 `battle` 节点**没有任何边也是正常的** —— 打完之前它就该一直待在那里反复点技能，
这就是 `next_node` 返回 `None` 的含义（原地不动，不是失败）。

### 模式 2：页面驱动

每页一个处理节点，`Graph.node_for_page()` 直接查表。
适合"首页就点开始、战斗页就点技能"这种一对一的情况。
一旦出现"同一个页面第一次要领奖励、之后直接开打"，就得给它加边 —— 那时它已经变成模式 1 了。

### 模式 3：图做主

条件里直接读 `ctx.page.id`。最灵活，但页面知识散进条件里，
`regions.yaml` 和模板路径也跟着散掉，`gamebot check` 就没法静态校验了。
**只在前两种表达不了时才用。**

## 四、页面树该长什么样

```yaml
pages:
  home:
    name: 首页
    queries:
      - {type: ImageQuery, template: home/logo.png}
    children:
      qianli:
        name: 千里单骑
        queries:
          - {type: ImageQuery, template: qianli/entry.png}
        children:
          battle:
            name: 战斗
            roi: [1180, 620, 680, 500]    # 相对父页面：只看右下角
            queries: [...]
            children:
              ready:  {name: 开始战斗, queries: [...]}
              result: {name: 战斗结算, queries: [...]}

  # 全局叠加层：不属于任何父页面，出现在哪都能被识别到
  network_error:
    kind: overlay
    priority: 100
    queries:
      - {type: ImageQuery, template: common/network_error.png}
```

三点值得注意：

1. **`id` 由嵌套位置推导**成路径形式（`home/qianli/battle`），
   所以重命名一个父节点会自动改掉所有子节点的 id —— 改配置时留意。
2. **`kind: overlay` 才能和父页面共存**。默认是替换式：
   进了「结算」就不再是「战斗」。搞混会导致"结算画面出来了，但脚本还认为在战斗中"。
3. **全局叠加层挂在顶层**（`network_error` 不写在 `children` 里），
   因为它不属于任何页面。

## 五、还没定的两件事

1. **`query_from_dict` / `step_from_dict`** —— 让 YAML 真正驱动流程的那两块拼图。
   查询注册表（`query_registry()`）和步骤注册表（`step_registry()`）都已经就绪，
   实现是"查表 + 递归构造 + 处理 policy 子字典"。补上之后 `gamebot check`
   就能真正校验配置了。
2. **`PageTree.locate()` 的定位算法**。算法已经写进它的 docstring（6 步），
   要拍板的是细节：hint 只影响尝试顺序这一点是否照做、叠加层扫到几层。

## 六、已经定下来的事

* **搭桥层放在 `FlowEngine.tick()` 里**（暂时）。上面 ③④⑤ 步就是 `tick()` 的骨架，
  已经写成了带完整注释的桩。以后如果它长到难以阅读，再抽 `flow/runner.py`。
* **`RunContext.page` 已经有了**（属性，返回 `PageMatch | None`，从跟踪器读）。
  所以 `Node.page` 的位置守卫是**生效**的，不是可选项：
  `GraphCursor.should_run()` 会拿实测页面和节点声明的页面比，不一致就拒绝执行。
* **旧的扁平实现已经删干净了**：`state/definition.py`、`state/detector.py`、
  `state/snapshot.py`、`flow/node.py`、`flow/transition.py`、`flow/machine.py`、
  `flow/definition.py` 全部移除，不向后兼容。现在的状态层是
  `page.py`（单帧定位）+ `tracker.py`（跨帧持续性）+ `store.py`（黑板），
  流程层是 `graph.py`（图）+ `scenario.py`（蓝图）+ `engine.py`（主循环）。

## 七、加一个页面时要动的地方

1. `config/flows/*.yaml` 的 `pages:` 里加节点（嵌套位置就是 id）；
2. 如果这个页面需要动作，在 `nodes:` 里加一个节点并写上 `page:`；
3. 加边决定什么时候进、什么时候走。

**页面的 id 是路径形式**（`home/qianli/battle`），所以改父节点的 key
会连带改掉所有子节点的 id —— 那时 `nodes[].page` 也得跟着改。
`Scenario.validate()` 会检查这件事，写错会在启动时报错而不是静默不动作。

