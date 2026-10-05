# 业务层：怎么写一个脚本

`src/gamebot/` 是**框架**，它不认识任何具体游戏。这里才是认识游戏的地方。

## 布局：一级游戏、二级功能

```
games/
└── <游戏>/                        一级：一个游戏一个目录
    ├── __init__.py               游戏级导出（可空）
    ├── game.py                   游戏级定义：窗口、锁定分辨率、公共配置
    ├── scene.py                  游戏级"事实来源"（沙盒那种合成屏幕；真游戏不用）
    ├── pages.py                  游戏级公共页面（首页、各类弹窗）—— 有多个脚本共用才需要
    ├── shortcuts.py              游戏级快捷方法（关弹窗、回主界面）—— 同上
    ├── templates/                游戏级公共模板
    └── <功能>/                    二级：一个脚本功能一个目录
        ├── __init__.py            ★ build_config() + build_scenario()
        ├── pages.py               这个功能的页面（状态对象）
        ├── graph.py               这个功能的流程（节点 + 边）
        ├── steps.py               这个功能专用的步骤
        ├── shortcuts.py           这个功能专用的快捷方法
        ├── checks.py              自检 / 真机探针实现
        ├── templates/             这个功能的图片资源
        └── README.md              这个脚本怎么调
```

**只有这一种布局**：游戏目录下面必须有功能目录。曾经支持过"游戏目录自己就是脚本"
（单脚本游戏），去掉了 —— 两种布局并存只有坏处：加第二个脚本时要挪目录，
而且"这个 `__init__.py` 到底是容器还是脚本"永远说不清。
现在在游戏目录下直接放 `build_scenario` 会**明确报错**并告诉你怎么挪。

一级按游戏、二级按功能的理由：

* **游戏级**放"所有脚本都要用"的东西 —— 窗口标题、分辨率、公共弹窗。
  改一次全体受益，不用在每个脚本里重复；
* **功能级**放"只跟这个玩法有关"的东西 —— 页面、流程、专用图、专用步骤。
  一个功能改坏了不影响别的。

**游戏级也不必凑齐所有文件。** 沙盒只有一个脚本，所以它没有游戏级 `pages.py` /
`shortcuts.py` —— 那些东西没有"多个脚本共用"的前提就不该存在。
要不要建，取决于这个游戏是不是真有共享内容，不取决于格式看起来对不对称。

## 唯一需要记住的规则

脚本包的 `__init__.py` 暴露两个函数，注册表就会**自动发现**它：

```python
def build_config() -> AppConfig: ...     # 这个脚本怎么跑（窗口、分辨率、模板根）
def build_scenario() -> Scenario: ...    # 这个脚本做什么（页面树 + 流程图 + 参数）
```

可选再加三样：

```python
TITLE = "千里单骑刷本"          # list 里显示的名字
DESCRIPTION = "自动刷本……"      # 一句话说明
def prepare() -> int: ...       # 生成/下载资源（图片），返回处理了几个文件
AUTO_PREPARE = True             # 允许 check 在资源缺失时自动跑 prepare()
def selftest() -> list[str]: ...  # 自检，返回失败说明（空 = 全过）
```

不需要维护手写的清单，也不会出现"新加了脚本但忘了登记"。

## 命令

```bash
python -m games list                      # 有哪些脚本
python -m games describe testgame/sandbox # 页面树 + 流程图长什么样
python -m games check    testgame/sandbox # 定义对不对、缺哪些图
python -m games setup    testgame/sandbox # 生成 / 下载资源（幂等）
python -m games selftest testgame/sandbox # 跑脚本自带的自检（静态）
python -m games probe    testgame/sandbox # 真机探针：现在屏幕上认不认得出来
```

`check` 是写脚本时最该反复跑的一条。它挡掉的是这几类问题：

| 错误 | 表现（如果没检查） |
|---|---|
| `Node.page` 写错一个字母 | 那条流程**永远不执行**，而且不报错 |
| 边的 source/target 拼错 | 同上 |
| 从 initial 走不到的节点 | 死代码，白写 |
| 模板文件忘了放 | 运行十分钟后才在某个分支报"找不到图" |
| 子页面的 roi 伸出父页面 | 那一页**永远定位不到** |
| 叠加层带了子页面 | 定位结果无法解释 |

