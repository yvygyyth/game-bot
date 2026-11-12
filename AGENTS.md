# AGENTS.md —— 进这个仓库先读这一页

传统识图游戏脚本框架：**截图 → 找图 → 判断 → 点击**，不依赖任何 AI 模型。
业务目标是"写一个能跑的识图脚本"，框架存在的意义是让这件事可维护。

## 命令

```bash
uv sync --extra windows --extra ui          # 装依赖（两个 extra 要一起给）
uv run python -m gamebot                   # 唯一的命令：开界面（改代码立刻生效）
```

测试与静态检查（**提交前必须全绿**）：

```bash
uv run ruff check . && uv run mypy && uv run pytest
```

## 该读哪份文档

| 你要做什么 | 读 |
|---|---|
| 装依赖 / 启动 / 出问题 | [docs/getting-started.md](docs/getting-started.md) |
| **写一个脚本**（业务层全部约定） | [games/README.md](games/README.md) |
| 写一个步骤函数（`ctx` 上有什么） | [docs/run-context.md](docs/run-context.md) |
| 状态树怎么和流程图对上 | [docs/state-and-flow.md](docs/state-and-flow.md) |
| **跨运行记住东西**（背包 / 累计局数） | [docs/store.md](docs/store.md) |
| 分层理由 / 关键决策 | [docs/architecture.md](docs/architecture.md) |
| 界面怎么设计、线程模型 | [docs/ui.md](docs/ui.md) |
| 50 个原子方法清单 | [docs/atomic-inventory.md](docs/atomic-inventory.md) |

## 代码在哪

```
src/gamebot/            框架（不认识任何具体游戏）
├── atomic/             L0~L5：截图 / 查询 / 组合子 / 动作 / 平台后端
├── state/              状态树 + 跟踪层 + 黑板（这一局）+ 状态仓库（跨运行）
├── execution/          步骤 = 普通函数 + 执行器 + journal
├── flow/               图 + 游标 + 关联表 + 引擎主循环
├── events.py           结构化事件流（界面/复盘的数据源）
├── feature.py          业务声明 FeatureSpec（一个脚本一个 SPEC）
└── bootstrap.py        唯一装配入口：SPEC -> 全链路

games/<游戏>/scripts/<功能>/    业务（认识游戏的地方）
├── pages.py            状态（我认得出什么）
├── graph.py            流程（做什么、何时换）
├── bindings.py         状态 ↔ 节点
├── steps/              一个步骤一个文件
├── store/              一个仓库一个文件（跨运行的记忆）
├── form.py             运行参数（界面上的控件）
└── templates/          图片 + T_* 路径索引（权威出处）

games/<游戏>/templates/<家族>/     游戏级公共按钮花纹：一个文件夹一种（文字/尺寸版本）
games/<游戏>/utils/             游戏级快捷方法（按钮家族 click_* 方法）
```

**图片 / 状态 / 流程 / 入参 / 记忆 / 动作**分别住在上面几个地方，不要混着写。

模板查找顺序是**功能级优先、游戏级兜底**（同名图功能级覆盖游戏级）。

## 六条容易犯的错

1. **失败用返回值，不用异常**（`ActionResult`）；唯一的异常是 `Cancelled`（"停下来"）。
2. **同一 tick 内只许有一帧**：要新图用 `ctx.invalidate_frame()`，别自己截图。
3. **"下次开还该记得吗？"** 记得 → `ctx.store(...)`；不记得 → `ctx.blackboard`；
   用户填的 → `ctx.param(...)`。三者混用是这里最容易犯的错。
4. **节点不声明自己在哪个状态** —— 对应关系只在关联表里。
5. **模板路径写在 `templates/__init__.py` 的 `T_*` 里**，别在调用点裸写字符串
   （界面里选脚本时会逐张查缺图）。
6. **状态标识只用稳定的东西**：不要血条 / 倒计时 / 会动的背景 / 会被弹窗盖住的整块面板。

## 现状

- 框架四层、事件流、状态仓库都已实现；没有"忘了实现"的桩。
- 没做的：UI 还没消费事件流（仍用回调）、OCR 只接了装配没真机实测、
  真机端到端一轮还没跑过、`state/page.py` 等几个大文件待拆。
- 真机跑之前确认权限：界面会弹框；勾了「空跑」则不弹（它不发输入）。
