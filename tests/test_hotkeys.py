"""全局快捷键 —— 键的解析、监听器的启停、以及"实际生效的键"可观测。

## 这一版换掉了机制，所以测试也换了重点

原来测的是 ``RegisterHotKey``（虚拟键码表、修饰位掩码、被占用后退到备选）。
现在走 ``pynput`` 的键盘钩子，那些内部结构**整个不存在了**：

* 没有虚拟键码表 —— 键名按 ``+`` 拆开、各自换算就行（:func:`parse_hotkey`）；
* 没有修饰位掩码 —— ``pynput`` 要的是 ``"<ctrl>+<alt>+<f5>"`` 这种字符串；
* **没有"被占用"这回事** —— 钩子不注册、不占键，所以首选永远生效。
  原来那条"备选接管"的测试因此没有意义了（换成"只监听首选"）。

## 真正要钉住的四件事

1. **换算对**：Qt 写法 -> ``pynput`` 写法（这是唯一容易写错的地方）；
2. **认不出来就出声**：不认的键名必须 warning + 跳过，而不是静默不生效；
3. **启停可观测**：``running`` / ``registered`` 准不准（"没生效"要看得出来）；
4. **不吞键**：这是换机制的根本理由 —— 见 :class:`TestItDoesNotSwallowKeys`。
"""

from __future__ import annotations

import pytest

from gamebot.ui.hotkeys import (
    GlobalHotkeys,
    Hotkey,
    HotkeyPlan,
    is_supported,
    parse_hotkey,
)
from gamebot.ui.shortcuts import SHORTCUTS


class TestParse:
    """Qt 写法 -> ``pynput`` 写法。"""

    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("F5", "<f5>"),
            ("F9", "<f9>"),
            ("F12", "<f12>"),
            ("F24", "<f24>"),
            ("Ctrl+Alt+F5", "<ctrl>+<alt>+<f5>"),
            ("Ctrl+Alt+F9", "<ctrl>+<alt>+<f9>"),
            ("Ctrl+Shift+P", "<ctrl>+<shift>+p"),
            ("Win+X", "<cmd>+x"),
            ("A", "a"),
            ("1", "1"),
            ("Esc", "esc"),
            ("Enter", "enter"),
            ("Space", "space"),
            ("Delete", "delete"),
        ],
    )
    def test_qt_writing_becomes_pynput_writing(self, written, expected):
        hotkey = parse_hotkey("act", written)
        assert hotkey is not None, f"{written!r} 应该能解析"
        assert hotkey.pynput_keys == expected

    def test_result_keeps_the_original_writing(self):
        """``keys`` 保留 Qt 写法 —— 界面/帮助显示的是它，不是 ``<f9>``。"""
        hotkey = parse_hotkey("act", "Ctrl+Alt+F5")
        assert hotkey is not None
        assert hotkey.keys == "Ctrl+Alt+F5"
        assert hotkey.display == "Ctrl+Alt+F5"

    def test_action_is_carried_through(self):
        hotkey = parse_hotkey("stop", "F9")
        assert hotkey is not None
        assert hotkey.action == "stop"

    def test_modifier_order_is_preserved(self):
        """修饰键**保持书写顺序**。

        ``pynput`` 把 ``"<ctrl>+<alt>+<f5>"`` 当字符串键去匹配组合，
        所以这里不做重排 —— 重排会让"我们监听的键"和"配置里写的键"
        在日志/界面里显示成两种样子，反而更难对照。
        """
        hotkey = parse_hotkey("act", "Ctrl+Alt+F5")
        assert hotkey is not None
        assert hotkey.pynput_keys == "<ctrl>+<alt>+<f5>"

    def test_spaces_around_plus_are_tolerated(self):
        hotkey = parse_hotkey("act", " Ctrl + Alt + F5 ")
        assert hotkey is not None
        assert hotkey.pynput_keys == "<ctrl>+<alt>+<f5>"


class TestUnparseableIsLoud:
    """认不出来必须"跳过 + 出声"。静默跳过 = "我明明写了却没生效"。"""

    @pytest.mark.parametrize(
        "written",
        ["", "   ", "PageUp", "F25", "F0", "Hyper+X", "Ctrl+", "Ctrl+Foo"],
    )
    def test_unparseable_returns_none(self, written):
        assert parse_hotkey("act", written) is None

    def test_it_logs_a_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            parse_hotkey("act", "PageUp")
        assert caplog.records, "认不出来却没出声 —— 这正是最难查的那种失败"
        assert "PageUp" in caplog.text


