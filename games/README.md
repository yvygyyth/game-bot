# 业务层：怎么写一个脚本

`src/gamebot/` 是**框架**，它不认识任何具体游戏。这里才是认识游戏的地方。

## 布局：一级游戏、二级功能

```
games/
└── <游戏>/                        一级：一个游戏一个目录（容器）
    ├── __init__.py               游戏级导出
    ├── game.py                   游戏级定义：窗口、锁定分辨率、公共配置
    ├── pages.py                  游戏级公共页面（首页、各类弹窗）
    ├── shortcuts.py              游戏级快捷方法（关弹窗、回主界面）
    ├── templates/                游戏级公共模板
    └── <功能>/                    二级：一个脚本功能一个目录
        ├── __init__.py            ★ build_config() + build_scenario()
        ├── pages.py               这个功能的页面（状态对象）
        ├── graph.py               这个功能的流程（节点 + 边）
        ├── steps.py               这个功能专用的步骤
        ├── shortcuts.py           这个功能专用的快捷方法
        ├── checks.py              ★ 只声明 ChecksSpec（检查逻辑在框架里）
        ├── templates/             这个功能的图片资源
        └── README.md              这个脚本怎么调
```

**脚本永远在功能目录里。** 游戏目录是容器，不直接放脚本 ——
放进去的话注册表扫不到，表现是"脚本没出现在列表里"，很难查。
真这么写了会明确报错并告诉你该放哪儿。

一级按游戏、二级按功能的理由：

* **游戏级**放"所有脚本都要用"的东西 —— 窗口标题、分辨率、公共弹窗。
  改一次全体受益，不用在每个脚本里重复；
* **功能级**放"只跟这个玩法有关"的东西 —— 页面、流程、专用图、专用步骤。
  一个功能改坏了不影响别的。

**游戏级也不必凑齐所有文件。** 要不要建 `pages.py` / `shortcuts.py`，
取决于这个游戏是不是真有多个脚本要共用同一批页面 —— 不是取决于格式对不对称。
只有一个脚本的游戏，那些文件就该空着。

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
python -m games list                          # 有哪些脚本
python -m games describe mingjiangsha/jingji  # 页面树 + 流程图长什么样
python -m games check    mingjiangsha/jingji  # 定义对不对、缺哪些图
python -m games setup    mingjiangsha/jingji  # 生成 / 下载资源（幂等）
python -m games selftest mingjiangsha/jingji  # 跑脚本自带的自检（静态）
python -m games probe    mingjiangsha/jingji  # 真机探针：现在屏幕上认不认得出来
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

`selftest` 和 `probe` 查的是两件不同的事，别混：

* **`selftest`** —— 静态：这份定义成不成立？模板裁得对不对？页面之间分得开吗？
  不需要游戏在跑。**"认得出但认错了地方"只有它能查出来。**
* **`probe`** —— 真机：此刻屏幕上认不认得出来？要游戏开着、并在预期的页面上。

### `checks.py` 只写数据，逻辑在框架里

**不要**在 `checks.py` 里实现检查逻辑。框架提供
[`gamebot.vision.checks`](../../src/gamebot/vision/checks.py)，你只声明
一个 `ChecksSpec`：

