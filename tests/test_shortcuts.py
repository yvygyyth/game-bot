"""快捷键表测试：**绑定、提示、帮助三处必须出自同一份数据**。

快捷键最容易出的问题不是"没绑上"，而是"说的和做的不一致"（tooltip 写 F5、
实际绑 F6）。所以这里既验表本身自洽，也验它真的绑到了界面上。
"""

from __future__ import annotations

from gamebot.ui.shortcuts import SHORTCUTS, Keymap, Shortcut


class TestTable:
    def test_keys_are_unique(self):
        """同一个键不能绑两个动作 —— 后绑的会静默盖掉先绑的。"""
        keys = [spec.keys for spec in SHORTCUTS]
        assert len(keys) == len(set(keys)), f"有重复键位: {keys}"

    def test_actions_are_unique(self):
        actions = [spec.action for spec in SHORTCUTS]
        assert len(actions) == len(set(actions))

    def test_every_entry_is_described(self):
        """没有说明的快捷键，在 F1 帮助里就是一串看不懂的字母。"""
        for spec in SHORTCUTS:
            assert spec.keys.strip(), spec
            assert spec.label.strip(), spec

    def test_core_actions_exist(self):
        """这几个是承诺过的，别不小心删了。"""
        actions = {spec.action for spec in SHORTCUTS}
        assert {"run", "stop", "help"} <= actions

    def test_stop_is_escape_and_run_is_f5(self):
        """用户问的就是这个，钉住。"""
        mapping = {spec.action: spec.keys for spec in SHORTCUTS}
        assert mapping["run"] == "F5"
        assert mapping["stop"] == "Esc"

    def test_button_names_are_known(self):
        """``button`` 只能是控件栏里真有的那几种，否则 tooltip 会静默贴不上。"""
        known = {"start", "stop", "check", "detect"}
        for spec in SHORTCUTS:
            assert spec.button in known | {""}, spec

    def test_hint_format(self):
        assert Shortcut("x", "F5", "y").hint == "（F5）"


class TestKeymap:
    def test_missing_bindings_are_skipped_not_fatal(self, qt_app):
        """少给几个动作不该炸 —— 快捷键少一个不影响界面能用。"""
        from PySide6.QtWidgets import QWidget

        keymap = Keymap(QWidget(), {"run": lambda: None})
        assert len(keymap) == 1

    def test_non_callable_bindings_are_skipped(self, qt_app):
        from PySide6.QtWidgets import QWidget

        keymap = Keymap(QWidget(), {"run": "不是函数"})
        assert len(keymap) == 0

    def test_all_actions_can_be_bound(self, qt_app):
        from PySide6.QtWidgets import QWidget

        bindings = {spec.action: (lambda: None) for spec in SHORTCUTS}
        assert len(Keymap(QWidget(), bindings)) == len(SHORTCUTS)

    def test_tooltip_gets_the_real_key_and_is_idempotent(self, qt_app):
        from PySide6.QtWidgets import QPushButton, QWidget

        button = QPushButton("开始")
        button.setToolTip("开始运行")
        keymap = Keymap(QWidget(), {spec.action: (lambda: None) for spec in SHORTCUTS})

        keymap.add_tooltips({"start": button})
        assert button.toolTip() == "开始运行 （F5）"

        keymap.add_tooltips({"start": button})  # 再来一次不该越加越长
        assert button.toolTip() == "开始运行 （F5）"

    def test_help_lines_mention_the_keys(self, qt_app):
        from PySide6.QtWidgets import QWidget

        keymap = Keymap(QWidget(), {})
        text = "\n".join(keymap.help_lines())
        assert "F5" in text
        assert "Esc" in text


class TestMainWindowBinding:
    def test_window_binds_the_keymap(self, qt_app):
        """主窗口真的绑上了（不是只把表写在那儿）。"""
        from gamebot.ui.window import MainWindow

        window = MainWindow()
        try:
            assert len(window.keymap) == len(SHORTCUTS)
            assert "F5" in window.controls.start_btn.toolTip()
            assert "Esc" in window.controls.stop_btn.toolTip()
        finally:
            window.close()
