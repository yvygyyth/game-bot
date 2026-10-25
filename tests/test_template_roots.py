"""两个模板根 —— 功能级优先、游戏级兜底。

## 为什么要专门测

"图找不到"是写脚本时最常见的故障，而它的原因往往只是"这张图该放游戏级、
但我放进了功能级"（或反过来）。两个根同时生效这件事**只在装配期**绑定，
跑起来之后报的是 `TemplateNotFoundError` —— 离真正的原因很远。

这里钉住三件事：

1. 功能级没有、游戏级有 -> 能找到；
2. 两边都有同名图 -> **功能级赢**（可以覆盖公共图）；
3. `preload` 会把两个根都读进来（否则第一次查询会漏）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from gamebot.feature import FeatureSpec
from gamebot.flow import Node, NodeBindings
from gamebot.scenario_spec import ScenarioSpec
from gamebot.vision.opencv_matcher import OpenCvMatcher


def _feature() -> FeatureSpec:
    """最小 FeatureSpec：只为了看两个模板根怎么从 name 推导。"""
    scenario = ScenarioSpec(
        initial="a",
        bindings=NodeBindings.of([("a", "a")]),
        nodes=(Node("a"),),
    )
    return FeatureSpec(
        name="demo/flow",
        title="演示",
        slug="flow",
        window_title="演示窗口",
        scenario=scenario,
    )


def _write(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.full((8, 8, 3), color, np.uint8))


class TestTwoRoots:
    def test_fallback_root_resolves(self, tmp_path: Path) -> None:
        feature, game = tmp_path / "feature", tmp_path / "game"
        _write(game / "buttons" / "edge.png", (0, 0, 255))

        matcher = OpenCvMatcher(feature, fallback_dirs=(game,), preload=False)

        assert matcher.load_template("buttons/edge.png")[0, 0].tolist() == [0, 0, 255]

    def test_feature_root_wins_on_a_name_clash(self, tmp_path: Path) -> None:
        feature, game = tmp_path / "feature", tmp_path / "game"
        _write(feature / "buttons" / "edge.png", (255, 0, 0))
        _write(game / "buttons" / "edge.png", (0, 0, 255))

        matcher = OpenCvMatcher(feature, fallback_dirs=(game,), preload=False)

        assert matcher.load_template("buttons/edge.png")[0, 0].tolist() == [255, 0, 0]

    def test_preload_reads_both_roots(self, tmp_path: Path) -> None:
        feature, game = tmp_path / "feature", tmp_path / "game"
        _write(feature / "only_feature.png", (1, 2, 3))
        _write(game / "only_game.png", (4, 5, 6))

        matcher = OpenCvMatcher(feature, fallback_dirs=(game,), preload=True)

        assert matcher.cached_templates == ["only_feature.png", "only_game.png"]

    def test_missing_name_still_reports_the_main_root(self, tmp_path: Path) -> None:
        """都找不到时，报错要指向**主根**（业务层写名字的地方），不是兜底根。"""
        feature, game = tmp_path / "feature", tmp_path / "game"
        _write(game / "buttons" / "edge.png", (0, 0, 255))

        matcher = OpenCvMatcher(feature, fallback_dirs=(game,), preload=False)

        assert matcher._resolve_path("nope.png") == feature / "nope.png"


class TestFeatureSpecKnowsBothRoots:
    def test_game_templates_dir_is_derived_from_the_name(self) -> None:
        spec = _feature()
        assert spec.game_templates_dir == "games/demo/templates"
        assert spec.templates_dir == "games/demo/scripts/flow/templates"
