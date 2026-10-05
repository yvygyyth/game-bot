"""运行参数表单 —— 按脚本声明的 ``FORM`` 动态生成控件。

## 数据是单向的

    FORM 声明（含默认值）
       ↓  表单初始值 = 声明的默认值
    表单持有"当前值"  ←── 用户编辑（**唯一**改值的地方）
       ↓  点「开始」时调一次 :meth:`ParamsPanel.values`
    FORM.fill(...)  →  ctx.params  →  步骤里 ctx.param(...) 现读

**没有"未动过的字段"这个概念**：取的是表单里全部字段的当前值。每个字段初始化
时就从声明拿了默认值，所以"这个要不要传下去"根本不是个问题 —— 也因此代码里
不需要区分"用户改过"和"没改过"（那种区分一引入，就得回答"没改过的算不算
显式选择"，而这个问题没有好答案）。

## 控件只有四种

勾选 / 选一个 / 打字 / 填数字。想表达更复杂的东西就往文本里塞 JSON，
或者别用表单（那是代码和 CLI 的事）。

数字的 ``min``/``max`` **直接设成 SpinBox 的 range** —— 控件层就卡住，
用户根本输不进越界值。所以表单提交时不用再做一次边界检查（真做了也是
同一份声明在管，见 ``gamebot.params``）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...params import TEXT_MAX_LENGTH, FieldKind, FormSpec, ParamField

__all__ = ["ParamsPanel"]


#: 数字没声明范围时给多大。**刻意是个"大到不碍事"的数**而不是 None ——
#: SpinBox 必须有个范围，而"不限制"在 Qt 里表达不了。
#: 不声明范围的字段本来就该是少数（范围是给用户看的提示，不是限制）。
_FALLBACK_INT_RANGE = (-1_000_000, 1_000_000)
_FALLBACK_FLOAT_RANGE = (-1e9, 1e9)
_FLOAT_DECIMALS = 3


class ParamsPanel(QGroupBox):
    """一个脚本的运行参数表单。没有表单时**整块藏起来**（见 :meth:`set_form`）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("运行参数", parent)
        self._form = FormSpec()
        self._editors: dict[str, QWidget] = {}

        self._hint = QLabel("这个脚本没有可调的运行参数", self)
        self._hint.setStyleSheet("color:#7f8c8d;")
        self._hint.setWordWrap(True)

        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)

        self._fields = QFormLayout()
        self._body_layout.addLayout(self._fields)

        self._reset_btn = QPushButton("重置为默认值", self)
        self._reset_btn.setToolTip(
            "把这几个字段恢复成脚本声明的默认值。\n"
            "参数不会自动保存 —— 每次打开界面都是默认值，这一点是刻意的：\n"
            "免得出现「上次改过的值偷偷生效」这种查不出来的事。"
        )
        self._reset_btn.clicked.connect(self.reset)
        self._body_layout.addWidget(self._reset_btn)

        outer = QVBoxLayout(self)
        outer.addWidget(self._hint)
        outer.addWidget(self._body)
        self.set_form(FormSpec())

    # ------------------------------------------------------------------ #
    # 装配
    # ------------------------------------------------------------------ #
    def set_form(self, form: FormSpec | None) -> None:
        """换一个脚本时重建表单。``None`` / 空表单 -> 整块藏起来。"""
        self._form = form or FormSpec()
        self._clear()

        if not self._form:
            # 没有表单的脚本不留一个空框 —— 那只会让人以为"是不是加载失败了"
            self._hint.setText("这个脚本没有可调的运行参数")
            self._hint.show()
            self._body.hide()
            return

        self._hint.hide()
        self._body.show()
        self.setTitle(self._form.title or "运行参数")
        for item in self._form.fields:
            editor = self._make_editor(item)
            self._editors[item.name] = editor
            self._fields.addRow(item.display, editor)
        self.reset()

    @property
    def form(self) -> FormSpec:
        return self._form

    def _clear(self) -> None:
        """把上一次的字段**整块换掉**。

        ## 为什么不是逐个摘 widget

        ``takeAt`` 能把控件从布局里摘出来，但 **``QFormLayout`` 内部的行映射
        不会因此减少** —— 摘完之后 ``rowCount()`` 还是 5，再加 5 个就变成 10。
        表现是换一次脚本、界面上的字段名多留一列，而且没有任何报错。

        ``labelForField`` 也救不了：``addRow("标签", w)`` 造的标签在
        ``takeAt`` 之后就已经从布局里摘掉了，查不回来。

        所以干脆把整个 ``QFormLayout`` 换成新的 —— Qt 里"清空一个布局"
        的可靠做法是删掉它，而不是掏空它。
        """
        self._editors.clear()
        self._body_layout.removeItem(self._fields)
        self._fields.deleteLater()
        self._fields = QFormLayout()
        # 插回"重置按钮"之前，保持顺序：字段在上、按钮在下
        self._body_layout.insertLayout(0, self._fields)

    def _make_editor(self, item: ParamField) -> QWidget:
        tip = item.help or item.name
        if item.kind is FieldKind.BOOL:
            editor: QWidget = QCheckBox(self)
            editor.setChecked(bool(item.default))
        elif item.kind is FieldKind.CHOICE:
            editor = QComboBox(self)
            for value, shown in item.choices:
                editor.addItem(shown, value)
            index = editor.findData(item.default)
            editor.setCurrentIndex(max(0, index))
        elif item.kind is FieldKind.TEXT:
            editor = QLineEdit(self)
            editor.setText(str(item.default))
            editor.setMaxLength(TEXT_MAX_LENGTH)
            editor.setPlaceholderText(tip)
        elif item.kind is FieldKind.FLOAT:
            editor = QDoubleSpinBox(self)
            low, high = (
                (item.min, item.max)
                if item.min is not None and item.max is not None
                else _FALLBACK_FLOAT_RANGE
            )
            editor.setRange(low, high)
            editor.setDecimals(_FLOAT_DECIMALS)
            if item.step:
                editor.setSingleStep(item.step)
            editor.setValue(float(item.default))
        else:
            editor = QSpinBox(self)
            low, high = (
                (int(item.min), int(item.max))
                if item.min is not None and item.max is not None
                else _FALLBACK_INT_RANGE
            )
            editor.setRange(low, high)
            if item.step:
                editor.setSingleStep(int(item.step))
            editor.setValue(int(item.default))
        editor.setToolTip(tip)
        return editor

    # ------------------------------------------------------------------ #
    # 读写
    # ------------------------------------------------------------------ #
    def values(self) -> dict[str, Any]:
        """表单里**全部**字段的当前值。点「开始」时调它。"""
        return {name: self._read(editor) for name, editor in self._editors.items()}

    def reset(self) -> None:
        """恢复成声明的默认值。"""
        for item in self._form.fields:
            editor = self._editors.get(item.name)
            if editor is None:
                continue
            self._write(editor, item.default)

    @staticmethod
    def _read(editor: QWidget) -> Any:
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        if isinstance(editor, QComboBox):
            return editor.currentData()
        if isinstance(editor, QLineEdit):
            return editor.text()
        if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            return editor.value()
        return None  # pragma: no cover - _make_editor 只造这四种

    @staticmethod
    def _write(editor: QWidget, value: Any) -> None:
        if isinstance(editor, QCheckBox):
            editor.setChecked(bool(value))
        elif isinstance(editor, QComboBox):
            index = editor.findData(value)
            editor.setCurrentIndex(max(0, index))
        elif isinstance(editor, QLineEdit):
            editor.setText(str(value))
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.setValue(value)  # 越界会被 Qt 夹到 range 里，这正是想要的
