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
        """**一个动作一个键。**

        曾经给 ``stop`` 配过 ``Esc`` + ``F9`` 两个键（想的是"一个被占还有一个"），
        后来去掉了：帮助里两行写着同一件事像两个功能，而且 ``RegisterHotKey``
        会吞键，多占一个系统级的键就多一份副作用。

        "首选键被占"现在由 ``global_fallback`` 处理 —— 那是**同一个键的备选写法**，
        不是第二个键位（界面内仍然只绑一个键）。
        """
        actions = [spec.action for spec in SHORTCUTS]
        assert len(actions) == len(set(actions)), f"有重复的动作: {actions}"

    def test_every_entry_is_described(self):
        """没有说明的快捷键，在 F1 帮助里就是一串看不懂的字母。"""
        for spec in SHORTCUTS:
            assert spec.keys.strip(), spec
            assert spec.label.strip(), spec

    def test_core_actions_exist(self):
        """这几个是承诺过的，别不小心删了。"""
        actions = {spec.action for spec in SHORTCUTS}
        assert {"run", "stop", "help"} <= actions

    def test_every_global_shortcut_has_a_fallback(self):
        """每条全局快捷键**都要有备选键**。

        理由不是预防性设计 —— 是实测出来的：这台机器上裸 ``F5`` / ``F9`` /
        ``F12`` / ``Esc`` **全都注册不上**（被别的软件占了），``Ctrl+Alt+*``
        全都可以。没有备选就等于"这条全局快捷键在有些机器上永远不生效"，
        而且失败是静默的。
        """
        for spec in SHORTCUTS:
            if spec.global_hotkey:
                assert spec.global_fallback, f"{spec.action} 没有备选键"
                assert spec.global_fallback != spec.keys

    def test_fallback_uses_modifiers(self):
        """备选键必须**带修饰键** —— 裸键被占的概率高得离谱，那正是要备选的原因。"""
        for spec in SHORTCUTS:
            if spec.global_fallback:
                assert "+" in spec.global_fallback, (
                    f"{spec.action} 的备选键 {spec.global_fallback!r} 也是裸键，"
                    "起不到备选作用"
                )

    def test_fallback_key_is_parseable(self, qt_app):
        """备选键也得能解析成虚拟键码 —— 写错了它永远轮不上，等于没有。"""
        from gamebot.ui.hotkeys import parse_hotkey

        for spec in SHORTCUTS:
            if not spec.global_fallback:
                continue
            parsed = parse_hotkey(spec.action, spec.global_fallback)
            assert parsed is not None, f"{spec.action} 的备选键解析不出来"
            assert parsed.mods, f"{spec.action} 的备选键没解析出修饰位"

    def test_stop_is_escape_and_run_is_f5(self):
        """用户问的就是这个，钉住。

        （``stop`` 曾经还有 ``F9`` 做别名，后来去掉了 —— 见上面
        ``test_actions_are_unique`` 的说明。"被占用"现在由
        ``global_fallback`` 处理。）
        """
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
