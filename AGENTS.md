# 给新会话 / 新协作者的入口

这份文件是**路由器**，不是说明书。它的作用是让一个全新的会话（上下文为空）
在几分钟内知道：项目是什么、命令怎么跑、规矩是什么、现在卡在哪。
细节都在 `docs/` 和各目录的 `README.md` 里，这里不重复。

## 这是什么

传统识图游戏脚本框架。分层：**流程层 → 状态层 → 执行层 → 原子层 → 类型层**，
依赖只允许向下（`tests/test_structure.py` 用 AST 强制）。
`src/gamebot/` 是框架（不认识任何具体游戏）；
`games/` 是业务层（一级游戏、二级功能），目前只有 `mingjiangsha/jingji`（名将杀 · 竞技场）。

## 命令

```bash
uv sync --extra windows --extra ui    # 装依赖（windows 后端 + 界面）
uv run ruff check .                   # 必须全绿
uv run pytest                         # 必须全过

uv run gamebot windows                # 列出可见窗口（填 window_title 用）
uv run gamebot capture -o a.png       # 截一张（验证坐标和后端）
uv run gamebot ui                     # 打开本地控制台

python -m games list                          # 有哪些脚本
python -m games check    mingjiangsha/jingji  # 定义对不对、缺哪些图
python -m games selftest mingjiangsha/jingji  # 静态自检
python -m games probe    mingjiangsha/jingji  # 真机探针（要游戏开着）
```

## 先读哪几份

| 想知道什么 | 读 |
|---|---|
| 当前进度、下一步清单 | `README.md` 的"进度"和"下一步" |
| 为什么这么分层、有哪些关键决策 | `docs/architecture.md` |
| 页面树和流程图怎么结合 | `docs/state-and-flow.md` |
| 业务层怎么写一个脚本 | `games/README.md` |
| **真机识图怎么调**（阈值、悬浮态、ROI） | `games/mingjiangsha/jingji/README.md` |
| 界面设计 + 做完之后踩的坑 | `docs/ui.md` |
| 50 个原子方法的契约 | `docs/atomic-inventory.md` |

## 现在能跑什么、卡在哪

**能跑**：截图、窗口枚举、坐标换算、模板匹配、原子层 L0~L5、
页面树/流程图/游标/校验、业务层注册表与自检、界面阶段 1、真机探针。

**还是桩**（这是唯一的缺口，`grep -rn NotImplementedError src/` 可看全）：

| 桩 | 影响 |
|---|---|
| `PageTree.locate()` | 认不出"现在在哪一页"—— 算法已写在它的 docstring 里 |
| `FlowEngine.tick()` / `_run_node()` | 没有任何一轮会执行 |
| `Executor.run` + 9 个 `Step.run()` | 动作下发不了 |
| `flow/loader.py` 的 parse*、`query_from_dict`、`PageTree.from_nested` | YAML 驱动用不了（现在只能手写 Python） |
| `execution/journal.py` 的 record* | 可观测性 |

**补上 `locate()` + `tick()` + `Executor.run`，`gamebot run` 就能真的走完流程。**

## 容易违反的几条规矩

1. **失败用返回值，不用异常。** 原子层/执行层返回 `ActionResult`；
   异常只留给装配期错误。唯一例外是 `Cancelled`（表示"别再继续了"，不是"失败了"）。
2. **坐标只有两个基准，别混。** `Frame` 收的 region 是**源坐标**（客户区相对，
   内部会减 origin）；`find_all_images` 返回的也是源坐标。
   拿源坐标去调收逻辑坐标的 `click_point` 会二次换算点偏 ——
   要用 `click_source_point`。
3. **真实输入必须加捕获区原点。** `WindowsInputBackend` 靠
   `offset_provider=screen.source_region` 拿到窗口位置再加。曾经漏过这一步，
   每次点击偏一个窗口位置，而大目标看不出来 —— 有 8 个用例钉着。
4. **位置守卫不解除。** 实测页面 ≠ 节点声明的 `page` 时**一个动作都不做**，
   而且**只拦不跳**（跳转必须由图里的边表达）。见 `docs/state-and-flow.md`。
5. **ROI 有两个作用。** 除了快，更重要的是把"多分类"变成"二分类" ——
   收窄搜索范围往往比多做一个模板有效。见 `games/mingjiangsha/shortcuts.py`。
6. **注释和文档写"为什么"，用中文。** 尤其是"为什么不是那个更直觉的做法"——
   那些被实测否掉的猜测（JPEG、尺度、往返重采样）都记在文件里，别重复踩。
7. **桩要显式。** 未实现的方法用 `raise NotImplementedError("待实现：<算法>")`，
   把算法写进 docstring，而不是留个 `pass`。
8. **测试放在该放的地方。** 框架的单元测试在 `tests/`；
   业务层脚本的自检在自己的 `checks.py`（跑 `python -m games selftest <key>`）。

## 真机相关的注意事项

* 分辨率锁死：`games/mingjiangsha/game.py` 的 `SOURCE_SIZE = (1918, 1080)`（客户区）。
  换分辨率所有模板和坐标全部失效。
* 模板要选**不会变**的元素：别用带数字的（金币数）、带特效的、
  随状态变的面板、活的背景（名将杀的背景一直在飘）。
* 资产图（`games/mingjiangsha/jingji/assets/`，14MB）不入库；
  自检在没有它们时会跳过"资产图回归"那一项。
* **某些执行环境会拦掉鼠标注入**（连 `SetCursorPos` 都返回 0 且无错误码）。
  遇到就别怀疑代码，先用 `python -m games probe` 确认截屏是否正常 ——
  截屏通、输入被拦，就是环境问题。
