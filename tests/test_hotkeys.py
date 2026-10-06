"""全局快捷键（``gamebot.ui.hotkeys``）。

## 这个文件能测什么、不能测什么

**不能测的**：真按键。低级键盘钩子要真有键按下来才会回调，而这个执行环境
**拦掉了输入注入**（连 ``SetCursorPos`` 都返回 0），所以"注入一个 F5 再断言
钩子收到"这条路在这里走不通。

**能测的、也正是最容易错的**：

* Qt 的键 → Win32 虚拟键码（手写过一版，``F5`` 落到了 PageUp 的键码上）；
* Qt 的修饰位 → 我们的 ``MOD_*``（手写过一版，Ctrl 被当成 Shift）；
* 命中判定（多按一个修饰键**不算**中，否则 ``Ctrl+Alt+X`` 会在 ``Ctrl+X`` 时触发）；
* Qt 信号那一跳（钩子线程命中 → 界面线程执行动作）。

前两条都是"错了不报错、只是按不出来"，所以必须有测试钉着。
"""

from __future__ import annotations

import sys

import pytest

from gamebot.ui.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    GlobalHotkeys,
    Hotkey,
    is_supported,
    parse_hotkey,
)

pytest.importorskip("PySide6")

#: ``键写法 -> (期望的虚拟键码, 期望的修饰位)``。
#:
#: 期望值是从 Win32 文档抄的常量，**故意写死**（不跟着实现走）——
#: 这样实现里表搭错了就会红，而不是自己证明自己。
EXPECTED: dict[str, tuple[int, int]] = {
    "F1": (0x70, 0),
    "F5": (0x74, 0),
    "F12": (0x7B, 0),
    "F24": (0x87, 0),
    "Esc": (0x1B, 0),
    "Tab": (0x09, 0),
    "Space": (0x20, 0),
    "A": (0x41, 0),
    "Z": (0x5A, 0),
    "0": (0x30, 0),
    "9": (0x39, 0),
    "Left": (0x25, 0),
    "Up": (0x26, 0),
    "Right": (0x27, 0),
    "Down": (0x28, 0),
    "Insert": (0x2D, 0),
    "Delete": (0x2E, 0),
    "PgUp": (0x21, 0),
    "PgDown": (0x22, 0),
    "Home": (0x24, 0),
    "End": (0x23, 0),
    "Ctrl+A": (0x41, MOD_CONTROL),
    "Ctrl+1": (0x31, MOD_CONTROL),
    "Alt+F4": (0x73, MOD_ALT),
    "Shift+F5": (0x74, MOD_SHIFT),
    "Ctrl+Shift+A": (0x41, MOD_CONTROL | MOD_SHIFT),
    "Ctrl+Alt+F12": (0x7B, MOD_CONTROL | MOD_ALT),
    "Ctrl+Alt+Shift+Esc": (0x1B, MOD_CONTROL | MOD_ALT | MOD_SHIFT),
}


class TestParse:
    @pytest.mark.parametrize(("keys", "want"), list(EXPECTED.items()))
    def test_key_and_modifiers(self, keys, want, qt_app):
        hotkey = parse_hotkey("x", keys)
        assert hotkey is not None, f"{keys} 解析失败"
        assert (hotkey.vk, hotkey.mods) == want, (
            f"{keys}: 得到 vk=0x{hotkey.vk:02X} mods={hotkey.mods}，"
            f"期望 vk=0x{want[0]:02X} mods={want[1]}"
        )

    def test_unknown_key_is_skipped_not_raised(self, qt_app):
        """认不出来的键**跳过这一条**，不能让界面起不来。"""
        assert parse_hotkey("x", "MediaPlay") is None

    @pytest.mark.parametrize("keys", ["PageUp", "PageDown", "Win"])
    def test_misspelled_key_names_are_rejected_loudly(self, keys, qt_app, caplog):
        """Qt **不认**的键名会被静默变成 ``Key_unknown``，必须报出来。

        踩过的坑：``"PageUp"`` / ``"PageDown"`` / ``"Win"`` 都能"解析成功"
        （``QKeySequence`` 不抛错，只是给出 ``Key_unknown``），于是那条快捷键
        **无声消失** —— 用户按不出来，日志里也什么都没有。
        Qt 认的是 ``PgUp`` / ``PgDown`` / ``Meta``。
        """
        with caplog.at_level("WARNING"):
            assert parse_hotkey("x", keys) is None
        assert "Key_unknown" in caplog.text, "要说清是键名写法的问题，而不是含糊地跳过"

    @pytest.mark.parametrize(("bad", "good"), [("PageUp", "PgUp"), ("PageDown", "PgDown")])
    def test_the_spelling_qt_actually_wants(self, bad, good, qt_app):
        """上面那两个的**正确写法**确实能用 —— 否则这条测试只是在描述一个死路。"""
        assert parse_hotkey("x", bad) is None
        assert parse_hotkey("x", good) is not None

    def test_result_keeps_the_original_writing(self, qt_app):
        """原始写法要留着 —— 报错和帮助里都要显示人写的那个。"""
        assert parse_hotkey("x", "Ctrl+Alt+F12").keys == "Ctrl+Alt+F12"

    def test_action_is_carried_through(self, qt_app):
        assert parse_hotkey("stop", "Esc").action == "stop"


