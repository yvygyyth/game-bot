# 安装与启动

这份文档解决一件事：**从零把这套装起来、跑起来**。

第一次装完，日常只需要记住两条：

* **开界面** → 双击 `gamebot.exe`（或桌面快捷方式）
* **跑真机脚本** → `.\dev.ps1`（管理员开发终端），然后 `python -m games run ...`

---

## 0. 先读这一页里最重要的一段：UIPI

Windows 有一条硬规则（[UIPI](https://learn.microsoft.com/windows/win32/winmsg/window-features)）：

> **发送方进程的完整性级别必须 >= 目标窗口的级别。**

**名将杀在这台机器上是提权运行的**，所以：

| 你怎么启动 | 进程级别 | 结果 |
|---|---|---|
| 普通终端 / AI 工具自带的终端 | Low | ✗ |
| 双击 `.ps1` / VS Code 普通启动 | Medium | ✗ |
| **以管理员身份运行** | **High** | **✓** |

级别不够时，**一切都是静默失效的** —— 程序退出码 0、识别命中、动作层返回
`success`、journal 里也是 `success`，**只有游戏没反应**：

* 鼠标指针**会**移到正确位置（`SetCursorPos` **不受** UIPI 限制）；
* 点击**不生效**（`SendInput` 返回成功，消息被系统丢掉，没有任何错误）；
* 失焦后全局快捷键也收不到（低级键盘钩子收不到高权限窗口的按键）。

表现和"坐标算错了""模板裁错了"**一模一样**，所以极易查错方向
（这个项目在这上面绕了很久）。结论：

> **要碰真机输入（点击 / 按键），就必须以管理员身份运行。**
> 只改代码、跑单元测试**不需要**。

---

## 1. 依赖

### 1.1 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | **Windows**（`windows` 后端 / 界面 / UIPI 都是 Windows 概念） |
| Python | **>= 3.11**（`pyproject.toml` 里钉的） |
| 包管理器 | [uv](https://docs.astral.sh/uv/)（本项目的标准化方式） |
| 磁盘 | 界面 extras 约 150MB（PySide6），其余不大 |

### 1.2 怎么装

```powershell
# 装 uv（已有就跳过）
winget install --id astral-sh.uv

cd D:\WWW\python\game-bot

# 一条命令装齐：Windows 后端 + 界面 + 开发工具
uv sync --extra windows --extra ui
```

> ⚠️ **`--extra windows` 和 `--extra ui` 要一起给。**
> `uv sync` 会把**没在命令行里列出的 extra 卸掉** —— 只写一个另一个就没了，
> 而症状是"上次还好好的，这次界面起不来了"。

### 1.3 依赖分组（`pyproject.toml`）

**核心**（装了就够跑框架和无界面脚本）：

| 包 | 用途 |
|---|---|
| `numpy` / `opencv-python` | 模板匹配 |
| `mss` | 抓屏 |
| `Pillow` | 图像读写、截图存盘 |
| `PyYAML` | 框架自己的 `config/*.yaml` |
| `pynput` | 全局快捷键（**监听钩子，不占键**） |

**可选 extras**：

| extra | 内容 | 什么时候要 |
|---|---|---|
| `windows` | `pywin32`（窗口发现）、`pydirectinput`（注入鼠标键盘） | **本机必装** —— 不装的话"软件"下拉框是空的 |
| `ui` | `PySide6` | 要用图形界面 |
| `android` | `adbutils` | 跑安卓模拟器/真机 |
| `ocr-rapid` | `rapidocr-onnxruntime` | 要用 `find_text` / `read_text` / `read_number`（推荐，纯本地） |
| `ocr-tesseract` | `pytesseract` | 同上，但还要单独装 Tesseract 本体 |

**开发**（`[dependency-groups] dev`，`uv sync` 默认会装）：

`pytest` / `pytest-cov` / `ruff` / `mypy` / `types-PyYAML`

### 1.4 怎么确认装对了

```powershell
uv run python -c "import numpy, cv2, mss, PIL, yaml, pynput, win32gui, pydirectinput, PySide6; print('依赖齐了')"
```

---

## 2. 启动方式

### 2.1 图形界面（日常用这个）

**双击项目根目录的 `gamebot.exe`**（或桌面的 `gamebot 界面` 快捷方式）
→ 系统弹 UAC → 点"是" → 界面出来。

**没有黑窗口。** exe 是 PyInstaller 打的，里面嵌了两样东西：

* `--windowed` → **GUI 子系统**（不分配控制台窗口）；
* `--uac-admin` → **UAC 清单**（双击自动请求提权）。

所以一个文件就够了 —— 不需要 `.bat` / `.ps1` / `.vbs` 这些中间层。

> **为什么之前那些启动器都会闪黑窗口**：它们要靠 `powershell.exe` 或
> `cmd.exe` 启动，而那两个是**控制台子系统**的程序，一运行就分配控制台。
> `-WindowStyle Hidden` 发得太晚，盖不住那一瞬。
> （用 `uv run python logs/tools/check_subsystem.py` 能直接看到哪些 exe
> 是"控制台"子系统。）
>
> **这和 Qt 无关** —— Qt 是纯 GUI 库，用 GUI 子系统的解释器启动，
> 一个控制台都不会有。

#### 怎么重新打包

改了代码之后要重新打（exe 里带的是**代码**，不是模板）：

```powershell
uv run python packaging/build_exe.py --verify
```

产出 `dist/gamebot/gamebot.exe`，并在项目根放一份副本（双击那份用 ——
这样工作目录正好是项目根，配置里的相对路径都能找到）。

**模板、脚本定义、日志都不在 exe 里** —— 它们留在项目目录里，
改完立刻生效，**不用重新打包**。

#### 不带 exe 也能开

```powershell
uv run python -m gamebot ui --script mingjiangsha/jingji   # 预选脚本
uv run python -m gamebot ui --snapshot logs/ui.png         # 不开窗口，渲一张截图就退（自检用）
```

（这条要在**管理员终端**里跑，理由见上面 §0。）

日志写在 **`logs/ui.log`**（界面自己也有一份日志面板）。

### 2.2 开发（VS Code）

**推荐：以管理员身份启动 VS Code** —— 之后集成终端里跑什么都够权限。

不想提权 VS Code 的话，需要真机操作时用它：

```powershell
.\dev.ps1                                    # 管理员开发终端（venv 已激活，自动提权）
.\dev.ps1 -Command "python -m games doctor mingjiangsha/jingji"
.\dev.ps1 -Command "python -m games run mingjiangsha/jingji --max-ticks 20"
```

`dev.ps1` 做的事：检查级别 → 不够就弹 UAC 提权 → 把 `.venv\Scripts` 加进
`PATH` → 交互模式给一段常用命令，或直接执行 `-Command`。

---

## 3. 命令速查

### 3.1 `python -m games` —— 业务层（写脚本用这个）

```powershell
python -m games list                              # 有哪些脚本
python -m games describe mingjiangsha/jingji      # 打印状态树 + 流程图（不连游戏）
python -m games check    mingjiangsha/jingji      # 校验定义（改完定义先跑这个）

# ⚠️ 跑真机操作前先自检：权限级别 / 前台窗口 / 模板 / 抓屏
python -m games doctor   mingjiangsha/jingji

python -m games run      mingjiangsha/jingji --dry-run --max-ticks 5   # 空跑：只识别不动手
python -m games run      mingjiangsha/jingji                            # 真跑
python -m games poke     mingjiangsha/jingji 1365 585                   # 点一下并报告全过程
python -m games where    mingjiangsha/jingji 1365 585                   # 这个点在各坐标系里是多少
```

`games run` 常用参数：

| 参数 | 作用 |
|---|---|
| `--dry-run` | **只识别、不下发任何输入** —— 调脚本时的默认姿势 |
| `--max-ticks N` | 最多跑 N 轮 |
| `--max-runtime S` | 最多跑 S 秒 |
| `--node ID` | 从某个流程节点开始（调后期分支不用从头玩） |
| `--param rounds=5` | 传运行参数（入参），步骤用 `ctx.param("rounds")` 读 |
| `--window TITLE` | 覆盖窗口标题 |
| `--no-journal` | 不写 journal 文件 |

### 3.2 `gamebot` —— 框架 CLI（调框架本身用）

```powershell
gamebot info                  # 打印生效配置
gamebot check                 # 校验 config/app.yaml 里的示例流程与模板
gamebot windows               # 列出可见窗口（标题 + 客户区矩形）
gamebot capture -o a.png      # 截全屏
gamebot grab --region 100,100,400,300 -o b.png   # 截指定区域
gamebot run --dry-run         # 跑框架示例流程
gamebot ui                    # 界面
```

> 这些命令调的是**框架**（`config/app.yaml` 里那份示例流程）。
> 真脚本走上面 §3.1 的 `python -m games ...`。
> `gamebot check` 会连**模板文件存不存在**一起校验 —— 模板还没裁完时会报缺失，
> 那是它该报的。

### 3.3 测试与静态检查

```powershell
uv run pytest tests/ -q          # 全部用例（不需要管理员）
uv run ruff check .              # 风格 / 未用导入 / 死名字
uv run mypy src games            # 类型
```

---

## 4. 装完之后的第一次运行

按这个顺序，每一步都能单独验证：

```powershell
# ① 依赖齐吗
uv run python -c "import win32gui, PySide6; print('ok')"

# ② 能看到游戏窗口吗（这一条不装 pywin32 会报错）
uv run python -m gamebot windows

# ③ 能抓屏吗
uv run python -m gamebot capture -o logs/first.png

# ④ 脚本定义对吗
uv run python -m games check mingjiangsha/jingji
```

然后**开管理员终端**（`.\dev.ps1`），把游戏摆到首页，再：

```powershell
python -m games doctor mingjiangsha/jingji    # 权限 / 前台 / 模板 / 抓屏，全绿才往下走
python -m games run mingjiangsha/jingji --dry-run --max-ticks 10
```

干跑没问题了再去掉 `--dry-run` 真跑。

---

## 5. 出问题先看这里

| 症状 | 多半是 | 怎么查 |
|---|---|---|
| **点击没反应、失焦热键也不灵** | **权限级别不够（UIPI）** | `python -m games doctor <脚本>`；看"权限（UIPI）"那一节 |
| "软件"下拉框是空的 | 没装 `pywin32` | `uv sync --extra windows --extra ui` |
| 界面起不来、`gamebot.exe` 被占用 | 界面还开着 | 关掉它再 `uv sync` |
| `ModuleNotFoundError` | extras 没装齐 | 见 §1.2 那条警告（两个 extra 要一起给） |
| 识别一直 `unknown` | 模板对不上 / 没站在预期界面 | 干跑看「识图日志」的带框图 + 分数 |
| `uv run` 报 Python 版本 | 系统 Python < 3.11 | uv 会自己下 Python，别用系统的 `python` 直接跑 |

### 权限那段到底在说什么

`python -m games doctor` 会打这样一段：

```
── 权限（UIPI） ────────────────────────────────
  本进程: Low
  目标窗口: Medium
  **权限不够，输入发不进游戏**：……
```

只要出现"权限不够"，**别去调坐标、别去重裁模板** —— 那些都是白费。
用管理员身份重开（双击 `gamebot.exe` —— 它内嵌的 UAC 清单会自己请求提权；或者走 `.\dev.ps1`）。

> 顺带一句：低权限进程读到的"目标窗口级别"**可能偏低**（Windows 会隐藏提权
> 进程的信息），所以"读出来相等"也不代表真的够。拿不准就直接管理员跑。

---

## 6. 目录约定（放到哪、日志在哪）

```
game-bot/
├── config/        框架级配置样板（app.yaml / regions.yaml）
├── src/gamebot/   框架：atomic / vision / state / flow / execution / ui / utils
├── games/         业务层：具体游戏的脚本
│   └── mingjiangsha/jingji/
│       ├── pages.py        状态树（认什么）
│       ├── bindings.py     状态 ↔ 流程节点 的关联表
│       ├── graph.py        流程图（怎么走）
│       ├── steps/          每个节点做什么
│       └── templates/      模板图 + rawMaterial/ 原始截图 + README.md 裁剪说明
├── logs/
│   ├── ui.log              界面日志（每次开界面都写）
│   ├── screenshots/        抓屏、带框的识图记录（默认留 200 张）
│   ├── journals/           每轮运行的结构化记录
│   └── tools/              一次性工具与排查脚本（见那里的 README.md）
├── docs/          架构与专题文档
├── dev.ps1        管理员开发终端
├── gamebot.exe    打包好的界面（双击这个；改了代码要重新打包）
└── packaging/     打包脚本（build_exe.py + 入口 entry.py）
```

---

## 7. 卸载 / 重装

```powershell
# 只清虚拟环境（不动源码和日志）
Remove-Item -Recurse -Force .venv
uv sync --extra windows --extra ui

# 彻底重来（连 uv 的缓存）
uv cache clean
```

模板、日志、脚本定义都在源码目录里，删 `.venv` 不会碰它们。