## 两个参考实现，覆盖两种情形

| | 看它 |
|---|---|
| **不依赖真机**（合成屏幕、八项自检、ROI 累加怎么验） | [`testgame/sandbox`](testgame/sandbox/README.md) |
| **真机识图**（悬浮态怎么处理、阈值怎么定、真机探针怎么用） | [`mingjiangsha/jingji`](mingjiangsha/jingji/README.md) |

沙盒那套的价值在于"断网也能验"：

```bash
python -m games selftest testgame/sandbox
```

## 图片资源怎么放

多脚本游戏里，每个功能有自己的模板根，**优先级高于游戏级**：

```python
config.vision.templates_dir = "games/<游戏>/templates"                  # 游戏级公共
config.vision.extra_template_dirs = ("games/<游戏>/<功能>/templates",)  # 本功能
```

解析顺序是 **附加根 → 主根**，所以：

* 功能代码里写 `"battle/skill.png"` → 落到本功能目录；
* 写 `"common/network_error.png"` → 本功能目录没有，落到游戏级；
* 同名时会**覆盖**公共模板 —— 某个功能需要不一样的样式时不用把公共的挪走。

## 写脚本时值得遵守的几条

**页面 id 用路径形式**，靠 `parent=` 自动拼。改父节点的 key 会连带改掉所有
子节点的 id，那时 `nodes[].page` 也要跟着改 —— `check` 会抓到。

**弹窗必须标 `kind=PageKind.OVERLAY`。** 默认的 `PAGE` 是替换式语义
（进了子页面就不再是父页面）；弹窗是**叠加式** —— "在首页"和"有网络错误弹窗"
同时成立。搞混会导致"弹窗挡住了但脚本以为在首页继续点"。

**页面特征要选弹窗盖不到的地方。** 用整块面板当特征，弹窗一冒出来盖掉中间，
那一页就永远认不出来了。顶栏、底栏、角落是安全的选择。

**子页面的特征必须落在父页面的 roi 里。** roi 是**整棵子树**的搜索范围
（不只是这一页自己的）。要么把子页面挪成兄弟，要么把父页面的 roi 放大到
能覆盖它。`PageTree.validate()` 会拦下写错的。

**快捷方法只做一件事。** 多步策略属于流程层，不属于快捷方法。
判断标准：如果它内部需要"看情况决定下一步"，那它应该是个步骤或一条边。

**步骤负责采集事实，流程负责做决定。** 步骤把读到的数值写进黑板
（`ctx.blackboard.set`），边的条件去读它。这样"为什么走了这条分支"
永远能在流程图里找到答案，而不是藏在某个 `if` 里。

**用模板的步骤要覆写 `used_templates()`。** 否则 `check` 查不到它用的图，
缺图只能在跑的时候才发现。`FunctionStep` 包的是普通函数，没法自动推断，
所以要显式传：`FunctionStep(fn, templates=(T_A, T_B))`。

**只用界面上稳定的元素做模板。** 别用带数字的（血量、倒计时）、
带特效的（高亮、动画中间帧）—— 它们每天都长得不一样。

**给每个脚本写 `selftest()`。** 检查的应该是"这份定义本身对不对"
（图齐不齐、ROI 框得对不对、页面之间有没有区分度），
这些是 `check` 查不出来的，而它们恰好是最常见的失效原因。

## 加一个游戏 / 加一个功能

**加一个功能**：在 `games/<游戏>/` 下建一个新目录，复制 `testgame/sandbox/`
或 `mingjiangsha/jingji/` 的骨架（`__init__.py` + `pages.py` + `graph.py` + `steps.py`）。

**加一个游戏**：按上面的布局建 `games/<游戏>/`，改三样 ——
`SLUG` / `WINDOW_TITLE` / `SOURCE_SIZE`，然后是页面、模板、流程。
游戏级要放什么，取决于有没有多个脚本要共用（见前面那段）。

