# 给新会话 / 新协作者的入口

这份文件是**路由器**，不是说明书。它的作用是让一个全新的会话（上下文为空）
在几分钟内知道：项目是什么、命令怎么跑、规矩是什么、现在卡在哪。
细节都在 `docs/` 和各目录的 `README.md` 里，这里不重复。

## 这是什么

传统识图游戏脚本框架。分层：**流程层 → 状态层 → 执行层 → 原子层 → 类型层**，
依赖只允许向下（`tests/test_structure.py` 用 AST 强制）。
`src/gamebot/` 是框架（不认识任何具体游戏）；
`games/` 是业务层（一级游戏、二级功能），目前只有 `mingjiangsha/jingji`（名将杀 · 竞技场）。

**状态层和流程层之间只有一个桥**：`flow/binding.py` 的 `StateBinding`。
它管三件事 —— 动前校验、重定位去向、动后预期。两侧互不认识对方的语义，
这条纪律见 `docs/state-and-flow.md`。

## 命令

```bash
uv sync --extra windows --extra ui    # 装依赖（windows 后端 + 界面）
uv run ruff check .                   # 必须全绿
uv run pytest                         # 必须全过

uv run gamebot windows                # 列出可见窗口（填 window_title 用）
uv run gamebot capture -o a.png       # 截一张（验证坐标和后端）
uv run gamebot check                  # 校验配置 / 流程定义 / 模板文件
uv run gamebot ui                     # 打开本地控制台

python -m games list                          # 有哪些脚本
python -m games check    mingjiangsha/jingji  # 定义对不对、缺哪些图

# 真的跑起来（业务层脚本；gamebot run 跑的是 config/app.yaml 那个示例流程）
python -m games run mingjiangsha/jingji --dry-run --max-ticks 20
python -m games run mingjiangsha/jingji --max-runtime 300
```

## 先读哪几份

| 想知道什么 | 读 |
|---|---|
| 当前进度、下一步清单 | `README.md` 的"进度"和"下一步" |
| 为什么这么分层、有哪些关键决策 | `docs/architecture.md` |
| **状态树和流程图怎么结合**（关联表、两条定位路径、重定位） | `docs/state-and-flow.md` |
| 业务层怎么写一个脚本 | `games/README.md` |
| **真机识图怎么调**（阈值、悬浮态、ROI） | `games/mingjiangsha/jingji/README.md` |
| 界面设计 + 做完之后踩的坑 | `docs/ui.md` |
| 50 个原子方法的契约 | `docs/atomic-inventory.md` |

## 现在能跑什么、卡在哪

**能跑**：截图、窗口枚举、坐标换算、模板匹配、原子层 L0~L5、
状态树（`locate` 快路径 + `recover` 慢路径 + 分类节点 + 叠加层）、
流程图（图 / 游标 / 决策 / 校验）、**关联表**、`FlowEngine.tick` 的重定位语义、
执行层（10 个步骤 + 重试/跳过/超时 + journal JSONL）、YAML 驱动
（`query_from_dict` / `step_from_dict` / `parse_*`）、业务层注册表与
`run` / `check` / `describe`、
**本地控制台**（选软件 → 选游戏 → 选脚本 → 开始/停止，引擎跑在工作线程；
状态树/流程图**真画成图**并点亮当前状态与节点；识图日志 = 每次匹配的带框图 + 表格）、
**识图记录器**（`vision/recorder.py`：包住 Matcher/TextReader，
红框=命中 / 橙框=未命中 / 蓝框=搜索范围，一帧一张图、最多留 20 张）。

**框架侧没有桩了。** 唯一显式的桩是 `PageTree.from_nested`，它是**刻意**不实现的
（配置解析留在 `flow.loader.parse_pages`，这样状态层不必 import 流程层）。

**还差的**（都不是框架主干）：

