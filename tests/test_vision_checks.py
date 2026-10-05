"""通用识别检查的测试 —— **判据本身要是对的**。

这块值钱在它能抓住什么，所以这里逐条验"该报的报、不该报的不报"：

* ROI 留不下悬停位移 → 必须报（名将杀首页卡片会弹 27/41 像素，静态看不出来）；
* 模板比 ROI 还大 → 必须报（永远匹配不到）；
* 阈值非法 → 必须报；
* 顺序探测点错按钮 → 必须报；
* **来源图上拿不到满分** → 必须报（模板裁歪了）；
* 一切正常 → **一条都不许报**（误报会让用户学会忽略输出，比不报还糟）。
"""

from __future__ import annotations

import numpy as np
import pytest

from gamebot.config.schema import AppConfig, BackendKind
from gamebot.types import Point, Region
from gamebot.vision.checks import (
    ChecksSpec,
    EntryGroup,
    EntrySpec,
    SequenceSpec,
    run_checks,
)

from .conftest import FakeMatcher


# --------------------------------------------------------------------------- #
# 造一个"模板目录 + 真图"的最小环境
# --------------------------------------------------------------------------- #
def _png(path, size: tuple[int, int], color: int = 200) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    cv2.imwrite(str(path), np.full((height, width, 3), color, dtype=np.uint8))


@pytest.fixture
def config(tmp_path) -> AppConfig:
    """一个真实存在的模板目录（检查要读模板的实际尺寸）。

    模板根由 ``vision.templates_dir`` 决定，**不是** ``paths.templates`` ——
    这两个字段名字像、用处不同，搞混了检查就会说"模板找不到"。
    """
    config = AppConfig.defaults()
    config.screen.backend = BackendKind.FAKE
    config.paths.root = tmp_path
    config.vision.templates_dir = "templates"
    config.vision.record = False
    (tmp_path / "templates").mkdir(parents=True, exist_ok=True)
    return config


def _spec(*, entries=(), sequences=(), groups=(), fixture_group="") -> ChecksSpec:
    return ChecksSpec(
        title="测试",
        entries=tuple(entries),
        sequences=tuple(sequences),
        groups=tuple(groups),
        fixture_group=fixture_group,
    )