```python
from gamebot.types import Point, Region
from gamebot.vision.checks import ChecksSpec, EntryGroup, EntrySpec, SequenceSpec

CHECKS = ChecksSpec(
    title="竞技场",
    # 每个"要认出来的东西"：模板 + 它该命中的位置 + 搜索范围
    entries=(
        EntrySpec(
            template=T_ENTRY,
            point=ENTRY_CENTER,          # 期望命中点
            confidence=0.85,
            tolerance=15,                # 允许偏多少像素
            roi=ENTRY_ROI,
            hover=Point(27, -41),        # 悬停会位移多少 → 自动查 ROI 余量够不够
            origin="home.png",           # 从哪张资产图裁的 → 自动查"裁歪没有"
            label="竞技入口",
        ),
    ),
    # 真机探针按"组"报：一组 = 一个界面的标识
    groups=(
        EntryGroup(name="首页", entries=(...)),
        EntryGroup(name="队伍", required=False, entries=(...)),  # 只报告，不判成败
    ),
    # 顺序探测：按顺序找，第一个过阈值的必须正好是该点的那个
    sequences=(
        SequenceSpec(
            templates=(T_CREATE_TEAM, T_ADD_PET, T_START_MATCH),
            names=("创建队伍", "添加伙伴", "开始匹配"),
            roi=TEAM_ROI,
            confidence=0.85,
            expected={"jingji.png": T_CREATE_TEAM, "add-pet.png": T_ADD_PET},
        ),
    ),
    states=("jingji.png", "add-pet.png", "start.png"),   # 资产图（真机截图）
    assets_dir=Path(__file__).parent / "assets",
    fixture_path=PROJECT_ROOT / FIXTURES_DIR / "home.png",
    fixture_group="首页",        # 参考图抓的是首页，只要求认出这一组
)


def run(config) -> list[str]:        # ← __init__.py 的 selftest() 接这个
    return run_checks(CHECKS, config)


def probe_live(config) -> list[str]:  # ← __init__.py 的 probe() 接这个
    return run_probe(CHECKS, config)
```

**为什么不让每个脚本自己写检查逻辑**：那样每个脚本都会把同一套算法重写一遍，
而且**语义会漂**——A 脚本把 `tolerance` 当半径、B 脚本当边长，两边还都"能跑"。
现在算法只有一份，修一次所有脚本受益。

几个字段值得单独记住：

| 字段 | 它防的是什么 |
|---|---|
| `hover` | 元素**悬停时会位移**（名将杀首页卡片弹 `(+27,-41)`）。ROI 留小了，鼠标一划过就滑出 ROI、匹配不到 —— **静态看代码完全看不出来** |
| `origin` | 模板**裁歪了几像素**。在自己那张资产图上拿不到满分就会被报出来 |
| `expected` | **按钮顺序**。有些按钮天生会在别的状态上拿高分（名将杀的「开始匹配」三种状态下都是 0.999），所以验的不是分数差，而是"第一个过阈值的正好是该点的那个" |
| `required=False` | 那一组**只报告不判成败**（队伍那三个按钮是用来诊断走到哪一步的） |

`states` / `assets_dir` 指向**真机截图**，它们不入库 —— 没有就自动跳过回归，
不会让自检失败。

**别在 `checks.py` 里重复通用的检查。** "模板文件在不在""定义自不自洽"归
`games check`（框架的一份实现，所有脚本共用）。在脚本里再写一遍等于同一件事
两个出处：改了框架那边这边不会跟着变，两边还会给出不一样的说法。

## 参考实现

[`mingjiangsha/jingji`](mingjiangsha/jingji/README.md)（名将杀 · 竞技场）是一份
完整的真机样板，里面记着几个用数据定下来的结论：

* 悬浮会改变元素的样子时，怎么判断该加模板还是该收窄 ROI；
* 页面标识该选什么、不该选什么（会变的数字、活的背景、随状态变的面板）；
* 阈值怎么定 —— 量正例下限和反例上限，取中间，而不是凭感觉给 0.9。

## 图片资源怎么放

每个功能有自己的模板根，**优先级高于游戏级**：

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

**加一个功能**：在 `games/<游戏>/` 下建一个新目录，复制 `mingjiangsha/jingji/` 的骨架（`__init__.py` + `pages.py` + `graph.py` + `steps.py`）。

**加一个游戏**：按上面的布局建 `games/<游戏>/`，改三样 ——
`SLUG` / `WINDOW_TITLE` / `SOURCE_SIZE`，然后是页面、模板、流程。
游戏级要放什么，取决于有没有多个脚本要共用（见前面那段）。

