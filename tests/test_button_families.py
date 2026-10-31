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
    def test_unmasked_matching_does_not_confuse_labels(self, matcher: OpenCvMatcher) -> None:
        """**整块**模板不会把一种文字认成另一种（这是"为什么要只比边框"的基线）。

        运行时不用整块比（文字会变），而是只比边框环 —— 见 ``TestRingTable`` 和
        ``TestRingMatching``。这条留着的价值是：说明"整块比"本身是精确的，
        换文字失配不是 bug，是特性。
        """
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


class TestRingMatching:
    """只比边框环：**同一尺寸、换文字**也能命中（整块模板会比不上）。"""

    def test_unmasked_template_fails_on_a_different_label(self, matcher, screenshots) -> None:
        """基准：整块模板在「换文字」的按钮上匹配不上 —— 这是要被解决的问题。"""
        image = _screenshot(screenshots, "jingji2.png")   # 这里是「添加伙伴」
        hits = matcher.match_all(
            image,
            "shadowConfirm/before_create.png",            # 模板是「创建队伍」
            confidence=CONFIDENCE,
            min_distance=30,
        )
        assert hits == [], f"整块模板不该命中另一种文字，实际 {[(h.score, h.point) for h in hits]}"

    def test_ring_mask_matches_a_different_label_of_the_same_size(
        self, matcher, screenshots, tmp_path: Path
    ) -> None:
        """只比边框：确定 -> 添加伙伴 命中，位置就是那个按钮。"""
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession
        from gamebot.config.schema import RunPaths
        from gamebot.context import RunContext
        from gamebot.types import Region
        from games.mingjiangsha.utils import find_buttons

        image = _screenshot(screenshots, "jingji2.png")
        bundle = build_fake_backends(image=image)
        session = BaseSession(
            bundle,
            matcher=OpenCvMatcher(FEATURE, fallback_dirs=(GAME,), preload=False),
        )
        ctx = RunContext(session, name="mingjiangsha/jingji", paths=RunPaths.under(tmp_path))
        try:
            # 模板是「创建队伍」，画面上是「添加伙伴」—— 文字不同、尺寸相同
            hits = find_buttons(
                ctx,
                "shadowConfirm",
                Region(2100, 800, 420, 200),
                templates=["shadowConfirm/before_create.png"],
            )
        finally:
            ctx.close()

        assert len(hits) == 1, f"应该正好命中一个按钮，实际 {hits}"
        assert abs(hits[0].point.x - 2332) <= 6
        assert abs(hits[0].point.y - 895) <= 6
        assert hits[0].score >= 0.95

    def test_ring_mask_does_not_match_a_different_size(self, matcher, screenshots) -> None:
        """环的位置跟着尺寸走：确定（263x92）不该命中 218x72 的添加伙伴。

        这是**已知限制**（见 buttons.py 的"尺寸/底色"那节）：换尺寸要另存一张，
        但不用重裁文字版本。
        """
        from games.mingjiangsha.utils import ring_mask

        image = _screenshot(screenshots, "jingji2.png")
        tpl = cv2.imread(str(GAME / "shadowConfirm" / "ok.png"))
        assert tpl is not None
        mask = ring_mask(tpl.shape[:2], inset=4, width=12)

        hits = matcher.match_all(
            image,
            "shadowConfirm/ok.png",
            confidence=CONFIDENCE,
            min_distance=30,
            mask=mask,
        )
        assert hits == [], f"不同尺寸不该命中，实际 {[(h.score, h.point) for h in hits]}"

#: 只比边框环的实测表（截图, 家族, 模板, 分数下限）
RING_CASES = [
    ("tip1.png", "shadowConfirm", "ok.png", 0.95),
    ("tip1.png", "shadowCancel", "cancel.png", 0.95),
    ("jingji1.png", "shadowConfirm", "before_create.png", 0.95),
    ("jingji2.png", "shadowConfirm", "after_create.png", 0.95),
    ("select2.png", "patternConfirm", "ok1.png", 0.95),
    ("zhandou6.png", "QJ", "qj1.png", 0.95),
    ("zhandou7.png", "QJ", "qj2.png", 0.95),
]


class TestRingTable:
    """运行时用的就是"只比边框环" —— 这张表就是 templates/README 里那张。"""

    @pytest.mark.parametrize(("shot", "folder", "template", "floor"), RING_CASES)
    def test_it_hits_once_with_a_high_score(
        self,
        matcher: OpenCvMatcher,
        screenshots: dict[str, np.ndarray],
        shot: str,
        folder: str,
        template: str,
        floor: float,
    ) -> None:
        from games.mingjiangsha.utils import BUTTON_RING_INSET, BUTTON_RING_WIDTH, ring_mask

        image = _screenshot(screenshots, shot)
        tpl = cv2.imread(str(GAME / folder / template))
        assert tpl is not None
        mask = ring_mask(
            tpl.shape[:2], inset=BUTTON_RING_INSET, width=BUTTON_RING_WIDTH
        )

        hits = matcher.match_all(
            image,
            f"{folder}/{template}",
            confidence=0.90,
            min_distance=30,
            mask=mask,
        )

        assert len(hits) == 1, f"{shot} 应该正好命中 1 个，实际 {len(hits)}"
        assert hits[0].score >= floor

    @pytest.mark.parametrize("shot", ["home.png", "jingji3.png", "zhandou2.png", "zhandou5.png"])
    def test_screens_without_these_buttons_have_no_hits(
        self, matcher: OpenCvMatcher, screenshots: dict[str, np.ndarray], shot: str
    ) -> None:
        """画面里根本没有这类按钮时，环也不该命中（误报=点错地方）。"""
        from games.mingjiangsha.utils import BUTTON_RING_INSET, BUTTON_RING_WIDTH, ring_mask

        image = _screenshot(screenshots, shot)
        for folder, template in (
            ("shadowConfirm", "before_create.png"),
            ("shadowCancel", "cancel.png"),
            ("QJ", "qj1.png"),
        ):
            tpl = cv2.imread(str(GAME / folder / template))
            assert tpl is not None
            mask = ring_mask(
                tpl.shape[:2], inset=BUTTON_RING_INSET, width=BUTTON_RING_WIDTH
            )
            hits = matcher.match_all(
                image, f"{folder}/{template}", confidence=0.90, min_distance=30, mask=mask
            )
            assert hits == [], f"{shot} 上 {folder}/{template} 误命中 {hits}"