# --------------------------------------------------------------------------- #
class TestGeometry:
    """纯算术检查 —— 不需要图片就能查出"位置会偏"的几个来源。"""

    def test_roi_leaving_no_room_for_hover_is_reported(self, config) -> None:
        """ROI 留不下悬停位移 → 报。

        这是这个检查存在的**主要理由**：名将杀首页的卡片静止时在中间、
        悬停时往右上弹 (+27, -41)。ROI 留小了，鼠标一划过入口模板就滑出去、
        匹配不到 —— 而静态看代码完全看不出来。
        """
        _png(config.paths.resolve(config.vision.templates_dir) / "card.png", (80, 60))
        spec = _spec(
            entries=(
                EntrySpec(
                    template="card.png",
                    point=Point(100, 100),
                    confidence=0.9,
                    roi=Region(60, 70, 80, 60),  # 卡得死死的，一点余量都没有
                    hover=Point(27, -41),
                    label="竞技入口",
                ),
            )
        )

        problems = run_checks(spec, config)

        joined = " ".join(problems)
        assert "装不下位移" in joined
        assert "+27" in joined and "-41" in joined

    def test_roi_with_enough_room_passes(self, config) -> None:
        """留够了就不许报 —— 误报会让人学会忽略输出。"""
        _png(config.paths.resolve(config.vision.templates_dir) / "card.png", (80, 60))
        spec = _spec(
            entries=(
                EntrySpec(
                    template="card.png",
                    point=Point(160, 160),
                    confidence=0.9,
                    roi=Region(40, 40, 240, 240),
                    hover=Point(27, -41),
                    label="竞技入口",
                ),
            )
        )

        assert run_checks(spec, config) == []

    def test_template_bigger_than_roi_is_reported(self, config) -> None:
        """模板比 ROI 还大 = 永远匹配不到。"""
        _png(config.paths.resolve(config.vision.templates_dir) / "big.png", (300, 200))
        spec = _spec(
            entries=(
                EntrySpec(
                    template="big.png",
                    point=Point(100, 100),
                    confidence=0.9,
                    roi=Region(0, 0, 100, 100),
                    label="大图",
                ),
            )
        )

        problems = run_checks(spec, config)
        assert any("永远匹配不到" in p for p in problems)

    def test_expected_centre_outside_roi_is_reported(self, config) -> None:
        """期望中心不在自己的 ROI 里 —— 摆下去必然伸出去。"""
        _png(config.paths.resolve(config.vision.templates_dir) / "t.png", (20, 20))
        spec = _spec(
            entries=(
                EntrySpec(
                    template="t.png",
                    point=Point(500, 500),
                    confidence=0.9,
                    roi=Region(0, 0, 100, 100),
                    label="跑偏了",
                ),
            )
        )

        problems = run_checks(spec, config)
        assert any("不在它的 ROI" in p for p in problems)

    @pytest.mark.parametrize("bad", [0.0, -0.1, 1.4])
    def test_illegal_threshold_is_reported(self, config, bad) -> None:
        """阈值不在 0~1 之间 → 报（1.4 这种永远匹配不到，0 这种全都命中）。"""
        _png(config.paths.resolve(config.vision.templates_dir) / "t.png", (20, 20))
        spec = _spec(
            entries=(
                EntrySpec(
                    template="t.png", point=Point(50, 50), confidence=bad,
                    roi=Region(0, 0, 100, 100), label="t",
                ),
            )
        )

        problems = run_checks(spec, config)
        assert any("不合法" in p for p in problems)

    def test_missing_template_is_reported(self, config) -> None:
        spec = _spec(
            entries=(
                EntrySpec(
                    template="nope.png", point=Point(50, 50), confidence=0.9,
                    roi=Region(0, 0, 100, 100), label="缺图",
                ),
            )
        )

        problems = run_checks(spec, config)
        assert any("找不到或读不出来" in p for p in problems)

    def test_sequence_template_bigger_than_roi_is_reported(self, config) -> None:
        _png(config.paths.resolve(config.vision.templates_dir) / "wide.png", (400, 30))
        spec = _spec(
            sequences=(
                SequenceSpec(
                    templates=("wide.png",),
                    names=("宽按钮",),
                    roi=Region(0, 0, 200, 100),
                    confidence=0.9,
                ),
            )
        )

        problems = run_checks(spec, config)
        assert any("永远匹配不到" in p for p in problems)


class TestEmptySpec:
    def test_nothing_to_check_reports_nothing(self, config) -> None:
        """没声明任何东西就不该报错 —— 加新脚本时可以先空着。"""
        assert run_checks(_spec(), config) == []


class TestEntryGroup:
    def test_required_defaults_to_true(self) -> None:
        group = EntryGroup(name="首页", entries=())
        assert group.required is True

    def test_label_falls_back_to_template(self) -> None:
        entry = EntrySpec(template="a/b.png", point=Point(1, 1), confidence=0.9)
        assert entry.name == "a/b.png"
        assert EntrySpec(
            template="a/b.png", point=Point(1, 1), confidence=0.9, label="按钮"
        ).name == "按钮"

    def test_sequence_label_uses_names(self) -> None:
        sequence = SequenceSpec(
            templates=("a.png", "b.png"),
            names=("甲", "乙"),
            roi=Region(0, 0, 10, 10),
            confidence=0.9,
        )
        assert sequence.label_of("a.png") == "甲"
        assert sequence.label_of("b.png") == "乙"
        # 没登记的模板退化成文件名，不该炸
        assert sequence.label_of("c.png") == "c.png"


