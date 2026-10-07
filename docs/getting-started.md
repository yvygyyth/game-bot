# 安装与启动

**日常只有两件事：**

| 想干什么 | 做什么 |
|---|---|
| **开界面** | 双击项目根目录的 **`gamebot.exe`**（桌面也有快捷方式） |
| **改了代码** | 跑一次 `uv run python packaging/build_exe.py`，然后照常双击 |

改**模板 / 脚本定义**不用重新打包 —— 它们不在 exe 里。

第一次装（新机器）见下面 §1。

---

## 0. 为什么必须"以管理员身份运行"

游戏是**提权运行**的，而 Windows 的 UIPI 规定：

> **发送方进程的完整性级别必须 >= 目标窗口的级别。**

级别不够时**一切都是静默失效的** —— 程序退出码 0、识别命中、动作层返回
`success`、日志里也是 `success`，**只有游戏没反应**：

* 鼠标指针**会**移到正确位置；
* 点击**不生效**（消息被系统丢掉，没有任何错误）；
* 失焦后全局快捷键也收不到。

表现和"坐标算错了""模板裁错了"**一模一样**，所以极易查错方向。

**不用记这件事** —— `gamebot.exe` 里嵌了 UAC 清单，双击就会自动弹提权确认，
点"是"就行。只有走命令行（§2.2）才需要自己开管理员终端。

> 只改代码、跑单元测试**不需要管理员**。

---

## 1. 第一次装（新机器）

```powershell
# 装 uv（已有就跳过）
winget install --id astral-sh.uv

cd D:\WWW\python\game-bot
uv sync --extra windows --extra ui
uv run python packaging/build_exe.py
```

跑完就有 `gamebot.exe` 了。

> ⚠️ 两个 extra **要一起给**：`uv sync` 会把没列出的 extra 卸掉，
> 只写一个另一个就没了（症状是"上次还好用，这次界面起不来了"）。

### 装完怎么确认

```powershell
uv run python -m games check mingjiangsha/jingji     # 定义对不对
uv run python -m games doctor mingjiangsha/jingji    # 权限 / 前台 / 模板 / 抓屏
```

`doctor` 全绿就可以开跑了。

### 框架自带的 CLI（可选）

`gamebot` 是对**框架本身**的 CLI，调框架、看窗口、抓图时用：

```powershell
gamebot info                  # 打印生效配置
gamebot windows               # 列出可见窗口（标题 + 客户区矩形）
gamebot capture -o a.png      # 截全屏
```

> 它跑的是 `config/app.yaml` 里那份**示例流程**。真脚本走 `games`。

---

## 2. 日常怎么用

### 2.1 开界面

双击 **`gamebot.exe`** → UAC 点"是" → 界面出来。

### 2.2 命令行（调脚本用）

真机操作要在**管理员终端**里跑（`.\dev.ps1` 会自动提权并开一个）：

```powershell
.\dev.ps1

# 进去之后：
python -m games list                                     # 有哪些脚本
python -m games describe mingjiangsha/jingji             # 看状态树 + 流程图（不连游戏）
python -m games check    mingjiangsha/jingji             # 校验定义和模板
python -m games doctor   mingjiangsha/jingji             # 环境自检，跑之前先看这个
python -m games run      mingjiangsha/jingji --dry-run   # 空跑：只识别、不动手
python -m games run      mingjiangsha/jingji             # 真跑
```

`games` 一共就五个子命令：

| 命令 | 干什么 |
|---|---|
| `list` | 有哪些脚本 |
| `check <脚本>` | 校验定义和模板 |
| `describe <脚本>` | 打印状态树 + 流程图（不连游戏） |
| `doctor <脚本>` | **跑之前的环境自检**（权限 / 前台窗口 / 模板 / 抓屏） |
| `run <脚本>` | 真跑。`--dry-run` 只识别不动手，`--max-ticks N` 限轮数 |

`run` 还能传运行参数（不写就用脚本声明的默认值）：

```powershell
python -m games run mingjiangsha/jingji --param rounds=3
```

### 2.3 测试与检查

```powershell
uv run pytest tests/ -q      # 全部用例（不需要管理员）
uv run ruff check .          # 风格
uv run mypy src games        # 类型
```

---

## 3. 改了东西要做什么

| 改了什么 | 要做什么 |
|---|---|
| **代码**（`src/gamebot/`、`games/` 里的 `.py`） | 跑一次 `uv run python packaging/build_exe.py` |
| **模板图**（`games/*/templates/*.png`） | **什么都不用做**，直接双击 exe 用 |
| **脚本定义**（`pages.py` / `graph.py` / `bindings.py`） | 什么都不用做 |
| **配置**（`config/*.yaml`） | 什么都不用做 |

**为什么模板不用重打**：exe 里只有代码，模板和定义留在项目目录里，
启动时从磁盘读 —— 所以改完立刻生效。这也是刻意的：模板要反复重裁。

---

## 4. 出问题先看这里

| 症状 | 多半是 | 怎么查 |
|---|---|---|
| **点击没反应、失焦热键也不灵** | **权限不够（UIPI）** | `python -m games doctor <脚本>`；或看界面启动时弹的那个框 |
| 双击 exe 闪一下就没了 | 缺依赖 / 代码错 | 看 `logs/ui.log` |
| "软件"下拉框是空的 | 没装 `pywin32` | `uv sync --extra windows --extra ui`，然后重打包 |
| `ModuleNotFoundError` | extras 没装齐 | 见 §1 那条警告 |
| 识别一直 `unknown` | 模板对不上 / 没站在预期界面 | 空跑看「识图日志」的带框图 + 分数 |
| UAC 弹窗点了"否" | 界面起不来 | 再双击一次，这次点"是" |

### 目录在哪

```
game-bot/
├── gamebot.exe      ← 双击这个
├── dev.ps1          ← 管理员开发终端
├── packaging/       ← 打包脚本（build_exe.py）
├── config/          ← 框架配置样板
├── src/gamebot/     ← 框架代码
├── games/           ← 脚本和模板（改这些不用重打包）
├── logs/
│   ├── ui.log          界面日志
│   ├── screenshots/    抓屏 + 带框的识图记录
│   └── journals/       每轮运行记录
└── docs/            ← 文档
```
