"""业务层脚本的**声明** —— 一个脚本导出**一个** ``SPEC``。

## 为什么要有这个

原来业务层的 ``__init__.py`` 导出的是**散装**的几个东西，而且里面还有
**组装代码**：``build_tree()`` 里 ``for page, parent in ...: tree.add(...)``、
``build_graph()`` 里 ``graph.add_node(...)`` / ``graph.connect(...)``。
那些是**每份声明都一样**的东西 —— 让每个功能各写一遍，等于把"会不会写错"
复制到每一个脚本里（忘了 ``add_node`` 就连边，是运行期事故）。

现在导出一个 ``FeatureSpec``：**只有数据**，框架负责组装。

* 字段全必选的部分漏了，编辑器当场报 ``Missing positional argument``；
* 名字拼错报 ``Unexpected keyword argument ... did you mean ...?``；
* 类型传错也报。

于是"结构对不对"在**写的时候**就有反馈，不需要跑起来或点一个检查按钮。

## 关于"可变值"和"函数"

有两处看着像"该收数据"，实际必须是**函数**：

* ``base_config`` —— 游戏级基础配置里含 ``PROJECT_ROOT`` 这类**环境推导值**，
  是"怎么跑"而不是"这是什么"，属于代码；
* ``build_config`` —— 每次运行都要**一份新的** ``AppConfig``。收一个配置对象
  会让一次运行改到的东西泄漏到下一次（那个坑以前踩过，所以类型上就要求可调用）。

其余全是声明：模板根、页面、节点、边、引擎选项。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .config.schema import AppConfig
from .exceptions import ConfigError
from .flow.scenario import Scenario
from .params import FormSpec
from .scenario_spec import ScenarioSpec
from .state.page import PageTree

__all__ = ["FeatureSpec"]


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """一个功能脚本的完整声明。

    业务层在 ``games/<游戏>/<功能>/__init__.py`` 里构造一个 ``SPEC`` 导出它。

    :param name: ``"<游戏>/<功能>"``，命令行和界面都用它标识。
    :param title: 给人看的名字（进日志、进界面下拉框）。
    :param slug: 功能目录名（如 ``"jingji"``），用在 journal 文件名上。
    :param templates_dir: 这个功能自己的模板根，**相对仓库根**。
        路径分隔统一用 ``/``。它优先于游戏级的模板根。
    :param scenario: 状态树 + 流程图 + 引擎选项，**全是数据**
        （见 :class:`~gamebot.scenario_spec.ScenarioSpec`）。
    :param base_config: 造一份**游戏级基础配置**（窗口、分辨率、游戏级模板根……）。
        必须是可调用对象而不是配置对象：里含 ``PROJECT_ROOT`` 这类环境推导值，
        而且每次运行都要一份新的。
    :param build_config: 可选。在框架拼好的配置上做**本功能**的最后调整。
        绝大多数脚本不需要 —— 模板根、名字、tick 间隔框架都会从声明里填好。
        留这个入口是为了"这个脚本真要拧某个框架级旋钮"这种情况。
    :param base_tree: 可选。造一棵**游戏级公共页面**的树；框架会先放它、
        再放 ``scenario.pages``。同样必须是可调用对象（每次一棵新的）。
    :param description: 一句话说明，进列表和日志。
    :param form: 运行参数表单。没有就是空表单（界面上不显示那一块）。
    """

    name: str
    title: str
    slug: str
    templates_dir: str
    scenario: ScenarioSpec
    base_config: Callable[[], AppConfig]
    description: str = ""
    form: FormSpec | None = None
    build_config: Callable[[AppConfig], AppConfig] | None = None
    base_tree: Callable[[], PageTree] | None = None

    def __post_init__(self) -> None:
        """声明自身的检查。**构造这一行就报**，而不是等框架捞不着东西才猜。

        跨对象的部分（节点认领状态、模板文件在不在）不在这里 —— 见模块开头。
        """
        if not self.name or "/" not in self.name:
            raise ConfigError(
                f"FeatureSpec.name 要写成 '<游戏>/<功能>'，收到 {self.name!r}"
            )
        if not self.title.strip():
            raise ConfigError(f"{self.name}: title 不能为空")
        if not self.slug.strip():
            raise ConfigError(f"{self.name}: slug 不能为空")
        if not self.templates_dir.strip():
            raise ConfigError(f"{self.name}: templates_dir 不能为空")
        if not isinstance(self.scenario, ScenarioSpec):
            raise ConfigError(
                f"{self.name}: scenario 要是 ScenarioSpec，收到 {type(self.scenario).__name__}"
            )
        if not callable(self.base_config):
            raise ConfigError(
                f"{self.name}: base_config 要是**可调用对象**（每次造一份新的），"
                f"收到 {type(self.base_config).__name__}"
            )
        if self.form is not None and not isinstance(self.form, FormSpec):
            raise ConfigError(
                f"{self.name}: form 要是 FormSpec 或 None，收到 {type(self.form).__name__}"
            )
        if self.build_config is not None and not callable(self.build_config):
            raise ConfigError(
                f"{self.name}: build_config 要是可调用对象或 None，"
                f"收到 {type(self.build_config).__name__}"
            )
        if self.base_tree is not None and not callable(self.base_tree):
            raise ConfigError(
                f"{self.name}: base_tree 要是可调用对象或 None，"
                f"收到 {type(self.base_tree).__name__}"
            )

    # ------------------------------------------------------------------ #
    # 组装（框架调）
    # ------------------------------------------------------------------ #
    def materialize_config(self) -> AppConfig:
        """把声明拼成一份**完整配置**。

        顺序是"游戏级基础 → 本功能声明里的那几项 → 可选的本功能调整"。
        中间那步是**框架**填的，不是业务层写的：

        * ``name`` ← ``FeatureSpec.name``；
        * ``vision.extra_template_dirs`` ← ``templates_dir``（功能级模板根，
          优先级高于游戏级）；
        * ``timing.tick_interval`` ← ``scenario.options.tick_interval``
          —— 引擎节奏只声明**一次**，填在这里是为了让帧 TTL
          （``bootstrap`` 按它算）跟得上引擎。两处各写一个值的话，
          声明成 2.0 而帧 TTL 按 0.4 算，就会出现"帧早就过期了"的怪事。
        """
        config = self.base_config()
        config.name = self.name
        config.vision.extra_template_dirs = (self.templates_dir,)
        tick = self.scenario.options.tick_interval
        if tick and tick > 0:
            config.timing.tick_interval = tick
        if self.build_config is not None:
            config = self.build_config(config)
        return config

    def materialize_scenario(self) -> Scenario:
        """把声明拼成运行期的 :class:`Scenario`。

        ``name`` 用 SPEC 的（而不是 ``ScenarioSpec`` 上另写一个）——
        脚本名只该有一个出处，否则报告里的名字和列表里的对不上。
        """
        tree = self.base_tree() if self.base_tree is not None else None
        return self.scenario.materialize(name=self.name, tree=tree)