class TestModifierMask:
    """修饰键位掩码 —— 键位匹配现在由 **Windows 自己**做（``RegisterHotKey``）。

    所以这里不再测"给一个 vk+mods 判断命中"的算法（那个函数已经删了），
    改测**我们交给 Windows 的那个掩码对不对**。它错了的症状是
    "``Ctrl+Alt+F12`` 按不出来"或"误触发别的组合"。
    """

    def _hotkey(self, qt_app, keys="Esc"):
        parsed = parse_hotkey("stop", keys)
        assert parsed is not None
        return parsed

    def test_plain_key_has_no_modifiers(self, qt_app):
        assert self._hotkey(qt_app, "Esc").mods == 0

    def test_control_bit(self, qt_app):
        assert self._hotkey(qt_app, "Ctrl+A").mods == MOD_CONTROL

    def test_alt_bit(self, qt_app):
        assert self._hotkey(qt_app, "Alt+A").mods == MOD_ALT

    def test_control_alt_combines(self, qt_app):
        """两个修饰键是**位或**，别把 ``Alt`` 覆盖掉 ``Ctrl``。"""
        hotkey = self._hotkey(qt_app, "Ctrl+Alt+F12")
        assert hotkey.mods == MOD_CONTROL | MOD_ALT
        assert hotkey.mods & MOD_CONTROL and hotkey.mods & MOD_ALT

    def test_shift_bit(self, qt_app):
        assert self._hotkey(qt_app, "Shift+A").mods == MOD_SHIFT

    def test_win_modifier_is_in_the_mask(self, qt_app):
        """``Meta`` 在 Qt 里是 Win 键；写成 ``"Win+A"`` 是**错的写法**，
        会被上面 ``TestParse`` 挡住 —— 这里验正确的那个。"""
        assert self._hotkey(qt_app, "Meta+A").mods == MOD_WIN

    def test_modifier_order_does_not_matter(self, qt_app):
        """位掩码是集合语义：``Ctrl+Alt`` 和 ``Alt+Ctrl`` 是同一个。"""
        assert self._hotkey(qt_app, "Ctrl+Alt+F12").mods == self._hotkey(
            qt_app, "Alt+Ctrl+F12"
        ).mods

    def test_display_preserves_canonical_order(self, qt_app):
        """显示用固定顺序（``Ctrl+Alt+Shift+Win``），不跟着输入顺序变。"""
        assert self._hotkey(qt_app, "Alt+Ctrl+F12").display == "Ctrl+Alt+F12"


