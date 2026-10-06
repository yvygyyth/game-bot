"""界面上的按钮/下拉框状态 —— 四条用户报过的问题。

## 为什么单独一组

`test_ui_run.py` 里原来那条 `TestStopping` 只断言了 ``_engine_running``
（内部状态），**没断言按钮**。而用户报的正是界面上看到的东西：

* "停止后没办法再开始了，按钮 disable 了"；
* "软件选了 UI 看不到的，选择会卡住，重新选不了"。

内部状态对、界面状态错，就是这一类。所以这里一律断言**控件本身的
``isEnabled()`` / ``currentText()``**，而不是背后的标志位。
"""

from __future__ import annotations

import time

import pytest

from gamebot.params import FormSpec
from gamebot.ui.registry import ScriptEntry

pytest.importorskip("PySide6")

import gamebot.bootstrap as bs
from gamebot.ui import window as win_mod
from gamebot.ui.panels import controls as controls_mod

from .test_ui_run import _entry


@pytest.fixture
def ui(qt_app, tmp_path, monkeypatch):
    """一个真实主窗口，脚本假、后端假、模板检查放行。"""
    entry = _entry()
    monkeypatch.setattr(win_mod, "load_scripts", lambda: ([entry], ""))
    monkeypatch.setattr(bs, "check_templates", lambda cfg, sc: [])

    main = win_mod.MainWindow()
    main._target_window_ok = lambda e: True
    qt_app.processEvents()
    try:
        yield main, entry
    finally:
        if main._engine_running:
            main._request_engine_stop()
            _wait(qt_app, lambda: not main._engine_running)
        main.keymap.stop()
        main.close()
        qt_app.processEvents()


