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

    def test_actions_are_unique_except_aliases(self):
        """一个动作一个主键 —— **除了显式标了 ``alias`` 的别名**。

        ``Shortcut`` 是"一个键 → 一个动作"的绑定，所以同一个动作出现两次
        必须是有意的（``alias=True``），否则就是复制粘贴事故。
        别名还得指向一个真实存在的主键 —— 不能凭空冒出一个动作。
        """
        primary = [spec.action for spec in SHORTCUTS if not spec.alias]
        assert len(primary) == len(set(primary)), f"有重复的主动作: {primary}"
        for spec in SHORTCUTS:
            if not spec.alias:
                continue
            assert any(
                other.action == spec.action and not other.alias for other in SHORTCUTS
            ), f"{spec.keys} 标成别名了，但没有对应的主键"

    def test_every_entry_is_described(self):
        """没有说明的快捷键，在 F1 帮助里就是一串看不懂的字母。"""
        for spec in SHORTCUTS:
            assert spec.keys.strip(), spec
            assert spec.label.strip(), spec

    def test_core_actions_exist(self):
        """这几个是承诺过的，别不小心删了。"""
        actions = {spec.action for spec in SHORTCUTS}
        assert {"run", "stop", "help"} <= actions

    def test_stop_keys_and_run_key(self):
        """用户问的就是这个，钉住。

        ``stop`` 有**两个**键：``Esc``（直觉）和 ``F9``（几乎没人抢）。
        ``F9`` 兼作诊断：它有效而 ``Esc`` 无效，就说明 ``Esc`` 被别的软件
        占了（全局钩子在 Windows 上是链式的，先装的先拿到），
        而不是本工具的钩子没装上。
        """
        keys_for: dict[str, list[str]] = {}
        for spec in SHORTCUTS:
            keys_for.setdefault(spec.action, []).append(spec.keys)
        assert keys_for["run"] == ["F5"]
        assert set(keys_for["stop"]) == {"Esc", "F9"}

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