class TestSequencePicking:
    """顺序探测：按顺序找，第一个过阈值的必须正好是该点的那个。"""

    def _spec(self, expected) -> ChecksSpec:
        return _spec(
            sequences=(
                SequenceSpec(
                    templates=("a.png", "b.png"),
                    names=("甲", "乙"),
                    roi=Region(0, 0, 100, 100),
                    confidence=0.9,
                    expected=expected,
                ),
            )
        )

    def test_asset_check_skipped_without_directory(self, config) -> None:
        """没有资产目录就跳过回归（那是本地素材，不入库）。"""
        _png(config.paths.resolve(config.vision.templates_dir) / "a.png", (10, 10))
        _png(config.paths.resolve(config.vision.templates_dir) / "b.png", (10, 10))
        problems = run_checks(self._spec({"x.png": "a.png"}), config)
        assert problems == []

    def test_asset_check_reports_missing_state_image(self, config, tmp_path) -> None:
        _png(config.paths.resolve(config.vision.templates_dir) / "a.png", (10, 10))
        _png(config.paths.resolve(config.vision.templates_dir) / "b.png", (10, 10))
        assets = tmp_path / "assets"
        # 目录里得有一张**能读出来**的图，否则会走"目录里没有可读 PNG"那条早退，
        # 就验不到"状态图缺失"这条了
        _png(assets / "present.png", (640, 360))
        spec = ChecksSpec(
            title="测试",
            assets_dir=assets,
            sequences=(
                SequenceSpec(
                    templates=("a.png", "b.png"),
                    roi=Region(0, 0, 100, 100),
                    confidence=0.9,
                    expected={"missing.png": "a.png"},
                ),
            ),
        )

        problems = run_checks(spec, config)
        assert any("缺少资产图" in p for p in problems)


class TestProbeRequirement:
    """探针的"必须认出来"和"顺便报告"要分得开。"""

    def test_optional_group_does_not_fail(self) -> None:
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession
        from gamebot.vision.probe import check_entries_on_frame

        session = BaseSession(build_fake_backends(size=(640, 360)), matcher=FakeMatcher())
        frame = session.capture()
        spec = ChecksSpec(
            title="测试",
            groups=(
                EntryGroup(
                    name="队伍",
                    required=False,
                    entries=(
                        EntrySpec(
                            template="btn.png", point=Point(10, 10), confidence=0.9,
                            roi=Region(0, 0, 100, 100), label="按钮",
                        ),
                    ),
                ),
            ),
        )

        # 假匹配器什么都没命中；因为这一组不是必需的，所以不算失败
        assert check_entries_on_frame(spec, frame) == []

    def test_required_group_missing_fails(self) -> None:
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession
        from gamebot.vision.probe import check_entries_on_frame

        session = BaseSession(build_fake_backends(size=(640, 360)), matcher=FakeMatcher())
        frame = session.capture()
        spec = ChecksSpec(
            title="测试",
            groups=(
                EntryGroup(
                    name="首页",
                    entries=(
                        EntrySpec(
                            template="entry.png", point=Point(10, 10), confidence=0.9,
                            roi=Region(0, 0, 100, 100), label="入口",
                        ),
                    ),
                ),
            ),
        )

        problems = check_entries_on_frame(spec, frame)
        assert any("首页 没认出来" in p for p in problems)

    def test_position_offset_beyond_tolerance_fails(self) -> None:
        """**认得出但认错地方**必须失败 —— 下一步就照着这个点戳下去了。"""
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession
        from gamebot.vision.probe import check_entries_on_frame

        matcher = FakeMatcher(matches={"entry.png": (Point(400, 300), 0.99)})
        session = BaseSession(build_fake_backends(size=(640, 360)), matcher=matcher)
        frame = session.capture()
        spec = ChecksSpec(
            title="测试",
            groups=(
                EntryGroup(
                    name="首页",
                    entries=(
                        EntrySpec(
                            template="entry.png",
                            point=Point(100, 100),     # 期望在这儿
                            confidence=0.9,
                            tolerance=15,
                            roi=Region(0, 0, 640, 360),
                            label="入口",
                        ),
                    ),
                ),
            ),
        )

        problems = check_entries_on_frame(spec, frame)
        assert any("位置偏了" in p for p in problems)