def _wait(qt_app, predicate, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestStartButtonAfterStop:
    """用户报："停止后没办法再开始了，按钮 disable 了"。

    ## 根因（顺序敏感 + 静默错）

    ``_on_engine_finished`` 里原来是：

        self.controls.set_running(False)       # 算 "not running and self._runnable"
        self.controls.note_runnable(True)      # _runnable 这时还是 False

    ``_runnable`` 在开跑那一刻被置为 False（防止运行中再点开始），所以解锁时
    它还是 False → **开始按钮永远点不亮**，而且没有任何报错。

    现在解锁只看 ``_has_script``（有没有选脚本），和"在不在跑"正交，
    先调后调都一样。
    """

    def test_start_button_is_reenabled_after_stop(self, qt_app, ui) -> None:
        main, _ = ui
        assert main.controls.start_btn.isEnabled(), "选完脚本就该能开始"

        main._on_start()
        assert _wait(qt_app, lambda: main._engine_running)
        assert not main.controls.start_btn.isEnabled(), "运行中开始按钮该灰"

        main._request_engine_stop()
        assert _wait(qt_app, lambda: not main._engine_running)

        assert main.controls.start_btn.isEnabled(), (
            "停止之后开始按钮必须重新可用 —— 这就是用户报的那个 bug"
        )
        assert not main.controls.stop_btn.isEnabled(), "没在跑，停止该灰"

    def test_can_run_a_second_time(self, qt_app, ui) -> None:
        """按钮亮了还不够，**真的能再跑一次**才算修好。"""
        main, _ = ui
        main._on_start()
        assert _wait(qt_app, lambda: main._engine_running)
        main._request_engine_stop()
        assert _wait(qt_app, lambda: not main._engine_running)

        main._on_start()
        assert _wait(qt_app, lambda: main._engine_running), "第二次开不起来"
        main._request_engine_stop()
        assert _wait(qt_app, lambda: not main._engine_running)

    def test_script_and_window_controls_unlock_after_stop(self, qt_app, ui) -> None:
        main, _ = ui
        main._on_start()
        assert _wait(qt_app, lambda: main._engine_running)
        for name in ("script", "window", "detect", "check_btn"):
            assert not getattr(main.controls, name).isEnabled(), f"{name} 运行中该锁住"

        main._request_engine_stop()
        assert _wait(qt_app, lambda: not main._engine_running)
        for name in ("script", "window", "detect", "check_btn"):
            assert getattr(main.controls, name).isEnabled(), f"{name} 停止后该解锁"

    def test_unlock_does_not_depend_on_call_order(self, qt_app, ui) -> None:
        """解锁的两种调用顺序结果要一样。

        这正是原来那个 bug 的本质：``set_running(False)`` 和
        ``note_runnable(True)`` 谁先谁后，结果不同。
        """
        main, _ = ui
        main.controls.set_running(True)
        main.controls.set_running(False)
        main.controls.note_runnable(True)
        assert main.controls.start_btn.isEnabled()

        main.controls.set_running(True)
        main.controls.note_runnable(True)
        main.controls.set_running(False)
        assert main.controls.start_btn.isEnabled(), "换个顺序也该是亮的"


class TestWindowSelectionRefresh:
    """用户报："软件选了 UI 看不到的，选择会卡住，重新选不了"。

    ## 根因

    下拉框是**可编辑**的（能手打标题），所以
    ``setCurrentText(不在列表里的标题)`` **不报错**：显示的文字改了，
    但 ``currentIndex`` 还停在旧位置 —— 于是进入"**显示 A、实际选中 B**"
    的状态，用户看到"选了列表里没有的东西，而且改不回去"。
    """

    def _fake_windows(self, monkeypatch, titles):
        class _Region:
            x = y = 0
            w, h = 640, 360

        class _Window:
            region = _Region()

            def __init__(self, title: str) -> None:
                self.title = title

        fake = [_Window(t) for t in titles]
        monkeypatch.setattr(controls_mod, "_list_windows", lambda keyword="": fake)

    def test_phantom_selection_is_cleared_on_refresh(self, qt_app, monkeypatch, ui) -> None:
        main, _ = ui
        controls = main.controls
        self._fake_windows(monkeypatch, ["窗口甲", "窗口乙"])
        controls.refresh_windows()
        assert controls.window.count() == 2

        # 用户手打了一个不存在的标题（可编辑下拉框允许这么做）
        controls.window.setCurrentText("根本不存在-zzz")
        controls.refresh_windows()

        assert controls.window.currentText() == "", (
            "不在列表里的选择必须被清空 —— 否则就是'显示 A 实际选中 B'那个假状态"
        )
        assert controls.window.currentIndex() == -1

    def test_user_can_select_again_after_the_phantom(self, qt_app, monkeypatch, ui) -> None:
        main, _ = ui
        controls = main.controls
        self._fake_windows(monkeypatch, ["窗口甲", "窗口乙"])
        controls.window.setCurrentText("不存在-zzz")
        controls.refresh_windows()

        controls.window.setCurrentIndex(1)
        assert controls.window_title == "窗口乙", "清空之后必须还能正常选"
        assert "客户区" in controls.coords.text()

    def test_existing_selection_survives_a_refresh(self, qt_app, monkeypatch, ui) -> None:
        """窗口还在时，刷新不该把用户的选择弄丢。"""
        main, _ = ui
        controls = main.controls
        self._fake_windows(monkeypatch, ["窗口甲", "窗口乙"])
        controls.refresh_windows()
        controls.window.setCurrentIndex(1)

        controls.refresh_windows()

        assert controls.window_title == "窗口乙", "刷新把还存在的选择弄丢了"

    def test_refresh_does_not_auto_select_the_first(self, qt_app, monkeypatch, ui) -> None:
        """没选过就保持没选 —— 自动选中会被下游当成"用户选了它"。"""
        main, _ = ui
        controls = main.controls
        self._fake_windows(monkeypatch, ["窗口甲", "窗口乙"])
        controls.refresh_windows()

        assert controls.window.currentText() == ""
        assert controls.window_title == ""


class TestCheckIsDiscoverable:
    """用户报："我不知道 UI 界面的检查按钮在检查什么"。

    根因有两半：tooltip 只说了一句笼统的话，而且**选完脚本不自动查** ——
    "缺模板"这种事要点了按钮才知道。现在选完脚本自动查一次，结论进状态栏。
    """

    def test_tooltip_says_what_is_checked(self, qt_app, ui) -> None:
        main, _ = ui
        tip = main.controls.check_btn.toolTip()
        assert "定义自洽" in tip
        assert "模板文件" in tip
        assert "不查" in tip, "还要说清它**不**查什么（识别准不准）"

    def test_selecting_a_script_runs_the_check_automatically(self, qt_app, ui) -> None:
        main, _ = ui
        main.controls.select_script(main.controls.script.currentData().key)
        qt_app.processEvents()

        assert "检查" in main._status.text(), (
            f"选完脚本该把检查结论写进状态栏，实际是 {main._status.text()!r}"
        )

    def test_status_bar_reports_missing_templates(self, qt_app, monkeypatch, ui) -> None:
        """缺模板要**在状态栏就能看见**，不是只写进「检查输出」页。"""
        main, _ = ui
        monkeypatch.setattr(bs, "check_templates", lambda cfg, sc: ["a.png", "b.png"])
        main._run_check(quiet=True)

        assert "缺 2 个模板文件" in main._status.text()

    def test_quiet_check_does_not_switch_pages(self, qt_app, ui) -> None:
        """自动那次不切页 —— 否则会打断用户刚选脚本的动作。"""
        main, _ = ui
        before = main.workspace.currentIndex()
        main._run_check(quiet=True)
        assert main.workspace.currentIndex() == before

    def test_manual_check_switches_to_output(self, qt_app, ui) -> None:
        main, _ = ui
        main._run_check()
        qt_app.processEvents()
        assert main.workspace.currentWidget() is main._check_page


class TestScriptSelectionBookkeeping:
    def test_selecting_records_has_script(self, qt_app, ui) -> None:
        main, entry = ui
        main.controls.select_script(entry.key)
        assert main.controls._has_script is True

    def test_clearing_records_no_script(self, qt_app, ui) -> None:
        main, entry = ui
        main.controls.select_script(entry.key)
        main._on_script_changed(None)
        assert main.controls._has_script is False
        assert not main.controls.start_btn.isEnabled(), "没选脚本就不能开始"


class TestFormSpecUnchanged:
    """占位：确保这个文件没有污染表单那块（它俩都在右侧栏）。"""

    def test_params_panel_present(self, qt_app, ui) -> None:
        main, _ = ui
        assert isinstance(main.params.form, FormSpec)

    def test_entry_is_a_script_entry(self, qt_app, ui) -> None:
        _main, entry = ui
        assert isinstance(entry, ScriptEntry)
