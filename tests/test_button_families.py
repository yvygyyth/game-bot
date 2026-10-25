"""按钮家族模板 —— **真机截图上的回归**。

`games/mingjiangsha/templates/<家族>/` 里的图就是这个游戏按钮的"身份证"。
这个文件用仓库里现存的原机截图复算一件事：

> **每个家族在自己的界面上只命中一次，分数 ≥0.95；别的家族不会被误命中。**

为什么值得每次跑测试都算一遍：这些模板会随着"游戏改版 / 换分辨率 / 重新裁图"失效，
而失效的表现是**真机上点不中**（或者更糟，点错按钮），现场极难查。
放在这里，改坏了提交前就红。

> 截图是 5MB 级的原图，模块级缓存一份，别每个用例都 `imread`。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from gamebot.vision.opencv_matcher import OpenCvMatcher

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "games" / "mingjiangsha" / "templates"
FEATURE = ROOT / "games" / "mingjiangsha" / "scripts" / "jingji" / "templates"
RAW = FEATURE / "rawMaterial"

#: 阈值：和 `click_button` 的默认值一致（实测真按钮 0.979~0.999）
CONFIDENCE = 0.90

#: ``(截图, 家族, 该命中哪张图, 分数下限)``
CASES = [
    ("tip1.png", "shadowConfirm", "ok.png", 0.95),
    ("tip1.png", "shadowCancel", "cancel.png", 0.95),
    ("jingji1.png", "shadowConfirm", "before_create.png", 0.95),
    ("jingji2.png", "shadowConfirm", "after_create.png", 0.95),
    ("select2.png", "patternConfirm", "ok1.png", 0.95),
    ("zhandou6.png", "QJ", "qj1.png", 0.95),
    ("zhandou7.png", "QJ", "qj2.png", 0.95),
]


@pytest.fixture(scope="module")
def matcher() -> OpenCvMatcher:
    """和 bootstrap 一样的两个模板根：功能级优先、游戏级兜底。"""
    return OpenCvMatcher(FEATURE, fallback_dirs=(GAME,), preload=True)


@pytest.fixture(scope="module")
def screenshots() -> dict[str, np.ndarray]:
    return {}


def _screenshot(cache: dict[str, np.ndarray], name: str) -> np.ndarray:
    if name not in cache:
        image = cv2.imread(str(RAW / name))
        assert image is not None, f"读不到截图: {RAW / name}"
        cache[name] = image
    return cache[name]


def _family_hits(matcher: OpenCvMatcher, image: np.ndarray, folder: str) -> list[tuple[float, str]]:
    """把家族里每张图都试一遍，返回 ``(分数, 文件名)``。"""
    hits: list[tuple[float, str]] = []
    for path in sorted((GAME / folder).glob("*.png")):
        for hit in matcher.match_all(
            image,
            f"{folder}/{path.name}",
            confidence=CONFIDENCE,
            min_distance=30,
        ):
            hits.append((hit.score, path.name))
    return sorted(hits, reverse=True)


class TestFamiliesOnRealScreens:
    @pytest.mark.parametrize(("shot", "folder", "expected", "floor"), CASES)
    def test_exactly_one_button_of_that_family_is_found(
        self,
        matcher: OpenCvMatcher,
        screenshots: dict[str, np.ndarray],
        shot: str,
        folder: str,
        expected: str,
        floor: float,
    ) -> None:
        hits = _family_hits(matcher, _screenshot(screenshots, shot), folder)

        assert len(hits) == 1, f"{shot} 在 {folder} 里应该正好 1 个，实际 {len(hits)}: {hits}"
        score, template = hits[0]
        assert template == expected, f"{shot} 命中的应该是 {expected}，实际 {template}"
        assert score >= floor, f"{shot}/{expected} 只匹配到 {score:.3f}（下限 {floor}）"

    def test_a_dialog_with_two_families_gives_one_hit_each(
        self, matcher: OpenCvMatcher, screenshots: dict[str, np.ndarray]
    ) -> None:
        """`tip1.png` 上有「取消」和「确定」两个按钮 —— 分属两个家族，各命中各的。

        这正是"一个文件夹一种按钮"的价值：想点确定就不会点到取消。
        """
        image = _screenshot(screenshots, "tip1.png")
        assert len(_family_hits(matcher, image, "shadowConfirm")) == 1
        assert len(_family_hits(matcher, image, "shadowCancel")) == 1


class TestFamiliesAreDistinct:
    def test_different_labels_in_one_family_do_not_match_each_other(
        self, matcher: OpenCvMatcher
    ) -> None:
        """同家族的不同文字版本互不命中 —— 否则"同位置只有一个"就不成立。"""
        base = cv2.imread(str(GAME / "shadowConfirm" / "before_create.png"))
        assert base is not None

        for other in ("after_create.png", "ok.png"):
            hits = matcher.match_all(
                base,
                f"shadowConfirm/{other}",
                confidence=CONFIDENCE,
                min_distance=10,
            )
            assert hits == [], f"「创建队伍」的截图不该被 {other} 命中"

    def test_every_family_folder_has_images(self) -> None:
        from games.mingjiangsha.templates import BUTTON_FOLDERS

        for folder in BUTTON_FOLDERS:
            images = list((GAME / folder).glob("*.png"))
            assert images, f"家族 {folder} 里没有图"


class TestEndToEndOnARealScreenshot:
    """真截图 + 真 Matcher + 真 `click_button` —— 三层接起来点一次。"""

    def test_it_clicks_the_confirm_button_in_a_tip_dialog(
        self, screenshots: dict[str, np.ndarray], tmp_path: Path
    ) -> None:
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession
        from gamebot.config.schema import RunPaths
        from gamebot.context import RunContext
        from gamebot.types import Region
        from games.mingjiangsha.templates import BUTTON_SHADOW_CONFIRM
        from games.mingjiangsha.utils import click_button

        image = _screenshot(screenshots, "tip1.png")
        bundle = build_fake_backends(image=image)
        session = BaseSession(
            bundle,
            matcher=OpenCvMatcher(FEATURE, fallback_dirs=(GAME,), preload=False),
        )
        ctx = RunContext(session, name="mingjiangsha/jingji", paths=RunPaths.under(tmp_path))
        try:
            # 只框住提示框底部（确定 / 取消那一行）；真实脚本里这个 ROI 来自弹窗位置
            result = click_button(
                ctx,
                BUTTON_SHADOW_CONFIRM,
                Region(900, 880, 480, 140),
            )
        finally:
            ctx.close()

        assert result.ok, result.message
        # tip1 上「确定」的已知中心（前面用模板实测出来的）
        assert abs(result.value.x - 1075) <= 6
        assert abs(result.value.y - 953) <= 6
        clicks = [event for event in bundle.input.events if event[0] == "click"]
        assert clicks, "没有真的下发点击"
        assert clicks[-1][1][0] == result.value

    def test_it_does_not_click_cancel_when_asked_for_confirm(
        self, screenshots: dict[str, np.ndarray], tmp_path: Path
    ) -> None:
        """同一个 ROI 里取消/确定都在 —— 请求 shadowConfirm 就不该点到取消。"""
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession
        from gamebot.config.schema import RunPaths
        from gamebot.context import RunContext
        from gamebot.types import Region
        from games.mingjiangsha.templates import BUTTON_SHADOW_CONFIRM
        from games.mingjiangsha.utils import click_button

        image = _screenshot(screenshots, "tip1.png")
        bundle = build_fake_backends(image=image)
        session = BaseSession(
            bundle,
            matcher=OpenCvMatcher(FEATURE, fallback_dirs=(GAME,), preload=False),
        )
        ctx = RunContext(session, name="mingjiangsha/jingji", paths=RunPaths.under(tmp_path))
        try:
            result = click_button(ctx, BUTTON_SHADOW_CONFIRM, Region(900, 880, 700, 140))
        finally:
            ctx.close()

        assert result.ok, result.message
        # 取消按钮的中心约 (1474, 953)，绝不能点过去
        assert abs(result.value.x - 1474) > 50

