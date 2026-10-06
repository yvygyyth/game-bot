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
        ├── __init__.py            ★ SPEC = FeatureSpec(...) —— 这个脚本的声明
        ├── form.py                动态表单声明（FORM，没人调参数就不用写）
        ├── pages.py               状态（**一个文件就够**，再复杂也别拆）
        ├── graph.py               流程（同上）
        ├── steps/                 ★ 一个步骤一个文件
        ├── shortcuts.py           这个功能专用的快捷方法
        ├── templates/             这个功能的图片资源
        └── README.md              这个脚本怎么调
```

（**没有 `checks.py` 了** —— 早先每个脚本要抄一份自检代码，已经删掉，
见下面"查错"那一节。）

### 为什么 `pages` / `graph` 各一个文件，`steps` 却拆成包

不是随手定的，是"改的时候要跳几个文件"决定的：

| 文件 | 改它的时候 | 为什么这样放 |
|---|---|---|
| `pages.py` | 加一页、改一页的标识 | 状态之间**互相咬得很紧**（父子、ROI 继承、谁与谁能同时成立）—— 拆开就得来回跳 |
| `graph.py` | 加一个节点、连一条边 | 同上：边是两两关系，"这个节点有几个出口"必须一眼看全 |
| `steps/` | **改一个动作** | 一个步骤是自洽的：逻辑 + 它的模板 + 阈值 + 搜索范围。按步骤分文件，改一步只动一个文件 |

`steps/` 里每个文件包含**它那个步骤用到的一切**：

```python
# games/<游戏>/<功能>/steps/advance_team.py
T_CREATE_TEAM = "jingji/create_team.png"     # 这个步骤用的模板
TEAM_ROI = Region(1400, 630, 470, 360)       # 它的搜索范围
CONF_BUTTON = 0.85                           # 它的阈值

class CreateTeamStep(Step):                  # 它的逻辑
    ...
```

`steps/__init__.py` **只做转发**（`from .advance_team import CreateTeamStep`），
不要在那里写逻辑 —— 这样 `from .steps import CreateTeamStep` 照常能用，
而"这个步骤到底长什么样"永远在一个文件里看得完。

**页面标识放 `pages.py`，不要放 `steps/`。** `T_TITLE` 那种是页面身份，
不是某个动作的图；混进 steps 之后改页面标识就得在步骤里翻。

**步骤要用的模板/ROI/阈值，写在那一步的模块里；如果页面树也要用同一个值，
就在 `pages.py` 定义、步骤那边 import**（别两处各写一份 —— 改了页面 ROI
忘了改步骤，症状是"状态认出来了但按钮找不到"，很难查）。


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

脚本包的 `__init__.py` 导出**一个** `SPEC`，注册表就会**自动发现**它：

```python
# games/<游戏>/<功能>/__init__.py —— 这里**只有数据**，没有一行组装代码
from gamebot.feature import FeatureSpec
from .graph import SCENARIO

SPEC = FeatureSpec(
    name="mingjiangsha/qianli",              # "<游戏>/<功能>"，命令行和界面用它标识
    title="千里单骑刷本",                     # 给人看的名字
    slug="qianli",                           # 功能目录名（进 journal 文件名）
    description="自动刷本，连胜就继续",         # 可选
    templates_dir="games/mingjiangsha/qianli/templates",
    scenario=SCENARIO,                       # 状态树 + 流程图 + 引擎选项（见下）
    base_config=game.base_config,            # 游戏级基础配置（可调用对象）
    base_tree=game.new_tree,                 # 可选：游戏级公共页面
    form=FORM,                               # 可选：运行参数表单
)
```

`scenario` 是另一个纯数据对象：

```python
# games/<游戏>/<功能>/graph.py
from gamebot.scenario_spec import ScenarioSpec
from gamebot.flow import EngineOptions, Node