| 缺什么 | 影响 |
|---|---|
| `events.py` + 每次运行独立日志 | 现在只有一个总日志文件；回放 / 更细的执行轨迹也等它 |
| 单步执行、断点 | 调"这一轮为什么这么决策"时有用，属锦上添花 |
| OCR 实测 | 两个实现已写，但没装依赖跑过 |
| 真机端到端 | 假后端下整条链已经通了；真机上还要验"照着眼看走完一局" |

## 容易违反的几条规矩

1. **失败用返回值，不用异常。** 原子层/执行层返回 `ActionResult`；
   异常只留给装配期错误。唯一例外是 `Cancelled`（表示"别再继续了"，不是"失败了"）。
2. **坐标只有两个基准，别混。** `Frame` 收的 region 是**源坐标**（客户区相对，
   内部会减 origin）；`find_all_images` 返回的也是源坐标。
   拿源坐标去调收逻辑坐标的 `click_point` 会二次换算点偏 ——
   要用 `click_source_point`。（`ClickStep` 收逻辑坐标，走 `click_logic_point`。）
3. **真实输入必须加捕获区原点。** `WindowsInputBackend` 靠
   `offset_provider=screen.source_region` 拿到窗口位置再加。曾经漏过这一步，
   每次点击偏一个窗口位置，而大目标看不出来 —— 有 8 个用例钉着。
4. **状态对不上时：本轮一个动作都不做，然后重定位。**
   已经不是"只拦不跳"了（那条旧规矩被推翻，理由见 `docs/state-and-flow.md` 第五节）：
   现在会拿真实锚点去关联表查出该去哪个节点、把游标挪过去，而**每次都记进
   `RunReport.recoveries`** —— 自动跳能被接受的唯一理由是它不隐形。
5. **父节点一律 `kind: group`（分类节点）。** 它自己不记录信息、不参与匹配，
   只提供 ROI 继承和组织结构。给它写 `queries` 或让它空着，校验都会报错。
   原因是实测踩过的坑：要求"父页面成立"会让「首页 → 竞技场 → 战斗」
   一进下一层就全部失效。
6. **每个记录信息的状态都必须有流程节点认领**（节点的 `page` 写它），
   否则 `Scenario.validate()` 直接 `ConfigError` —— 重定位到它之后无处可去。
   分类节点和叠加层没这个要求；**终态状态有**。
7. **ROI 有两个作用。** 除了快，更重要的是把"多分类"变成"二分类" ——
   收窄搜索范围往往比多做一个模板有效。见 `games/mingjiangsha/shortcuts.py`。
8. **注释和文档写"为什么"，用中文。** 尤其是"为什么不是那个更直觉的做法"——
   那些被实测否掉的猜测（JPEG、尺度、往返重采样）都记在文件里，别重复踩。
9. **桩要显式。** 未实现的方法用 `raise NotImplementedError("待实现：<算法>")`，
   把算法写进 docstring，而不是留个 `pass`。
10. **测试放在该放的地方。** 框架的单元测试在 `tests/`；
    业务层脚本没有自己的检查代码 —— 定义和模板由 `games check` 统一查。

## 真机相关的注意事项

* 分辨率锁死：`games/mingjiangsha/game.py` 的 `SOURCE_SIZE = (1918, 1080)`（客户区）。
  换分辨率所有模板和坐标全部失效。
* 模板要选**不会变**的元素：别用带数字的（金币数）、带特效的、
  随状态变的面板、活的背景（名将杀的背景一直在飘）。
* 模板放哪一层按**谁用**定：只有这个玩法用得到的放
  `games/<游戏>/<功能>/templates/`（优先级更高），多个脚本共用的才放
  `games/<游戏>/templates/`。分错了不会报错，只是以后加脚本时找不到图。
* **某些执行环境会拦掉鼠标注入**（连 `SetCursorPos` 都返回 0 且无错误码）。
  遇到就别怀疑代码：先 `gamebot capture -o a.png` 看截屏是否正常 ——
  截屏通、输入被拦，就是环境问题。