class TestListenerIsObservable:
    """启停状态要能读出来 —— "按了没反应"必须能查。"""

    def _plan(self, action: str = "run", keys: str = "F5") -> HotkeyPlan:
        hotkey = parse_hotkey(action, keys)
        assert hotkey is not None
        return HotkeyPlan(action=action, candidates=(hotkey,))

    def test_no_plans_does_not_start(self):
        service = GlobalHotkeys([])
        assert service.start() is False
        assert service.running is False

    def test_start_registers_and_running_reflects_it(self, qt_app):
        service = GlobalHotkeys([self._plan()])
        try:
            if not service.start():  # pragma: no cover - pynput 起不来时跳过
                pytest.skip("这个环境下 pynput 监听器起不来")
            assert service.running is True
            assert [h.keys for h in service.registered] == ["F5"]
        finally:
            service.stop()

    def test_only_the_first_candidate_is_listened_to(self, qt_app):
        """候选只取首选 —— 钩子不存在"被占用"，备选永远用不上。"""
        first = parse_hotkey("run", "F5")
        second = parse_hotkey("run", "Ctrl+Alt+F5")
        assert first is not None and second is not None
        service = GlobalHotkeys([HotkeyPlan("run", (first, second))])
        try:
            if not service.start():  # pragma: no cover
                pytest.skip("这个环境下 pynput 监听器起不来")
            assert [h.keys for h in service.registered] == ["F5"]
        finally:
            service.stop()

    def test_stop_is_idempotent(self):
        service = GlobalHotkeys([self._plan()])
        service.stop()
        service.stop()
        assert service.running is False

    def test_stop_clears_registered(self, qt_app):
        service = GlobalHotkeys([self._plan()])
        if service.start():
            service.stop()
        assert service.registered == []
        assert service.running is False

    def test_plans_are_exposed_read_only(self):
        service = GlobalHotkeys([self._plan()])
        plans = service.plans
        plans.clear()
        assert len(service.plans) == 1, "外部改返回值不该影响内部状态"

    def test_the_same_key_twice_keeps_the_first_action(self):
        """两个动作抢同一个键：留住先声明的，并记进 ``failed_keys``。"""
        service = GlobalHotkeys([self._plan("run", "F5"), self._plan("stop", "F5")])
        try:
            if not service.start():  # pragma: no cover
                pytest.skip("这个环境下 pynput 监听器起不来")
            assert [h.action for h in service.registered] == ["run"]
            assert [h.action for h in service.failed_keys] == ["stop"]
        finally:
            service.stop()

    def test_triggered_signal_reaches_a_slot(self, qt_app):
        """钩子回调只发信号（跨线程安全），槽在这里收到。"""
        seen: list[str] = []
        service = GlobalHotkeys([self._plan()])
        service.triggered.connect(seen.append)
        try:
            service._fire("run")  # 直接触发，不等真按键
            assert seen == ["run"]
        finally:
            service.stop()


class TestItDoesNotSwallowKeys:
    """**换机制的根本理由**：旧方案（``RegisterHotKey``）会把键吞掉。

    ``pynput`` 装的是监听钩子 —— **不注册、不占用**，所以：

    * 键被别的软件用着也照样能监听（旧方案会注册失败、完全没反应）；
    * 游戏自己仍然收得到这个键（旧方案会让游戏也收不到）。

    这条测试钉的是"我们没有偷偷用回会吞键的那套 API"。
    """

    def test_no_win32_hotkey_registration_in_the_code(self):
        """**代码里**不许出现 ``RegisterHotKey`` / ``UnregisterHotKey``。

        只看代码行，不看注释和 docstring —— 模块开头正是用
        "原来那套会吞键"来解释为什么换掉的，那段说明必须留着。
        """
        import ast
        import pathlib

        source = pathlib.Path("src/gamebot/ui/hotkeys.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        # 把所有字符串字面量挖掉（docstring / 注释在 AST 里就是常量），
        # 剩下的标识符和属性名才是"真的调用了什么"。
        code_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                code_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                code_names.add(node.attr)
        for banned in ("RegisterHotKey", "UnregisterHotKey"):
            assert banned not in code_names, (
                f"代码里还在调 {banned} —— 那套会吞键、也会被别的软件占用挡住"
            )
        assert "WM_HOTKEY" not in code_names

    def test_it_uses_pynput(self):
        import pathlib

        source = pathlib.Path("src/gamebot/ui/hotkeys.py").read_text(encoding="utf-8")
        assert "pynput" in source
        assert "GlobalHotKeys" in source


class TestShortcutTableIsConsistent:
    """``SHORTCUTS`` 那张表和这套机制对得上。"""

    def test_every_global_shortcut_parses(self):
        for spec in SHORTCUTS:
            if not spec.global_hotkey:
                continue
            assert parse_hotkey(spec.action, spec.keys) is not None, (
                f"{spec.action} 的全局键 {spec.keys!r} 解析不出来"
            )

    def test_only_runtime_controls_are_global(self):
        """只有操作运行状态的那几条挂全局 —— 切页的挂全局没意义。"""
        global_actions = {s.action for s in SHORTCUTS if s.global_hotkey}
        assert global_actions <= {"run", "stop", "help"}
        assert "run" in global_actions and "stop" in global_actions

    def test_platform_check_matches_reality(self):
        """``is_supported`` 说的是实话（pynput 装好了就是 True）。"""
        import importlib.util

        assert is_supported() == (importlib.util.find_spec("pynput") is not None)


class TestHotkeyDataclass:
    def test_display_is_the_qt_writing(self):
        hotkey = Hotkey(action="run", keys="F5", pynput_keys="<f5>")
        assert hotkey.display == "F5"