SCENARIO = ScenarioSpec(
    initial="home",                          # 必选：流程从哪开始
    tree=PageGroup(                          # 整棵状态树（嵌套）
        # **嵌套的树**：分类节点和状态节点是两种类型
        PageGroup("home", children=(
            PageLeaf("home/lobby", queries=(...)),        # 记录"我在首页"
            PageGroup("home/jingji", roi=..., children=(
                PageLeaf("home/jingji/before_create", queries=(...)),
            )),
        )),
    ),
    nodes=(
        Node("home", page="home/lobby", steps=[EnterJingjiStep()], cooldown=0.5),
        Node("create", page="home/jingji/before_create", steps=[CreateTeamStep()]),
    ),
    edges=(                                  # (source, target, Edge 的参数)
        ("home", "create", {"condition": on_page("home/jingji/before_create"), "priority": 10}),
    ),
    options=EngineOptions(tick_interval=0.4, max_runtime=180.0),
)
```

> **节点的 `page` 要写"真正记录信息的那个状态"**，不是分类容器。
> 上例里是 `home/lobby` 而不是 `home` —— 容器不记录信息，
> 把节点挂在它上面会被 `validate_binding` 拦住（那是对的）。

### 声明是数据，**组装是框架的事**

这一点是刻意的：建树、按顺序加节点、连边、跑完整校验 —— 这些**对每份声明都
一个样**。让每个功能各写一遍，等于把"会不会写错"复制到每个脚本里
（忘了 `add_node` 就连边，是运行期事故，而且报错点离写错的地方很远）。

框架在 `ScenarioSpec.materialize()` 里做，顺序有讲究：

1. 先建树（`pages` 父先子后，`add()` 才能算出路径 id 与 ROI 继承）；
2. 再加**全部**节点，**然后**才连边 —— 反过来的话"边指向还没加的节点"会变成假错误；
3. 连完边跑 `Scenario.validate()`：悬空引用、从 initial 走不到的节点、
   每个记录信息的状态有没有节点认领，一次全报出来。

所以你写声明时只需要回答"这个脚本**是什么**"，不用想"怎么把它拼成一个对象"。

### 为什么是"一个 typed 对象"

**字段全必选 + 类型明确 ⇒ 编辑器替你查错。** 这几种写法在写的时候就有反馈，
不用跑起来、也不用点一个"检查"按钮：

| 写错了什么 | mypy 报什么 |
|---|---|
| 漏掉 `templates_dir` | `Missing positional argument "templates_dir"` |
| 把 `form` 拼成 `from_` | `Unexpected keyword argument "from_" ... did you mean "form"?` |
| `templates_dir` 传了 `Path` 而不是 `str` | `Argument "templates_dir" ... has incompatible type "Path"; expected "str"` |
| `base_config` 传了**配置对象**而不是函数 | 运行期 `ConfigError`（这条类型上看不出来，所以构造期也查一遍） |

以前是散装几个名字（`TITLE` / `build_config` / `build_scenario`），框架靠
``getattr(module, "build_config", None)`` 去捞 —— 于是"必须有哪些、叫什么"
这条契约**只存在于框架的字符串里**，编辑器和类型检查都看不见。

### 有两处**必须**是函数，不是数据

| 字段 | 为什么是函数 |
|---|---|
| `base_config` | 里面含 `PROJECT_ROOT` 这类**环境推导值**（"怎么跑"），而且每次运行要一份新的 |
| `build_config` | 同上 —— 共享一个 `AppConfig` 会让一次运行改到的东西**泄漏到下一次** |

`build_config` 是可选的：模板根、名字、tick 间隔框架都会从声明里填好。
留这个口子是为了"这个脚本真要拧某个框架级旋钮"。

### 还需要导出的常量

`SPEC` 之外，`SLUG` / `TITLE` / `TEMPLATES_DIR` 这类模块级常量**照旧留着** ——
它们是给别处用的（比如 `shortcuts.py` 里拼模板路径），而 `SPEC` 是给**框架**用的
那份声明。两者不重复：`SPEC` 里的值就从这些常量取。

不需要维护手写的清单，也不会出现"新加了脚本但忘了登记"。**漏了 `SPEC`
会被明确报出来**（说清缺什么、约定在哪），而不是让脚本静默消失在列表里。

## 命令

**前面一定有 `uv run`** —— 它自动用 `.venv`。少写它就会用 PATH 里那个
`python`（本机 3.10.8，而项目要求 >=3.11），报错跟游戏脚本毫无关系。

```bash
uv run python -m games list                          # 有哪些脚本
uv run python -m games describe mingjiangsha/jingji  # 页面树 + 流程图长什么样
uv run python -m games check    mingjiangsha/jingji  # 定义对不对、缺哪些图
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

