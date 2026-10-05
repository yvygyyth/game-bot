"""pytest 公共装置。

设计原则：**测状态层 / 流程层 / 执行层时，不要碰真实截图和真实键鼠。**

所以这里提供：

* ``FakeMatcher`` / ``FakeReader``  —— 不读图片的视觉替身，返回预设结果
* ``fake_bundle``                  —— 内存后端（记录所有输入调用）
* ``session`` / ``frame``          —— 接了假后端的 Session 与一帧画面
* ``config``                       —— 指向临时目录的配置，不会污染项目
* ``ctx``                          —— 完整 RunContext，可跑流程层

有了这些，整个框架的不依赖 Windows / adb / 游戏就能被测试。
"""

from __future__ import annotations

import numpy as np
import pytest

from gamebot.atomic.backends.fake import FakeInputBackend, build_fake_backends
from gamebot.atomic.session import BaseSession
from gamebot.atomic.vision import MatchResult, TextBox
from gamebot.config.schema import AppConfig, BackendKind
from gamebot.context import RunContext
from gamebot.types import Point, Region


# --------------------------------------------------------------------------- #
# 视觉替身
# --------------------------------------------------------------------------- #
class FakeMatcher:
    """按模板名查预设结果的 Matcher 替身。

    :param matches: ``{template: (point, score)}``。没登记的模板视为"找不到"。
    :param all_matches: ``{template: [point, ...]}``，给 ``match_all`` 用。
    """

    def __init__(
        self,
        matches: dict[str, tuple[Point, float]] | None = None,
        all_matches: dict[str, list[Point]] | None = None,
        default_score: float = 0.95,
    ) -> None:
        self.matches = matches or {}
        self.all_matches = all_matches or {}
        self.default_score = default_score
        self.calls: list[tuple[str, Region | None]] = []

    def match(
        self, image, template, *, region=None, confidence=0.9, use_pyramid=True, grayscale=True
    ):
        self.calls.append((template, region))
        found = self.matches.get(template)
        if found is None:
            return None
        point, score = found
        if score < confidence:
            return None
        return MatchResult(
            point=point, score=score, region=Region(point.x - 5, point.y - 5, 10, 10)
        )

    def match_all(
        self,
        image,
        template,
        *,
        region=None,
        confidence=0.9,
        max_count=0,
        min_distance=10,
        grayscale=True,
    ):
        self.calls.append((template, region))
        points = self.all_matches.get(template, [])
        results = [
            MatchResult(
                point=p, score=self.default_score, region=Region(p.x - 5, p.y - 5, 10, 10)
            )
            for p in points
        ]
        return results[:max_count] if max_count else results

    def compare(self, image, region, template, confidence=0.9):
        found = self.matches.get(template)
        return found[1] if found else None


class FakeReader:
    """TextReader 替身。"""

    def __init__(self, texts: dict[str, tuple[Point, float]] | None = None, raw: str = "") -> None:
        self.texts = texts or {}
        self.raw = raw

    def locate(self, image, text, *, region=None, lang="ch", confidence=0.8, exact_match=False):
        for known, (point, score) in self.texts.items():
            hit = known == text if exact_match else text in known
            if hit and score >= confidence:
                return [
                    TextBox(
                        point=point,
                        text=known,
                        score=score,
                        region=Region(point.x - 20, point.y - 8, 40, 16),
                    )
                ]
        return []

    def read(self, image, *, region=None, lang="ch", confidence=0.8):
        return self.raw


# --------------------------------------------------------------------------- #
# 装置
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_bundle():
    """内存后端三件套。``bundle.input.events`` 可断言所有输入调用。"""
    return build_fake_backends(size=(640, 360))


@pytest.fixture
def matcher() -> FakeMatcher:
    return FakeMatcher(matches={"a.png": (Point(100, 50), 0.99)})


@pytest.fixture
def session(fake_bundle, matcher) -> BaseSession:
    return BaseSession(fake_bundle, matcher=matcher, reader=FakeReader(raw="123"))


@pytest.fixture
def frame(session):
    """一帧全黑画面（640x360，全屏）。"""
    return session.capture()


@pytest.fixture
def config(tmp_path) -> AppConfig:
    """指向临时目录的配置，避免往项目 logs/ 里写东西。"""
    cfg = AppConfig.defaults()
    cfg.name = "test-flow"
    cfg.screen.backend = BackendKind.FAKE
    cfg.paths.root = tmp_path
    cfg.paths.logs = tmp_path / "logs"
    cfg.paths.screenshots = tmp_path / "logs" / "screenshots"
    cfg.paths.journals = tmp_path / "logs" / "journals"
    cfg.paths.templates = tmp_path / "assets" / "templates"
    return cfg


@pytest.fixture
def ctx(session, config) -> RunContext:
    context = RunContext(session, config, frame_ttl=0.5)
    yield context
    context.close()


@pytest.fixture
def input_recorder(fake_bundle) -> FakeInputBackend:
    """直接拿假输入后端，方便断言"点了没有、点哪儿"。"""
    return fake_bundle.input


@pytest.fixture(scope="session")
def qt_app():
    """一个共享的 ``QApplication``（``QWidget`` / ``QShortcut`` 都要它）。

    放 conftest 而不是某个测试文件里：界面相关的测试不止一个文件要用，
    放文件里另一个文件就找不到（``fixture 'qt_app' not found``）。

    scope 是 session：一个进程里只能有一个 ``QApplication``，反复建会崩。
    PySide6 是可选依赖，没装时**跳过**这些用例而不是让整个测试收集失败。
    """
    pytest.importorskip("PySide6", reason="界面测试需要 PySide6（uv sync --extra ui）")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def blank_image() -> np.ndarray:
    """一张 640x360 的纯黑图，用来拼自定义画面。"""
    return np.zeros((360, 640, 3), dtype=np.uint8)


@pytest.fixture
def image_factory():
    """``image_factory((x, y, w, h), color)`` —— 在纯黑图上画个色块。"""

    def make(
        size: tuple[int, int, int, int], color: tuple[int, int, int] = (255, 0, 0)
    ) -> np.ndarray:
        image = np.zeros((360, 640, 3), dtype=np.uint8)
        x, y, w, h = size
        # numpy 是 (row, col) = (y, x)，且颜色顺序是 BGR
        image[y : y + h, x : x + w] = color
        return image

    return make
