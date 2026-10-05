"""界面冒烟测试：**真的走一遍「点开始 → 跑 → 点停止」**。

## 为什么必须有这个文件

界面上那些槽函数（``_on_start`` / ``_on_stop``）在 ``_wire()`` 里被信号连着，
但**没有任何测试点过它们** —— 于是 ``_engine_tick_relay`` 这种"访问了不存在的
属性"的错（正确拼法是 ``_engineTickRelay``）一路溜到用户手里：
点「开始」直接 AttributeError，而全部 517 个用例照样全绿。

教训很直白：**"接线的两头各自都测过了"不等于"这条线通"**。
信号连接、按钮到槽、跨线程那条路，只有真按一下才算验过。

这里不用真游戏：脚本的 ``build_config`` 返回假后端配置，于是整条路
（装配 -> 工作线程 -> tick -> 停止 -> 收摊）都能在无头环境里跑完。
"""

from __future__ import annotations

import time

import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.query import ImageQuery
from gamebot.atomic.session import BaseSession
from gamebot.config.schema import AppConfig, BackendKind
from gamebot.flow.graph import Graph, Node
from gamebot.flow.scenario import Scenario
from gamebot.state.page import Page, PageTree
from gamebot.types import Point

from .conftest import FakeMatcher, FakeReader


# --------------------------------------------------------------------------- #
# 一个最小的假脚本（不碰真游戏）
# --------------------------------------------------------------------------- #
def _tree() -> PageTree:
    tree = PageTree()
    # 用 Page 对象，不是字典 —— ``add_many`` 收的是 Page（字典那条路是
    # flow.loader 的活，状态层不认）。
    tree.add(Page("home", queries=(ImageQuery("home.png", confidence=0.9),)))
    return tree


def _scenario(max_ticks: int = 3, interval: float = 0.01) -> Scenario:
    graph = Graph(initial="home")
    graph.add_node(Node("home", page="home"))
    scenario = Scenario(name="fake-ui", tree=_tree(), graph=graph)
    scenario.options.max_ticks = max_ticks
    scenario.options.tick_interval = interval
    scenario.validate()
    return scenario


def _config() -> AppConfig:
    config = AppConfig.defaults()
    config.screen.backend = BackendKind.FAKE
    config.screen.source_size = (640, 360)
    config.paths.screenshots = config.paths.root / "logs" / "screenshots"
    return config


class _Spec:
    """冒充业务层的 ``ScriptSpec``（界面只用到这几个属性/方法）。

    ``prepare`` 也给上：``load_details`` 会读它来判断"这个脚本有没有资源脚本"，
    少一个属性界面就会在选择脚本时炸 —— 这正是真 ``ScriptSpec`` 的接口面，
    假对象要照着补齐。
    """

    def __init__(self, *, max_ticks: int = 3) -> None:
        self._max_ticks = max_ticks
        self.prepare = None

    def build_config(self) -> AppConfig:
        return _config()

    def build_scenario(self) -> Scenario:
        return _scenario(max_ticks=self._max_ticks)

    def selftest(self) -> list[str]:
        return []


def _entry():
    from gamebot.ui.registry import ScriptEntry

    return ScriptEntry(
        key="fake/ui",
        game="fake",
        slug="ui",
        title="假脚本",
        description="界面冒烟用",
        spec=_Spec(),
    )