`selftest` / `probe` 这两样**已经删掉了**（连同框架里那套检查代码）。
现在查错只有两条路：

* **`games check`** —— 定义自不自洽、模板文件在不在。所有脚本共用同一份实现；
* **`games describe`** —— 状态树和流程图长什么样，人眼看。

早先每写一个脚本都要再抄一份"自检"（算 ROI 余量、跑顺序探测、验位置偏差），
后来发现那套逻辑每个脚本都一样、只有数值不同，而且**语义会漂** ——
所以连"让业务层声明数值"的中间方案也去掉了。

**识别准不准，靠真跑一次 + 看「识图日志」。** 界面上那页会把每次匹配的框画在
真机截图上（红=命中 / 橙=未命中 / 蓝=搜索范围）。单独"抓一帧试试"那条路也删了
—— 它跟真跑时的帧、ROI、帧新鲜度都不完全一样，看出来的结论会骗人。

## 运行参数（入参）

脚本经常会遇到"这次跑法不一样"：刷几局、打哪个副本、用哪套阈值。
这些值**不能写死在脚本里**，也不该让步骤在构造时焊死 —— 因为
`build_scenario()` 是静态的，它拿不到任何运行期信息。

所以框架给了运行参数，步骤用 `ctx.param(...)` 读：

```python
class FarmStep(Step):
    def run(self, ctx: RunContext) -> ActionResult[Any]:
        rounds = ctx.param("farm.rounds", 3)      # 给了默认值 = 可选参数
        limit = ctx.param("farm.timeout", 30.0)
        ...
```

命令行传：

```bash
uv run python -m games run <脚本> --param farm.rounds=5 --param farm.timeout=60
```

**参数和黑板是两件东西，别混**（这是这个框架里最容易搞错的一对）：

| | `ctx.param(name, default)` | `ctx.blackboard` |
|---|---|---|
| 是什么 | **入参**：这次运行的输入 | **跑出来的状态** |
| 谁写 | 外面（表单 / 命令行 / 测试） | 步骤自己 |
| 跑的过程中变吗 | **不变** | 一直在变 |
| 每次运行开始时清吗 | **不清** | 清 |

判断方法很简单：**"用户还没点开始时它就有值了吗？"** 有 → 参数；
要靠跑起来才产生的 → 黑板。

参数名建议点分层级（`"farm.rounds"`），避免和别的脚本/别的用途撞名。
命令行传的值会尽量转成 int / float / 布尔 —— 否则步骤里拿到字符串，
`range("5")` 直接炸，而报错点在步骤、跟命令行看不出关系。

## 运行参数的表单（让人能调）

参数有了机制，还得有个**界面**——不然每调一个值都要敲命令行。在功能目录里加
`form.py` 声明一个 `FORM`，界面上就会出现对应的控件：

```python
# games/<游戏>/<功能>/form.py
from gamebot.params import FieldKind, FormSpec, ParamField

FORM = FormSpec(
    title="竞技场参数",
    fields=(
        ParamField("farm.rounds", FieldKind.INT, 1, label="刷几轮",
                   help="0 = 一直刷", min=0, max=99),
        ParamField("farm.team", FieldKind.CHOICE, "auto", label="队伍",
                   choices=(("auto", "自动"), ("main", "主力队"))),
        ParamField("farm.strict", FieldKind.BOOL, False, label="严格模式"),
        ParamField("farm.note", FieldKind.TEXT, "", label="备注"),
    ),
)
```

**只有四种控件** —— 想表达更复杂的东西就往文本里塞 JSON，或者别用表单
（那是代码和命令行的事）：

| 声明 | 控件 | 说明 |
|---|---|---|
| `BOOL` | 复选框 | |
| `INT` / `FLOAT` | 数字输入框 | `min`/`max` **直接设成控件范围**，用户输不进越界值 |
| `TEXT` | 输入框 | 有长度上限（表单值会进日志） |
| `CHOICE` | 选择器 | `choices=((值, 显示名), ...)`，传下去的是**值**不是显示名 |

### 三条必须记住的

**1. 声明写错在 `ParamField(...)` 那一行就炸。** 重名、`CHOICE` 没给选项、
默认值不在选项里、`min > max` …… 全都当场 `ConfigError`，不会拖到用户点了开始。

