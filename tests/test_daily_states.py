"""每日领奖：状态识别 + 模板声明审计。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.session import BaseSession
from gamebot.config.schema import RunPaths
from gamebot.context import RunContext
from gamebot.vision.opencv_matcher import OpenCvMatcher
from games import get_script
from games._templates import audit, declared_from_module

FEATURE_DIR = Path(__file__).resolve().parents[1] / "games/mingjiangsha/scripts/daily"
TEMPLATES_DIR = FEATURE_DIR / "templates"
RAW_DIR = TEMPLATES_DIR / "rawMaterial"

CASES = (
    ("daily/root", "home.png"),
    ("daily/mail", "mail.png"),
    ("daily/activity", "activity.png"),
    ("daily/gallery", "gallery.png"),
    ("daily/shop", "shop_gold.png"),
    ("daily/shop", "shop_copper.png"),
    ("daily/shop", "shop_jinlan.png"),
    ("daily/zhu_jiu", "zhu_jiu.png"),
    ("daily/zhan_yi", "zhanyi.png"),
    ("daily/gong_hui", "gonghui.png"),
    ("daily/flower", "flower1.png"),
)


@pytest.fixture(scope="module")
def scenario():
    return get_script("mingjiangsha/daily").build_scenario()


@pytest.fixture(scope="module")
def matcher() -> OpenCvMatcher:
    return OpenCvMatcher(TEMPLATES_DIR, preload=True, use_pyramid=False)


def _locate(scenario, matcher, shot: str) -> str | None:
    image = cv2.imread(str(RAW_DIR / shot))
    assert image is not None, shot
    image = image[23:1392, :]
    session = BaseSession(build_fake_backends(image=image), matcher=matcher)
    ctx = RunContext(
        session,
        name="mingjiangsha/daily",
        paths=RunPaths.under(Path(tempfile.mkdtemp())),
        frame_ttl=0.0,
    )
    try:
        result = scenario.tree.locate(ctx.frame(), "unknown")
        return None if result.value is None else result.value.id
    finally:
        ctx.close()


@pytest.mark.parametrize(("expected", "shot"), CASES)
def test_state_is_recognized(scenario, matcher, expected: str, shot: str) -> None:
    assert _locate(scenario, matcher, shot) == expected


def test_all_templates_are_declared() -> None:
    declared = declared_from_module("games.mingjiangsha.scripts.daily.templates")
    missing, unused = audit(TEMPLATES_DIR, declared)
    assert not missing, f"缺少声明: {missing}"
    assert not unused, f"没有被声明的图: {unused}"


def test_script_is_registered() -> None:
    spec = get_script("mingjiangsha/daily")
    assert spec.title == "每日领奖"
    assert spec.feature.use_pyramid is False
