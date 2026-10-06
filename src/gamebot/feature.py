"""业务层脚本的**声明** —— 一个脚本导出**一个** ``SPEC``。

## 为什么要有这个

原来业务层的 ``__init__.py`` 导出的是**散装**的几个东西：``TITLE``、
``DESCRIPTION``、``build_config()``、``build_scenario()``，外加一个单独文件里的
``FORM``。框架靠 ``getattr`` 按名字去捞 —— 于是"必须有哪些、叫什么"这条契约
**只存在于框架的字符串里，编辑器和类型检查都看不见**。

现在导出一个 ``FeatureSpec``：

* **字段全必选**（没有默认值的那些），漏了编辑器当场报
  ``Missing positional argument``；
* 字段名拼错报 ``Unexpected keyword argument ... did you mean ...?``；
* 类型传错也报（``templates_dir`` 写了个 ``Path`` 而不是 ``str``）。

于是"结构对不对"这件事在**写的时候**就有反馈，不需要跑起来或点一个检查按钮。

## 它和一个 dict 的区别

用 ``dict`` 也能"收拢在一处"，但编辑器看不出任何东西 —— 那正是要避免的。
这里每个字段都有类型、有 docstring，`mypy` 全部认识。

## 它**不**负责什么

* 不识图、不跑流程：那些在 `Scenario` / `PageTree` 里；
* 不做跨对象的校验（节点有没有认领状态、模板文件在不在）—— 那些**原理上**
  要看到全部数据或磁盘才能判断，归 `Scenario.validate()` 和加载时的检查。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .config.schema import AppConfig
from .exceptions import ConfigError
from .flow.scenario import Scenario
from .params import FormSpec

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
    :param build_config: 造一份配置。**必须是个无参可调用对象**（不是配置本身）——
        因为每次运行都要一份新的，共享一个 ``AppConfig`` 会让一次运行改到的
        东西泄漏到下一次。
    :param build_scenario: 造一份流程定义。同理，每次运行一份新的。
    :param description: 一句话说明，进列表和日志。
    :param form: 运行参数表单。没有就是空表单（界面上不显示那一块）。
    """

    name: str
    title: str
    slug: str
    templates_dir: str
    build_config: Callable[[], AppConfig]
    build_scenario: Callable[[], Scenario]
    description: str = ""
    form: FormSpec | None = None

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
        if not callable(self.build_config):
            raise ConfigError(
                f"{self.name}: build_config 要是**可调用对象**（每次造一份新的），"
                f"收到 {type(self.build_config).__name__}"
            )
        if not callable(self.build_scenario):
            raise ConfigError(
                f"{self.name}: build_scenario 要是**可调用对象**，"
                f"收到 {type(self.build_scenario).__name__}"
            )
        if self.form is not None and not isinstance(self.form, FormSpec):
            raise ConfigError(
                f"{self.name}: form 要是 FormSpec 或 None，"
                f"收到 {type(self.form).__name__}"
            )
