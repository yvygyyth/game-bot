"""进程完整性级别 —— 判断"我能不能给那个窗口发输入"。

## 为什么值得有测试

这个模块存在的理由是一个**排查了很久的静默失败**：

* 鼠标指针**真的**移到了目标点（``SetCursorPos`` 不受 UIPI 限制）；
* ``SendInput`` 返回**成功**、``GetLastError() == 0``；
* 而游戏窗口**什么都收不到**。

看起来完全像"坐标算错了"或"游戏不认合成输入"。真相是 Windows 的 UIPI：
**低完整性进程不能给高完整性窗口发输入**。这个项目在这上面栽过 ——
所以判据必须有测试守着，而且提示必须够清楚。

## 怎么测（不依赖机器状态）

本机真实级别是能读到的，但**不能拿它当断言**（换台机器就红）。
所以：

* 真实的 ``level_of_pid`` 只验"读得到、是个合法级别"；
* UIPI 的判断逻辑用**注入的级别**验（monkeypatch 掉两个读取函数），
  这样"低 -> 高要报警、高 -> 低不报警"是可复现的。
"""

from __future__ import annotations

import os
import sys

import pytest

from gamebot.utils.integrity import (
    IntegrityLevel,
    check_integrity,
    level_of_pid,
    level_of_window,
)

WINDOWS = sys.platform == "win32"


class TestIntegrityLevel:
    def test_names_are_mapped(self):
        assert IntegrityLevel(0x1000).name == "Low"
        assert IntegrityLevel(0x2000).name == "Medium"
        assert IntegrityLevel(0x3000).name == "High"

    def test_unknown_value_falls_back_to_hex(self):
        """没见过的级别也要能显示 —— 不能因此崩掉。"""
        assert "0x3500" in IntegrityLevel(0x3500).name

    def test_equality_is_by_value(self):
        assert IntegrityLevel(0x2000) == IntegrityLevel(0x2000, "随便什么名字")
        assert IntegrityLevel(0x1000) != IntegrityLevel(0x2000)

    def test_comparable_by_value(self):
        """UIPI 的判断就是比大小 —— 这个顺序必须对。"""
        assert IntegrityLevel(0x1000).value < IntegrityLevel(0x2000).value
        assert IntegrityLevel(0x2000).value < IntegrityLevel(0x3000).value


class TestReadingRealProcesses:
    @pytest.mark.skipif(not WINDOWS, reason="完整性级别是 Windows 概念")
    def test_own_process_has_a_readable_level(self):
        """本进程的级别一定读得到（它是给用户看的第一条信息）。"""
        level = level_of_pid(os.getpid())
        assert level is not None, "连自己的级别都读不到，提示就没法给出去了"
        assert level.name in {"Low", "Medium", "Medium+", "High", "System", "Untrusted"}

    @pytest.mark.skipif(not WINDOWS, reason="完整性级别是 Windows 概念")
    def test_a_bogus_pid_returns_none_not_an_exception(self):
        """读不到就返回 None —— **这个模块自己不该成为新的失败点**。"""
        assert level_of_pid(0x7FFFFFF0) is None

    @pytest.mark.skipif(not WINDOWS, reason="完整性级别是 Windows 概念")
    def test_a_bogus_hwnd_returns_none(self):
        assert level_of_window(0) is None


class TestCheckIntegrity:
    """UIPI 判断本身 —— 用注入的级别验，不依赖本机状态。"""

    def _patch(self, monkeypatch, mine: int, theirs: int, *, hwnd: int = 12345):
        monkeypatch.setattr(
            "gamebot.utils.integrity.level_of_pid", lambda _pid: IntegrityLevel(mine)
        )
        monkeypatch.setattr(
            "gamebot.utils.integrity.level_of_window",
            lambda _hwnd: IntegrityLevel(theirs),
        )
        import win32gui

        monkeypatch.setattr(win32gui, "FindWindow", lambda *_a: hwnd)
        return hwnd

    @pytest.mark.skipif(not WINDOWS, reason="UIPI 是 Windows 概念")
    def test_low_sender_to_medium_window_warns(self, monkeypatch):
        """**这条就是那个 bug**：低 -> 高必须报警。"""
        self._patch(monkeypatch, 0x1000, 0x2000)
        warning = check_integrity("名将杀")
        assert warning is not None, "低完整性给高完整性窗口发输入，必须报警"
        assert "Low" in warning and "Medium" in warning
        assert "UIPI" in warning
        # 提示里必须带**怎么办**，光说不行没用
        assert "终端" in warning

    @pytest.mark.skipif(not WINDOWS, reason="UIPI 是 Windows 概念")
    def test_same_level_is_fine(self, monkeypatch):
        self._patch(monkeypatch, 0x2000, 0x2000)
        assert check_integrity("名将杀") is None

    @pytest.mark.skipif(not WINDOWS, reason="UIPI 是 Windows 概念")
    def test_higher_sender_to_lower_window_is_fine(self, monkeypatch):
        """高给低发是允许的（管理员进程能给普通窗口发输入）。"""
        self._patch(monkeypatch, 0x3000, 0x2000)
        assert check_integrity("名将杀") is None

    def test_no_window_title_means_no_check(self):
        """没给标题就没什么可判的 —— 不要瞎猜。"""
        assert check_integrity("") is None
        assert check_integrity("这个窗口根本不存在-9f8a7b6c") is None

    @pytest.mark.skipif(not WINDOWS, reason="UIPI 是 Windows 概念")
    def test_unreadable_level_does_not_warn(self, monkeypatch):
        """级别读不出来时**不猜** —— 宁可不说，也别误报。"""
        monkeypatch.setattr("gamebot.utils.integrity.level_of_window", lambda _h: None)
        assert check_integrity("名将杀") is None


class TestBootstrapAndDiagnosticsUseIt:
    """判据要接在**用户会看到的地方** —— 否则等于没有。"""

    def test_bootstrap_checks_at_assembly_time(self):
        """装配 Session 时就检查一次（启动日志里能直接看到）。"""
        import pathlib

        source = pathlib.Path("src/gamebot/bootstrap.py").read_text(encoding="utf-8")
        assert "check_integrity" in source
        assert "log.warning" in source

    def test_doctor_reports_it(self):
        """``games doctor`` 是跑真机前的自检入口，必须报出来。

        （``poke`` / ``where`` 已经删了 —— 诊断命令留一个统一的就够。）
        """
        import pathlib

        source = pathlib.Path("games/doctor.py").read_text(encoding="utf-8")
        assert "check_integrity" in source

    def test_window_shows_it_in_the_log_panel(self):
        """界面「开始」之前把它写进日志面板（那里第一眼就能看到）。"""
        import pathlib

        source = pathlib.Path("src/gamebot/ui/window.py").read_text(encoding="utf-8")
        assert "_warn_about_integrity" in source
        assert "check_integrity" in source