@pytest.fixture
def ui(qt_app, tmp_path, monkeypatch):
    """造一个真实的主窗口，但里面的脚本是假的、后端是假的。

    ``Session`` 走内存后端：``build_context`` 默认会用 ``build_session_from_config``
    去建真后端（Windows 会去找真窗口），所以这里把 Session 换掉。
    """
    from gamebot import bootstrap as bs
    from gamebot.ui import window as win_mod

    entry = _entry()
    monkeypatch.setattr(win_mod, "load_scripts", lambda: ([entry], ""))
    monkeypatch.setattr(win_mod, "load_details", win_mod.load_details)

    real_build = bs.build_session_from_config

    def fake_session(config, *, recorder=None):
        matcher = recorder.wrap_matcher(FakeMatcher(matches={"home.png": (Point(1, 1), 0.99)}))
        return BaseSession(
            build_fake_backends(size=(640, 360)),
            matcher=matcher,
            reader=recorder.wrap_reader(FakeReader()) if recorder else FakeReader(),
        )

    monkeypatch.setattr(bs, "build_session_from_config", fake_session)
    # 「开始」在缺模板时会**拒绝启动**（刻意的：模板少一张的表现是"跑到某个
    # 分支卡住"，早炸早好）。假脚本没有真模板文件，所以把那个检查也换掉 ——
    # 否则测的就不是"开始这条路"，而是"我给假脚本配齐模板没有"。
    # 注意要打在 bootstrap 上：window 里是**函数内**导入的（`from ..bootstrap
    # import check_templates`），打在 window 模块上会 AttributeError。
    monkeypatch.setattr(bs, "check_templates", lambda cfg, sc: [])

    main = win_mod.MainWindow()
    main.resize(900, 700)
    main.show()
    qt_app.processEvents()
    try:
        yield main, entry, real_build
    finally:
        main.close()
        qt_app.processEvents()


def _wait_until(qt_app, predicate, timeout: float = 8.0) -> bool:
    """转 Qt 事件循环直到条件成立（跨线程的信号要靠它才送得到界面线程）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --------------------------------------------------------------------------- #
class TestStartStop:
    def test_start_button_actually_runs_the_engine(self, qt_app, ui) -> None:
        """点「开始」真的能起来 —— 就是这条能抓住 ``_engine_tick_relay`` 那个错。"""
        main, _entry, _ = ui
        main._on_start()

        assert main._engine_running is True
        # 引擎在工作线程里跑，跑完会发 finished -> 界面解锁
        assert _wait_until(qt_app, lambda: not main._engine_running), "引擎没能在超时内跑完"
        report = main._last_report
        assert report is not None
        assert report.ticks > 0

    def test_start_twice_is_ignored(self, qt_app, ui) -> None:
        """运行中再点开始不该起第二个引擎。"""
        main, _, _ = ui
        main._on_start()
        assert main._engine_running is True

        main._on_start()  # 不该抛，也不该重入
        assert main._engine_running is True

        _wait_until(qt_app, lambda: not main._engine_running)

    def test_stop_when_not_running_is_a_noop(self, qt_app, ui) -> None:
        """Esc / 停止按钮在空闲时按下去是安全的空操作。"""
        main, _, _ = ui
        assert main._engine_running is False
        main._on_stop()  # 不抛就行

    def test_close_while_running_does_not_explode(self, qt_app, ui) -> None:
        """跑着的时候关窗：要能停下来收摊，不能崩。"""
        main, _, _ = ui
        main._on_start()
        assert main._engine_running is True
        main.close()
        qt_app.processEvents()
        assert main._engine_running is False

    def test_start_without_script_shows_a_hint_not_a_crash(self, qt_app, ui, monkeypatch) -> None:
        """没选脚本就点开始：给提示，不许抛。"""
        main, _, _ = ui
        main._entry = None
        shown: list[tuple] = []
        monkeypatch.setattr(
            main, "_info_box", lambda title, body: shown.append((title, body))
        )

        main._on_start()

        assert shown, "应当弹一句提示"
        assert main._engine_running is False


class TestButtonWiring:
    """按钮 -> 槽的连接也要验：这两头各自测过，但线可能没接上。"""

    def test_start_button_signal_reaches_the_handler(self, qt_app, ui) -> None:
        main, _, _ = ui
        assert main.controls.start_btn.isEnabled()
        main.controls.start_btn.click()
        assert main._engine_running is True
        _wait_until(qt_app, lambda: not main._engine_running)

    def test_stop_button_signal_reaches_the_handler(self, qt_app, ui) -> None:
        main, _, _ = ui
        main._on_start()
        assert main._engine_running is True
        assert main.controls.stop_btn.isEnabled()
        main.controls.stop_btn.click()  # 不该抛
        assert _wait_until(qt_app, lambda: not main._engine_running)

    def test_selection_controls_are_locked_while_running(self, qt_app, ui) -> None:
        main, _, _ = ui
        main._on_start()
        assert not main.controls.script.isEnabled()
        assert not main.controls.window.isEnabled()
        _wait_until(qt_app, lambda: not main._engine_running)
        assert main.controls.script.isEnabled()
