"""业务层脚本的**声明** —— 一个脚本导出**一个** ``SPEC``。

## 为什么要有这个

原来业务层的 ``__init__.py`` 导出的是**散装**的几个东西，而且里面还有
**组装代码**。那些是**每份声明都一样**的东西 —— 让每个功能各写一遍，
等于把"会不会写错"复制到每一个脚本里。

现在导出一个 ``FeatureSpec``：**只有数据**，框架负责组装。

* 字段全必选的部分漏了，编辑器当场报 ``Missing positional argument``；
* 名字拼错报 ``Unexpected keyword argument ... did you mean ...?``；
* 类型传错也报。

于是"结构对不对"在**写的时候**就有反馈，不需要跑起来或点一个检查按钮。

功能级模板根不单独声明：约定就是 ``games/<游戏>/scripts/<功能>/templates``，
由 ``name`` 推导；装配时相对仓库根解析。
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import ConfigError
from .flow.scenario import Scenario
from .params import FormSpec
from .scenario_spec import ScenarioSpec

__all__ = ["FeatureSpec"]


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """一个功能脚本的完整声明。

    业务层在 ``games/<游戏>/scripts/<功能>/__init__.py`` 里构造一个 ``SPEC`` 导出它。

    :param name: ``"<游戏>/<功能>"``，命令行和界面都用它标识（不含 ``scripts``）。
        功能级模板根由它推导：``games/<游戏>/scripts/<功能>/templates``。
    :param title: 给人看的名字（进日志、进界面下拉框）。
    :param slug: 功能目录名（如 ``"jingji"``），用在 journal 文件名上。
    :param window_title: 找游戏窗口用的标题关键字。UI/CLI 可覆盖。
    :param scenario: 状态树 + 流程图 + 引擎选项，**全是数据**
        （见 :class:`~gamebot.scenario_spec.ScenarioSpec`）。
    :param description: 一句话说明，进列表和日志。
    :param form: 运行参数表单。没有就是空表单（界面上不显示那一块）。
    """

    name: str
    title: str
    slug: str
    window_title: str
    scenario: ScenarioSpec
    description: str = ""
    form: FormSpec | None = None

    @property
    def templates_dir(self) -> str:
        """功能级模板根，**相对仓库根**。约定 ``games/<游戏>/scripts/<功能>/templates``。"""
        game, feature = self.name.split("/", 1)
        return f"games/{game}/scripts/{feature}/templates"

    @property
    def game_templates_dir(self) -> str:
        """游戏级公共模板根，**相对仓库根**。约定 ``games/<游戏>/templates``。

        放"多个脚本都要用"的图：按钮花纹、通用弹窗、公共图标。
        查找顺序是**功能级优先、游戏级兜底**（功能级可以覆盖同名图）——
        见 :func:`gamebot.bootstrap.build_matcher` 的 ``fallback_dirs``。
        """
        game = self.name.split("/", 1)[0]
        return f"games/{game}/templates"

    def __post_init__(self) -> None:
        """声明自身的检查。**构造这一行就报**，而不是等框架捞不着东西才猜。"""
        if not self.name or "/" not in self.name:
            raise ConfigError(
                f"FeatureSpec.name 要写成 '<游戏>/<功能>'，收到 {self.name!r}"
            )
        if not self.title.strip():
            raise ConfigError(f"{self.name}: title 不能为空")
        if not self.slug.strip():
            raise ConfigError(f"{self.name}: slug 不能为空")
        if not self.window_title.strip():
            raise ConfigError(f"{self.name}: window_title 不能为空")
        if not isinstance(self.scenario, ScenarioSpec):
            raise ConfigError(
                f"{self.name}: scenario 要是 ScenarioSpec，收到 {type(self.scenario).__name__}"
            )
        if self.form is not None and not isinstance(self.form, FormSpec):
            raise ConfigError(
                f"{self.name}: form 要是 FormSpec 或 None，收到 {type(self.form).__name__}"
            )

    def materialize_scenario(self) -> Scenario:
        """把声明拼成运行期的 :class:`Scenario`。

        ``name`` 用 SPEC 的（而不是 ``ScenarioSpec`` 上另写一个）——
        脚本名只该有一个出处，否则报告里的名字和列表里的对不上。
        """
        return self.scenario.materialize(name=self.name)