**2. 值进的是运行参数，不是配置。** 点「开始」时 `FORM.fill(表单值)` 凑一份
完整参数交给 `ctx.params`，步骤里 `ctx.param("farm.rounds")` 现读：

```
FORM 声明 → 用户填 → 点开始 → FORM.fill() → ctx.params → 步骤 run() 时现读
```

所以步骤**不要在构造函数里收表单值**（那是静态的、拿不到），也别给 `ctx.param`
再写一遍默认值 —— `fill()` 保证每个声明过的字段都有值，**默认值只有 `FORM`
一处出处**。

**3. 校验只有一份配置。** 控件的范围由 `FORM` 生成，表单提交走
`FORM.fill()`，命令行 `--param` 走**同一个** `fill()`。两处各写一份的话，
迟早出现"界面拦得住的、命令行拦不住"，而用户会以为是自己参数写错了。

### 表单里没有的参数照样能用

表单是运行参数的一个**子集入口**，不是唯一出处：

* 表单里有的字段，用户能调；
* 表单里**没有**的参数（测试注入的假后端、只在代码里传的配置）照样走
  `ctx.params`，命令行 `--param` 也允许传 —— 那些不受表单约束。

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

**放哪一层按"谁用"定，不是按"看起来属于哪"。** 只有这个玩法用得到的图放
本功能目录；**多个脚本都要用**的（网络错误弹窗、通用按钮）才放游戏级。
判断错了不会报错 —— 只是以后加第二个脚本时会发现"这张图怎么找不到了"，
或者游戏级目录里堆了一堆其实只有一个脚本用的图。

### 两件事，别混（这块来回改过三次，值得单独说）

同一个 `templates/` 目录里，**"放哪一层"和"子目录叫什么"回答的是两个不同的问题**：

| 问题 | 答案由什么决定 | 例子 |
|---|---|---|
| 放**功能级**还是**游戏级**？ | 谁声明用它 —— 一个功能专属就放功能级 | 竞技卡 → 功能级（不是公共资源） |
| 子目录名写什么？ | 它**长在哪个界面上** | 竞技卡长在首页 → `home/` |

所以竞技卡是 **`<功能根>/home/jingji_card.png`**：

```
games/mingjiangsha/jingji/templates/
├── home/jingji_card.png          竞技卡：长在**首页**上、但属于竞技功能
└── jingji/
    ├── title.png                 左上角「竞技场」标题（页面标识）
    ├── create_team.png           三个按钮：都长在**竞技场页**上
    ├── add_pet.png
    └── start_match.png
```

**子目录 = 界面分组**，不是功能名。功能目录已经叫 `jingji` 了，
再在它里面套一个 `templates/jingji/` 当"功能命名空间"是重复的 ——
`templates/jingji/` 之所以存在，是因为那四张图**长在竞技场页上**。

**目录层级要跟着模板名走。** 模板名是相对模板根的路径，所以
`"battle/skill.png"` 会落到 `<根>/battle/skill.png`。名字里带层级、
磁盘上却没建那个子目录，报的是"找不到图"而不是"目录不存在"。

**改了目录就要改模板名，反之亦然。** 两处对不上时唯一的症状就是
`games check` 报"缺某个模板文件"—— 而报出来的名字正是你写错的那个，
照着它建目录/改名就行，不用猜。

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

**"认得出但认错地方"要靠界面的「识图日志」发现。** 它会把每一次匹配的框画在
真机截图上（红=命中、橙=未命中、蓝=搜索范围），位置偏没偏一眼就看出来 ——
这种问题静态代码查不出来，早先那套 `selftest` 想查但没人维护。

## 加一个游戏 / 加一个功能

**加一个功能**：在 `games/<游戏>/` 下建一个新目录，复制 `mingjiangsha/jingji/` 的骨架（`__init__.py` + `pages.py` + `graph.py` + `steps.py`）。

**加一个游戏**：按上面的布局建 `games/<游戏>/`，改三样 ——
`SLUG` / `WINDOW_TITLE` / `SOURCE_SIZE`，然后是页面、模板、流程。
游戏级要放什么，取决于有没有多个脚本要共用（见前面那段）。

