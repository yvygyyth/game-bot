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
from gamebot.params import FormSpec
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

    假对象要照着真 ``ScriptSpec`` 的接口面补齐，少一个属性界面就会在选择
    脚本时炸 —— 而且炸得不明显：``_on_start`` 会提前返回、``_engine_running``
    一直是 False，于是"等引擎停下来"的用例**没有超时地一直等**（真踩过：
    跑一次全套用了 8 分钟）。
    """

    def __init__(
        self,
        *,
        max_ticks: int = 3,
        interval: float = 0.01,
        form: FormSpec | None = None,
    ) -> None:
        self._max_ticks = max_ticks
        self._interval = interval
        self.form = form or FormSpec()

    def build_config(self) -> AppConfig:
        return _config()

    def build_scenario(self) -> Scenario:
        return _scenario(max_ticks=self._max_ticks, interval=self._interval)


def _entry(max_ticks: int = 3, interval: float = 0.01, form: FormSpec | None = None):
    from gamebot.ui.registry import ScriptEntry

    return ScriptEntry(
        key="fake/ui",
        game="fake",
        slug="ui",
        title="假脚本",
        description="界面冒烟用",
        spec=_Spec(max_ticks=max_ticks, interval=interval, form=form),
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
    # （以前这里还要替掉 ``check_templates`` —— 「开始」会在缺模板时拒绝启动。
    # 那个预检已经删掉了：它要靠"哪一步用哪张图"的声明，而步骤现在是普通函数、
    # 没有那个属性。缺图的报错由识图本身给出，带模板路径。）

    main = win_mod.MainWindow()
    main.resize(900, 700)
    main.show()
    qt_app.processEvents()
    try:
        yield main, entry, real_build
    finally:
        main.close()
        qt_app.processEvents()


@pytest.fixture
def ui_long(qt_app, tmp_path, monkeypatch):
    """和 ``ui`` 一样，但脚本是"跑不完"的。

    为什么必须单独一个：要验"停止真的停得住"，场景就**不能自己跑完** ——
    否则"最后停了"可能是 ``max_ticks`` 干的，测试变假绿（这正是原来那条用例
    的问题：它设 ``max_ticks=3``，几十毫秒自己就完了，断言却只写"最终会停"）。
    这里 ``max_ticks=5000``、轮间隔 20ms，正常情况下它绝不会在测试时限内跑完，
    所以"停了"只可能是被我们停的。
    """
    from gamebot import bootstrap as bs
    from gamebot.ui import window as win_mod

    entry = _entry(max_ticks=5000, interval=0.02)
    monkeypatch.setattr(win_mod, "load_scripts", lambda: ([entry], ""))
    monkeypatch.setattr(win_mod, "load_details", win_mod.load_details)

    def fake_session(config, *, recorder=None):
        matcher = FakeMatcher(matches={"home.png": (Point(1, 1), 0.99)})
        if recorder is not None:
            matcher = recorder.wrap_matcher(matcher)
        return BaseSession(
            build_fake_backends(size=(640, 360)),
            matcher=matcher,
            reader=recorder.wrap_reader(FakeReader()) if recorder else FakeReader(),
        )

    monkeypatch.setattr(bs, "build_session_from_config", fake_session)

    main = win_mod.MainWindow()
    main.resize(900, 700)
    main.show()
    qt_app.processEvents()
    try:
        yield main, entry, None
    finally:
        # 关窗自己会请求停止；这里兜一层，别让用例失败时留个还在转的线程
        if main._engine_running:
            main._request_engine_stop()
            _wait_until(qt_app, lambda: not main._engine_running)
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
class _FakeRegion:
    """冒充 ``Region`` —— 控件栏的坐标显示会读它。"""

    def __init__(self) -> None:
        self.x, self.y, self.w, self.h = 0, 0, 640, 360


class _FakeWindow:
    """冒充 ``WindowInfo``。

    需要 ``title``（预检按它比对）**和** ``region``（下拉框一变，控件栏就会
    重算并显示客户区坐标 —— 少这个属性会炸在那儿）。
    """

    def __init__(self, title: str) -> None:
        self.title = title
        self.region = _FakeRegion()


class TestTargetWindowPreflight:
    """开跑前确认"要抓的那个窗口**现在**还在"。

    ## 这一组里有个陷阱

    预检会**弹模态框**，而测试要转事件循环（跨线程信号）—— 模态框一弹就真
    等人点，整套挂在那儿，表现只是"慢"，不像失败。

    所以每条走到"窗口不在"的用例都**必须**挡住 ``_ask_re_detect``。
    产品里那个方法是模态框，测试里换成返回值即可（这也是它单独成为一个
    方法而不是内联的原因）。

    ## 为什么值得单独一组用例

    窗口下拉框是**枚举当时**的快照。选完之后那个窗口关掉了的话，原来那条路
    会把底层异常直接弹给用户：

        [装不起来] BackendError: 未找到标题包含 'README.md - game-bot - Cursor' 的窗口

    用户看到的是自己几十分钟前选过的另一个窗口的标题 —— 既没说"是窗口问题"，
    也没说怎么办。现在改成开跑前就用**人话**问清楚。
    """

    def _stub_windows(self, monkeypatch, titles, *, chosen: str | None = None):
        """把窗口枚举换掉：省掉真枚举（慢），也让"窗口在不在"可控。

        ``chosen`` 模拟"用户在上面选了哪个" —— 注意 ``ControlsBar.window_title``
        是**只读属性**（它读的是下拉框的文本），所以设的是下拉框而不是属性。
        """
        from gamebot.ui import window as win_mod
        from gamebot.ui.panels import controls as controls_mod

        monkeypatch.setattr(
            controls_mod, "_list_windows", lambda keyword="": [_FakeWindow(t) for t in titles]
        )
        return win_mod

    @pytest.fixture(autouse=True)
    def _never_show_a_real_dialog(self, ui, monkeypatch):
        """**默认挡住模态框。**

        预检走到"窗口不在"就会弹框，而测试要转事件循环 —— 模态框一弹就真等人点，
        整套挂在那儿。表现只是"慢"（实测一个用例让全套 4.6s -> 59s），
        不像失败，所以很容易漏。

        默认答案给 ``False``（什么都不做）。要验"点了 Yes 会怎样"的用例
        自己再覆盖一次 :meth:`_ask_re_detect`。
        """
        main, _entry, _ = ui
        monkeypatch.setattr(main, "_ask_re_detect", lambda wanted, source: False)

    def test_missing_window_is_caught_before_anything_else(
        self, qt_app, ui, monkeypatch
    ) -> None:
        """窗口不在时**当场拦下**，而且不许走"枚举不到"那条分支。"""
        main, entry, _ = ui
        self._stub_windows(monkeypatch, ["别的窗口"])
        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(
            main, "_info_box", lambda title, body: shown.append((title, body))
        )
        asked: list[tuple[str, str]] = []
        monkeypatch.setattr(
            main, "_ask_re_detect", lambda wanted, source: asked.append((wanted, source)) or False
        )
        main.controls.software.setCurrentText("README.md - game-bot - Cursor")

        assert main._target_window_ok(entry) is False
        assert shown == [], "枚举得到别的窗口时不该走'枚举不到'那条分支"
        assert asked and asked[0][0] == "README.md - game-bot - Cursor"
        assert asked[0][1] == "上面选的软件", "要写清是在找哪个来源的标题"

    def test_missing_window_offers_to_redetect(self, qt_app, ui, monkeypatch) -> None:
        """要问一句，而且点了「Yes」就重新枚举。"""
        main, entry, _ = ui
        self._stub_windows(monkeypatch, ["别的窗口"])
        main.controls.software.setCurrentText("已经关掉的窗口")

        refreshed: list[bool] = []
        monkeypatch.setattr(
            main.controls, "refresh_windows", lambda keyword="": refreshed.append(True) or []
        )
        asked: list[tuple[str, str]] = []
        monkeypatch.setattr(
            main,
            "_ask_re_detect",
            lambda wanted, source: asked.append((wanted, source)) or True,
        )

        assert main._target_window_ok(entry) is False
        assert refreshed == [True], "点了 Yes 应该重新枚举窗口列表"
        assert asked and asked[0][0] == "已经关掉的窗口", "问的时候要说出在找哪个标题"

    def test_declining_does_not_refresh(self, qt_app, ui, monkeypatch) -> None:
        main, entry, _ = ui
        self._stub_windows(monkeypatch, ["别的窗口"])
        main.controls.software.setCurrentText("关掉的")
        refreshed: list[bool] = []
        monkeypatch.setattr(
            main.controls, "refresh_windows", lambda keyword="": refreshed.append(True) or []
        )
        monkeypatch.setattr(main, "_ask_re_detect", lambda wanted, source: False)

        assert main._target_window_ok(entry) is False
        assert refreshed == []

    def test_existing_window_passes(self, qt_app, ui, monkeypatch) -> None:
        main, entry, _ = ui
        self._stub_windows(monkeypatch, ["在的窗口", "别的"])
        main.controls.software.setCurrentText("在的窗口")

        assert main._target_window_ok(entry) is True

    def test_empty_enumeration_is_not_reported_as_missing_window(
        self, qt_app, ui, monkeypatch
    ) -> None:
        """一个窗口都枚举不到时**不说**"窗口不在" —— 那是后端不可用。

        这两种情况的处理完全不同（一个是"重选一个"，一个是"去装后端"），
        混成一句话会把人引到错的方向。
        """
        main, entry, _ = ui
        self._stub_windows(monkeypatch, [])
        main.controls.software.setCurrentText("随便什么")
        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(
            main, "_info_box", lambda title, body: shown.append((title, body))
        )

        assert main._target_window_ok(entry) is False
        assert len(shown) == 1
        assert "枚举不到" in shown[0][0]
        assert "pywin32" in shown[0][1]

    def test_start_is_blocked_when_window_is_gone(self, qt_app, ui, monkeypatch) -> None:
        """端到端：窗口不在时点「开始」，引擎不能起来。"""
        main, _entry, _ = ui
        self._stub_windows(monkeypatch, ["别的窗口"])
        main.controls.software.setCurrentText("关掉的窗口")
        monkeypatch.setattr(main, "_info_box", lambda title, body: None)
        # **必须挡掉弹窗**：模态框会阻塞，而测试在转事件循环 —— 忘了这一句
        # 整套会挂在这儿等人点，表现只是"慢"（实测 4.6s -> 59s），不像失败。
        monkeypatch.setattr(main, "_ask_re_detect", lambda wanted, source: False)

        main._on_start()

        assert main._engine_running is False, "窗口不在就不该启动引擎"

    def test_no_selection_falls_back_to_config_title(
        self, qt_app, ui, monkeypatch
    ) -> None:
        """没选软件时，按**配置里**的 window_title 检查（那才是后端会用的）。"""
        main, entry, _ = ui
        self._stub_windows(monkeypatch, ["在的窗口"])
        main.controls.software.setCurrentText("")
        monkeypatch.setattr(
            entry.spec, "build_config", lambda: _config_with_title("在的窗口")
        )

        assert main._target_window_ok(entry) is True


def _config_with_title(title: str) -> AppConfig:
    config = _config()
    config.screen.window_title = title
    return config


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
        assert not main.controls.software.isEnabled()
        _wait_until(qt_app, lambda: not main._engine_running)
        assert main.controls.script.isEnabled()


class TestStopping:
    """「停止」必须真的停得住 —— 这条曾经是假绿的。

    ## 踩过的坑（别再犯）

    ``_on_stop`` 原来发一个**队列信号**让引擎线程去执行 ``request_stop``。
    队列连接的槽要等目标线程回到事件循环才投递，而引擎线程正卡在
    ``engine.run()`` 那个阻塞循环里 —— 停止请求永远排队、永远不执行。
    表现：点了停止，脚本照跑。

    ## 为什么原来的测试没发现

    那个用例的场景设了 ``max_ticks=3``，**它自己几十毫秒就跑完了**；
    断言只写"最终会停" —— 不管是我停的还是它自己跑完的，都过。
    所以这里必须两样都验：

    1. 请求停止时**引擎还在跑**（还没跑完）；
    2. 结束原因是 ``user``，不是 ``max_ticks``。
    """

    @staticmethod
    def _stop_and_wait(qt_app, main, timeout: float = 3.0) -> float:
        started = time.monotonic()
        main._on_stop()
        assert _wait_until(qt_app, lambda: not main._engine_running, timeout), "停止没生效"
        return time.monotonic() - started

    def test_stop_interrupts_a_running_engine(self, qt_app, ui_long) -> None:
        """跑到一半点停止：立刻停，且原因是 user。"""
        main, _, _ = ui_long
        main._on_start()

        # 等它真的跑起来（至少两轮），这时它离 max_ticks 还远
        assert _wait_until(
            qt_app,
            lambda: main._engine_worker.engine is not None
            and main._engine_worker.engine.report.ticks >= 2,
        ), "引擎没跑起来"
        report = main._engine_worker.engine.report
        assert report.ticks < 200, "还没到 max_ticks，所以下面停下来一定是被停的"

        elapsed = self._stop_and_wait(qt_app, main)

        assert elapsed < 1.0, f"停止花了 {elapsed:.2f}s，太慢"
        assert main._last_report is not None
        assert main._last_report.stop_reason.value == "user", (
            f"结束原因是 {main._last_report.stop_reason}，说明它不是被停止的"
        )

    def test_stop_reaches_the_session_so_sleeps_are_interrupted(self, qt_app, ui_long) -> None:
        """中止标志必须写到 **Session** 上。

        ``engine.stop()`` 只设自己的标志位是不够的：``ctx.sleep()`` 要能被立刻
        唤醒，看的是 ``session`` 上那个 ``Event``。只设引擎的，就得等当前这一觉
        睡满才停 —— 节点声明了 cooldown 时那就是好几秒。
        """
        main, _, _ = ui_long
        main._on_start()
        assert _wait_until(qt_app, lambda: main._engine_worker.engine is not None)

        engine = main._engine_worker.engine
        main._request_engine_stop()

        assert engine.ctx.session.stop_requested, "中止标志没写到 session 上"
        _wait_until(qt_app, lambda: not main._engine_running)

    def test_close_while_running_stops_and_does_not_hang(self, qt_app, ui_long) -> None:
        """跑着关窗：得停下来收摊，不能卡在 wait(5000)。"""
        main, _, _ = ui_long
        main._on_start()
        assert _wait_until(qt_app, lambda: main._engine_worker.engine is not None)

        started = time.monotonic()
        main.close()
        qt_app.processEvents()
        elapsed = time.monotonic() - started

        assert main._engine_running is False
        assert elapsed < 4.0, f"关窗花了 {elapsed:.2f}s，可能卡在等引擎退出"
