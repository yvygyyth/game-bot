"""动态表单的声明 —— "这个脚本有哪些运行参数可以让人调"。

## 它和 :meth:`RunContext.param` 的关系（别混）

两件事，一个是机制、一个是界面：

* **运行参数**（``ctx.param``）对类型**没有任何限制**。值可以是 dict、列表、
  任意对象 —— 测试时注入一个假后端、代码里传一份配置，都走它；
* **动态表单**（本模块）只管**四种控件**能表达的类型：勾选、选一个、
  打字、填数字。它是运行参数的一个**子集入口**。

所以本模块刻意不做成"参数的唯一出处"：脚本完全可以有表单里没有的参数
（留给代码或 CLI），也可以有表单里有、步骤暂时不读的参数。

## 数据是单向的

    FORM 声明（含默认值）
       ↓  表单初始值 = 声明的默认值
    表单持有"当前值"  ←── 用户编辑（唯一改值的地方）
       ↓  点「开始」时**从表单读一次**
    params  →  ctx.param(...)  →  步骤

**没有"未动过的字段"这个概念**：点开始时取表单的**全部**当前值。表单里每个
字段都有值（初始来自声明），所以"这个字段要不要传"根本不是个问题。

## 校验只有一份配置

:class:`FormSpec` 就是那份配置：控件层的 ``min``/``max`` 由它生成
（SpinBox 的 range 就是它，**控件层就卡住**），提交时的越界判定也走它的
:meth:`FormSpec.coerce`。命令行 ``--param`` 走**同一个** ``coerce`` ——
一处定义、一处判定，不存在"表单一套、命令行一套"。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .exceptions import ConfigError

__all__ = ["TEXT_MAX_LENGTH", "FieldKind", "FormSpec", "ParamField"]


class FieldKind(StrEnum):
    """一个字段用哪种控件。

    刻意只有四种（对应四个组件）—— 想表达更复杂的东西就往文本里塞 JSON，
    或者别用表单（那是代码和 CLI 的事）。加第五种之前先问：**它真的需要
    一个新控件，还是只是某个已有控件的参数？**
    """

    BOOL = "bool"
    """复选框。"""

    INT = "int"
    """整数输入框（``QSpinBox``）。"""

    FLOAT = "float"
    """小数输入框（``QDoubleSpinBox``）。"""

    TEXT = "text"
    """单行输入框（``QLineEdit``）。"""

    CHOICE = "choice"
    """选择器（``QComboBox``），从 ``choices`` 里选一个。"""


#: 文本框的长度上限。定一个上限是为了让"内存里能塞多少"这件事可预期 ——
#: 表单值会进 journal / 日志，无限长的输入是个隐患。
TEXT_MAX_LENGTH = 200


@dataclass(frozen=True, slots=True)
class ParamField:
    """一个表单字段。**声明期就尽量把错误报出来**，不要等用户点了开始。"""

    name: str
    """参数名，步骤里用 ``ctx.param(name)`` 读。建议点分层级（``"farm.rounds"``）。"""

    kind: FieldKind
    default: Any = None
    label: str = ""
    """显示给人看的名字。不给就用 ``name``。"""

    help: str = ""
    """鼠标悬停时的说明。"""

    min: float | None = None
    """数字字段的下界。**控件层就卡住** —— SpinBox 的 range 直接用它。"""

    max: float | None = None

    step: float | None = None
    """数字字段点上下箭头时一次走多少。不给就用 Qt 的默认。"""

    choices: tuple[tuple[Any, str], ...] = ()
    """``CHOICE`` 的选项：``((值, 显示名), ...)``。

    值是"给代码的"，显示名是"给人的"。**两者分开**是因为给代码的值经常
    不适合直接看（``"auto"`` 该显示成"自动"）。
    """

    def __post_init__(self) -> None:
        # 冻结的 dataclass 只能用 object.__setattr__ 补默认 label
        if not self.label:
            object.__setattr__(self, "label", self.name)
        # **构造时就查**：声明是静态数据，写错了没有任何理由拖到运行时 ——
        # 而"拖到用户点了开始才报"是最难查的一种（他会以为是自己填错了）。
        self.validate()

    @property
    def display(self) -> str:
        return self.label or self.name

    def validate(self) -> None:
        """查这条声明自不自洽。

        :meth:__post_init__ 会**自动调一次** —— 也就是说声明写错了在
        `ParamField(...)` 那一行就炸，不会拖到运行时。
        """
        if not self.name or not self.name.strip():
            raise ConfigError("表单字段的 name 不能为空")

        if self.kind is FieldKind.CHOICE:
            if not self.choices:
                raise ConfigError(f"字段 {self.name!r} 是选择器，但没给 choices")
            values = [value for value, _ in self.choices]
            if len(set(map(repr, values))) != len(values):
                raise ConfigError(f"字段 {self.name!r} 的 choices 里有重复的值")
            for _, shown in self.choices:
                if not shown:
                    raise ConfigError(f"字段 {self.name!r} 的 choices 里有空显示名")
            if self.default is not None and not any(
                value == self.default for value, _ in self.choices
            ):
                raise ConfigError(
                    f"字段 {self.name!r} 的默认值 {self.default!r} 不在 choices 里"
                    f"（可选: {[v for v, _ in self.choices]}）"
                )
        elif self.choices:
            raise ConfigError(f"字段 {self.name!r} 不是选择器，却给了 choices")

        if self.kind in (FieldKind.INT, FieldKind.FLOAT):
            self._validate_number()
        elif self.min is not None or self.max is not None or self.step is not None:
            raise ConfigError(f"字段 {self.name!r} 不是数字，却给了 min/max/step")

        if self.kind is FieldKind.BOOL and not isinstance(self.default, bool):
            raise ConfigError(
                f"字段 {self.name!r} 是复选框，默认值必须是 True/False，"
                f"实际是 {type(self.default).__name__}"
            )
        if self.kind is FieldKind.TEXT and not isinstance(self.default, str):
            raise ConfigError(
                f"字段 {self.name!r} 是文本框，默认值必须是字符串，"
                f"实际是 {type(self.default).__name__}"
            )

    def _validate_number(self) -> None:
        if self.default is None or isinstance(self.default, bool):
            # bool 是 int 的子类，写 ParamField(..., INT, True) 多半是笔误
            raise ConfigError(
                f"数字字段 {self.name!r} 必须有默认值（True/False 也不行 —— "
                "那是复选框）"
            )
        if self.kind is FieldKind.INT and not isinstance(self.default, int):
            raise ConfigError(
                f"字段 {self.name!r} 声明为整数，默认值却是 "
                f"{type(self.default).__name__}（要小数请用 FieldKind.FLOAT）"
            )
        if not isinstance(self.default, (int, float)):
            raise ConfigError(
                f"数字字段 {self.name!r} 的默认值必须是数字，"
                f"实际是 {type(self.default).__name__}"
            )
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ConfigError(
                f"字段 {self.name!r} 的 min({self.min}) 比 max({self.max}) 还大"
            )
        if self.min is not None and self.default < self.min:
            raise ConfigError(
                f"字段 {self.name!r} 的默认值 {self.default} 小于 min {self.min}"
            )
        if self.max is not None and self.default > self.max:
            raise ConfigError(
                f"字段 {self.name!r} 的默认值 {self.default} 大于 max {self.max}"
            )
        if self.step is not None and self.step <= 0:
            raise ConfigError(f"字段 {self.name!r} 的 step 必须为正数")

    def coerce(self, value: Any) -> Any:
        """把一个外部来的值转成这个字段认的类型，越界就报错。

        **唯一的校验处**：表单提交走它，命令行 ``--param`` 也走它。
        两处各写一份的话，迟早会出现"界面拦得住的、命令行拦不住"这种不一致。
        """
        if self.kind is FieldKind.BOOL:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("true", "1", "yes", "on"):
                    return True
                if lowered in ("false", "0", "no", "off", ""):
                    return False
            raise ConfigError(f"参数 {self.name!r} 要 True/False，收到 {value!r}")

        if self.kind is FieldKind.TEXT:
            if not isinstance(value, str):
                raise ConfigError(f"参数 {self.name!r} 要字符串，收到 {type(value).__name__}")
            if len(value) > TEXT_MAX_LENGTH:
                raise ConfigError(
                    f"参数 {self.name!r} 太长了（{len(value)} > {TEXT_MAX_LENGTH}）"
                )
            return value

        if self.kind is FieldKind.CHOICE:
            for candidate, _ in self.choices:
                # 表单给的是选项**值**；命令行给的是字符串，两种都要认
                if candidate == value or str(candidate) == str(value):
                    return candidate
            raise ConfigError(
                f"参数 {self.name!r} 的值 {value!r} 不在选项里"
                f"（可选: {[v for v, _ in self.choices]}）"
            )

        return self._coerce_number(value)

    def _coerce_number(self, value: Any) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ConfigError(f"参数 {self.name!r} 要数字，收到 {value!r}")
        if isinstance(value, str):
            text = value.strip()
            try:
                number: int | float = (
                    float(text) if self.kind is FieldKind.FLOAT else int(text)
                )
            except ValueError as exc:
                raise ConfigError(f"参数 {self.name!r} 要数字，看不懂 {value!r}") from exc
        else:
            number = value
        if self.kind is FieldKind.INT and isinstance(number, float):
            if number != int(number):
                raise ConfigError(f"参数 {self.name!r} 要整数，收到 {value!r}")
            number = int(number)
        if self.min is not None and number < self.min:
            raise ConfigError(f"参数 {self.name!r} 不能小于 {self.min}（收到 {number}）")
        if self.max is not None and number > self.max:
            raise ConfigError(f"参数 {self.name!r} 不能大于 {self.max}（收到 {number}）")
        return number


@dataclass(frozen=True, slots=True)
class FormSpec:
    """一个脚本的整个表单。业务层在 ``form.py`` 里声明一个 ``FORM``。"""

    fields: tuple[ParamField, ...] = ()
    title: str = "运行参数"

    def __post_init__(self) -> None:
        seen: dict[str, int] = {}
        for position, item in enumerate(self.fields):
            if item.name in seen:
                raise ConfigError(
                    f"表单里有重名字段 {item.name!r}"
                    f"（第 {seen[item.name] + 1} 个和第 {position + 1} 个）"
                )
            seen[item.name] = position

    def __bool__(self) -> bool:
        return bool(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def validate(self) -> None:
        """逐条查。**装配期调一次** —— 声明写错了应该在建脚本时就报。"""
        for item in self.fields:
            item.validate()

    def defaults(self) -> dict[str, Any]:
        """表单的初始值：每条声明的默认值。"""
        return {item.name: item.default for item in self.fields}

    def get(self, name: str) -> ParamField | None:
        for item in self.fields:
            if item.name == name:
                return item
        return None

    def coerce(self, values: dict[str, Any]) -> dict[str, Any]:
        """把一批值按字段声明转换 + 校验，**没声明过的 key 原样留下**。

        为什么原样留下：``--param`` 允许传表单里没有的参数（那是代码的自由，
        见模块开头）。表单里有的才受这套约束。
        """
        result: dict[str, Any] = {}
        for key, value in values.items():
            spec = self.get(key)
            result[key] = spec.coerce(value) if spec is not None else value
        return result

    def fill(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        """**把一次运行的参数凑齐**：声明的默认值打底，用户给的值覆盖它。

        这一步是"表单"和"运行参数"的接缝，也是**唯一的校验处**：
        界面提交走它，命令行 ``--param`` 走它，测试想造一份参数也走它。

        :param values: 用户给的值（可能只有一部分，也**允许有表单没声明的 key**）。
            传 ``None`` 就是"全用默认值" —— 那是"用户一个都没改"的正常情况。
        :return: 一份完整的参数字典，可以直接交给 ``build_context(params=...)``。

        ## 为什么要有这个"凑齐"的动作

        步骤里读参数写的是 ``ctx.param("jingji.settle")`` —— 没有兜底默认值。
        如果表单只把用户改过的字段传下去，那些"用户没动"的字段在步骤里就变成
        缺失，于是每个 ``ctx.param`` 都得再写一遍默认值，而那份默认值和
        ``FORM`` 里的声明**是两处**，迟早不一致。

        所以：**默认值只有一份出处（声明），凑齐之后再往下传。**
        步骤那边 ``ctx.param(name)`` 直接拿到值，不用兜底。
        """
        merged = self.defaults()
        for key, value in (values or {}).items():
            spec = self.get(key)
            # 声明过的按声明校验；没声明的（CLI 的自由）原样带过去
            merged[key] = spec.coerce(value) if spec is not None else value
        return merged
