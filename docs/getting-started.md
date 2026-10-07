# 安装与启动

## 启动（一条命令）

```powershell
uv run python -m gamebot ui
```

界面就出来了。**改代码立刻生效**，不用重新打包。

日志在 `logs/ui.log`。

---

## 什么时候需要"以管理员身份运行"

上面那条命令**普通权限就能跑**，可以直接调脚本、空跑、看识图日志。

但**要让点击和全局快捷键真的对游戏生效**，进程级别必须够 —— 原因见下面 §1。

| 你要干的事 | 要不要管理员 |
|---|---|
| 改代码、跑 `pytest`、`games check` / `describe` | 不用 |
| 干跑看识别结果（`games run --dry-run`） | 不用 |
| **真跑（会点游戏）** | **要** |
| 失焦后按 F5 / F9 / F1 | 要 |

要的时候，开一个**管理员终端**再跑同一条命令：

```powershell
.\dev.ps1                      # 自动提权 + venv 已激活，然后照常敲上面那条
```

> 界面上如果出现"权限不够"的弹框，就是这件事 —— 关掉重开即可。
> 弹框只在**真的不够**时出现，不会打扰你。

---

## 1. 为什么需要管理员：UIPI

游戏是**提权运行**的，而 Windows 的 UIPI 规定：

> **发送方进程的完整性级别必须 >= 目标窗口的级别。**

级别不够时**一切都是静默失效的** —— 程序退出码 0、识别命中、动作层返回
`success`、日志里也是 `success`，**只有游戏没反应**：

* 鼠标指针**会**移到正确位置；
* 点击**不生效**（消息被系统丢掉，没有任何错误）；
* 失焦后全局快捷键也收不到。

表现和"坐标算错了""模板裁错了"**一模一样**，所以极易查错方向。

**这就是为什么界面会弹那个框** —— 它在开跑之前把原因说清楚，
而不是让你去调坐标、重裁模板。

---

## 2. 第一次装（新机器）

```powershell
# 装 uv（已有就跳过）
winget install --id astral-sh.uv

cd D:\WWW\python\game-bot
uv sync --extra windows --extra ui
```

> ⚠️ 两个 extra **要一起给**：`uv sync` 会把没列出的 extra 卸掉，
> 只写一个另一个就没了（症状是"上次还好用，这次界面起不来了"）。

### 装完怎么确认

```powershell
uv run python -m games check mingjiangsha/jingji     # 定义对不对
uv run python -m games doctor mingjiangsha/jingji    # 权限 / 前台 / 模板 / 抓屏
```

`doctor` 全绿就可以开跑了。

---

## 3. 常用命令

```powershell
# 界面
uv run python -m gamebot ui
uv run python -m gamebot ui --script mingjiangsha/jingji   # 预选脚本
uv run python -m gamebot ui --snapshot logs/ui.png         # 不开窗口，渲张截图就退

# 脚本（这五个够用了）
uv run python -m games list                              # 有哪些脚本
uv run python -m games describe mingjiangsha/jingji      # 看状态树 + 流程图（不连游戏）
uv run python -m games check    mingjiangsha/jingji      # 校验定义和模板
uv run python -m games doctor   mingjiangsha/jingji      # 环境自检，跑真机之前先看
uv run python -m games run      mingjiangsha/jingji --dry-run   # 空跑：只识别、不动手
uv run python -m games run      mingjiangsha/jingji              # 真跑

# 测试与静态检查
uv run pytest tests/ -q      # 全部用例（不需要管理员）
uv run ruff check .          # 风格
uv run mypy src games        # 类型
```

`run` 的两个参数：

| 参数 | 作用 |
|---|---|
| `--dry-run` | 只识别、不下发任何输入 —— 调脚本时的默认姿势 |
| `--max-ticks N` | 最多跑 N 轮 |
| `--param rounds=3` | 传运行参数（不写就用脚本声明的默认值） |

框架自带的 CLI（调框架、看窗口、抓图）：

```powershell
uv run python -m gamebot info         # 打印生效配置
uv run python -m gamebot windows      # 列出可见窗口（标题 + 客户区矩形）
uv run python -m gamebot capture -o a.png   # 截全屏
```

---

## 4. 打包成 exe（可选）

**这是打包产物，不是启动方式。** 只有想双击就开、或者发给别人用的时候才要：

```powershell
uv run python packaging/build_exe.py
```

产出 `dist/gamebot/gamebot.exe`，并在项目根放一份副本。
双击它会弹 UAC（exe 里嵌了提权清单），点"是"就开。

**改了代码要重跑这条命令**（exe 里带的是代码）。
日常开发**别用它** —— 源码那条命令改完立刻生效。

---

## 5. 出问题先看这里

| 症状 | 多半是 | 怎么查 |
|---|---|---|
| **点击没反应、失焦热键也不灵** | **权限不够（UIPI）** | `.\dev.ps1` 里重开；或 `uv run python -m games doctor <脚本>` |
| 界面起不来 | 缺依赖 / 代码错 | 看 `logs/ui.log` |
| "软件"下拉框是空的 | 没装 `pywin32` | `uv sync --extra windows --extra ui` |
| `ModuleNotFoundError` | extras 没装齐 | 见 §2 那条警告 |
| 识别一直 `unknown` | 模板对不上 / 没站在预期界面 | 空跑看「识图日志」的带框图 + 分数 |

### 目录在哪

```
game-bot/
├── dev.ps1          ← 需要管理员时用它（自动提权）
├── packaging/       ← 打包脚本（可选）
├── config/          ← 框架配置样板
├── src/gamebot/     ← 框架代码
├── games/           ← 脚本和模板
├── logs/
│   ├── ui.log          界面日志
│   ├── screenshots/    抓屏 + 带框的识图记录
│   └── journals/       每轮运行记录
└── docs/            ← 文档
```