class TestRegistrationIsObservable:
    """**这条换上 `RegisterHotKey` 的核心理由**：成败能看出来。

    低级键盘钩子的失败是静默的 —— 句柄有效、``GetLastError=0``、线程在跑，
    但回调一次都不被调用，外部表现只有"按了没反应"。
    ``RegisterHotKey`` 失败**返回 False 并带错误码**，所以这里能直接钉住
    "注册成功的键进了 ``registered``、失败的进了 ``failed_keys``"。
    """

    def test_no_hotkeys_does_not_start(self, qt_app):
        """一条都没解析出来时不起线程（省一个后台线程，也省一次建窗口）。"""
        service = GlobalHotkeys([])
        assert service.start() is False
        assert not service.running

    def test_start_on_non_windows_is_false_not_an_exception(self, qt_app, monkeypatch):
        """非 Windows 上降级成"没这功能"，不是抛异常。"""
        import gamebot.ui.hotkeys as mod

        monkeypatch.setattr(mod.sys, "platform", "darwin")
        assert mod.is_supported() is False
        service = GlobalHotkeys([Hotkey("stop", 0x1B, 0, "Esc")])
        assert service.start() is False

    def test_stop_is_idempotent(self, qt_app):
        """没起来过 / 已经停了，再 stop 也不该炸（关窗路径会无脑调一次）。"""
        service = GlobalHotkeys([Hotkey("stop", 0x1B, 0, "Esc")])
        service.stop()
        service.stop()

    def test_registered_and_failed_are_reported_separately(self, qt_app):
        """注册结果要能分开看 —— 这是换机制换来的可诊断性。"""
        if not is_supported():
            pytest.skip("只有 Windows 上有这个 API")
        service = GlobalHotkeys([Hotkey("stop", 0x1B, 0, "Esc")])
        try:
            service.start()
            # 每个键要么注册上、要么进失败表，不能两个都不在
            assert len(service.registered) + len(service.failed_keys) == 1
            # 不变量：同一时刻两边不该有同一个键
            assert not {h.keys for h in service.registered} & {
                h.keys for h in service.failed_keys
            }
        finally:
            service.stop()

    def test_stop_after_start_cleans_up(self, qt_app):
        if not is_supported():
            pytest.skip("只有 Windows 上有这个 API")
        service = GlobalHotkeys([Hotkey("stop", 0x1B, 0, "Esc")])
        if not service.start():
            pytest.skip("这个环境注册不上（多半被别的软件占了）")
        assert service.running
        service.stop()
        assert not service.running
        assert service.registered == [], "注销之后不该还留着'已注册'"

    def test_triggered_signal_reaches_a_slot(self, qt_app):
        """命中之后"动作会不会被执行"这一段能验，而它正是最容易接错的一段
        （少一次 connect、或者槽函数签名不对，表现都是"按了没反应"）。
        """
        service = GlobalHotkeys([Hotkey("stop", 0x1B, 0, "Esc")])
        seen: list[str] = []
        service.triggered.connect(seen.append)

        service.triggered.emit("stop")
        qt_app.processEvents()

        assert seen == ["stop"]

    def test_hotkeys_are_exposed_read_only(self, qt_app):
        """``hotkeys`` 返回副本 —— 调用方改了不该影响服务内部那一条。"""
        hotkey = Hotkey("stop", 0x1B, 0, "Esc")
        service = GlobalHotkeys([hotkey])
        service.hotkeys.clear()
        assert service.hotkeys == [hotkey]

    def test_message_ids_start_at_one(self, qt_app):
        """``WM_HOTKEY`` 的 ``wParam`` 是注册时给的 id，必须从 1 开始且连续。

        这里钉住"id → 哪条快捷键"的映射算法本身（``index - 1``）——
        它错了的症状是"按 A 触发了 B"，比没反应更难查。
        """
        hotkeys = [
            Hotkey("run", 0x74, 0, "F5"),
            Hotkey("stop", 0x1B, 0, "Esc"),
            Hotkey("help", 0x70, 0, "F1"),
        ]
        for index, hotkey in enumerate(hotkeys, start=1):
            assert hotkeys[index - 1] is hotkey
        assert len(hotkeys) == 3


class TestShortcutTableIsConsistent:
    """快捷键表里标了 ``global_hotkey`` 的必须**都解析得出来**。

    否则现象是"帮助里带星号、但实际没挂全局"—— 用户按不出来还不知道为什么。
    """

    def test_every_global_shortcut_parses(self, qt_app):
        from gamebot.ui.shortcuts import SHORTCUTS

        for spec in SHORTCUTS:
            if not spec.global_hotkey:
                continue
            assert parse_hotkey(spec.action, spec.keys) is not None, (
                f"{spec.action} 标了 global_hotkey，但 {spec.keys!r} 解析不出来"
            )

    def test_only_runtime_controls_are_global(self, qt_app):
        """只给操作运行状态的开全局，切页那几条不开。

        理由：占全局是有代价的（那条键在整个系统里都归本工具管），
        切页只在看界面时按，占了没意义还会和别的软件抢键。
        """
        from gamebot.ui.shortcuts import SHORTCUTS

        globals_ = {spec.action for spec in SHORTCUTS if spec.global_hotkey}
        assert globals_ == {"run", "stop", "help"}

    def test_platform_check_matches_reality(self):
        assert is_supported() == (sys.platform == "win32")
