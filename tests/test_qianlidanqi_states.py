"""千里单骑：四个 select 状态 + 模板声明审计。

状态图在 ``pages.py``，这里用 ``rawMaterial`` 里的真机截图把"认得出/认不错"钉住。
截图是 2560x1440 / 2560x1392 的窗口图（顶部 23px 标题栏），运行时客户区是
2560x1369 —— 测试里裁掉标题栏（和底部任务栏）再喂，和真机一致。
"""

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

FEATURE_DIR = Path(__file__).resolve().parents[1] / "games/mingjiangsha/scripts/qianlidanqi"
TEMPLATES_DIR = FEATURE_DIR / "templates"
GAME_TEMPLATES_DIR = FEATURE_DIR.parents[1] / "templates"
RAW_DIR = TEMPLATES_DIR / "rawMaterial"

#: (期望状态, 真机截图)
CASES = (
    ("root", "first1.png"),
    ("campaign", "first2.png"),
    ("qianli/select1", "select1.png"),
    ("qianli/select2", "select2.png"),
    ("qianli/select3", "select3.png"),
    ("qianli/select4", "select4.png"),
    ("qianli/select5", "select5.png"),
    ("qianli/map", "flow1.png"),
    ("qianli/map", "flow2.png"),
    ("qianli/map", "flow_map2.png"),
    ("qianli/map", "flow_map4.png"),
    ("qianli/map", "flow_map5.png"),
    ("qianli/pre_battle", "battle/battle1.png"),
    ("qianli/gift", "battle/zengli.png"),
    ("qianli/gift", "flow_gift.png"),
    ("qianli/shop/ba_qing", "shop_ba_qing.png"),
    ("qianli/rest", "rest.png"),
    ("qianli/pocket/choice", "pocket1.png"),
    ("qianli/pocket/confirm", "pocket2.png"),
    ("qianli/map", "flow_map26.png"),
    ("qianli/event/intro", "event_zuoci_intro.png"),
    ("qianli/event/intro", "event_kaka_intro.png"),
    ("qianli/event/choice", "event_feifei_choice.png"),
    ("qianli/map", "flow_map3.png"),
    ("qianli/event/intro", "event_mozi_intro.png"),
    ("qianli/event/intro", "event_shichang_intro.png"),
    ("qianli/event/shi_chang", "event_shichang_choice.png"),
    ("qianli/event/zhuge", "zhuge1.png"),
    ("qianli/event/zhuge", "zhuge2.png"),
    ("qianli/event/zhuge", "zhuge3.png"),
    ("qianli/event/mo_zi", "event_mozi_choice.png"),
    ("qianli/skill_panel", "skill_panel.png"),
    ("qianli/fight/hand_swap", "event_shichang_battle.png"),
    ("qianli/fight/menu_off", "battle_menu.png"),
    ("qianli/fight/ended", "fight_victory.png"),
    ("qianli/gift_kind", "battle/zengli2.png"),
    ("qianli/end", "end.png"),
    ("qianli/end2", "end2.png"),
)


@pytest.fixture(scope="module")
def scenario():
    return get_script("mingjiangsha/qianlidanqi").build_scenario()


@pytest.fixture(scope="module")
def matcher() -> OpenCvMatcher:
    return OpenCvMatcher(
        TEMPLATES_DIR, fallback_dirs=(GAME_TEMPLATES_DIR,), preload=True, use_pyramid=False
    )


def _locate_image(scenario, matcher, image) -> str | None:
    session = BaseSession(build_fake_backends(image=image), matcher=matcher)
    ctx = RunContext(
        session,
        name="mingjiangsha/qianlidanqi",
        paths=RunPaths.under(Path(tempfile.mkdtemp())),
        frame_ttl=0.0,
    )
    try:
        result = scenario.tree.locate(ctx.frame(), "unknown")
        return None if result.value is None else result.value.id
    finally:
        ctx.close()


def _locate(scenario, matcher, shot: str) -> str | None:
    image = cv2.imread(str(RAW_DIR / shot))
    assert image is not None, shot
    # 截图标题栏有 23px（2560x1392/1440）和 32px（2560x1401）两种
    top = 32 if image.shape[0] == 1401 else 23
    return _locate_image(scenario, matcher, image[top:top + 1369, :])


@pytest.mark.parametrize(("expected", "shot"), CASES)
def test_state_is_recognized(scenario, matcher, expected: str, shot: str) -> None:
    assert _locate(scenario, matcher, shot) == expected


def test_select2_and_select3_differ_by_the_placeholder(scenario, matcher) -> None:
    """两个面板只差"占位卡在不在" —— 这就是 exclude 的作用，单独钉一下。"""
    assert _locate(scenario, matcher, "select2.png") == "qianli/select2"
    assert _locate(scenario, matcher, "select3.png") == "qianli/select3"


def test_all_templates_are_declared() -> None:
    declared = declared_from_module("games.mingjiangsha.scripts.qianlidanqi.templates")
    missing, _ = audit((TEMPLATES_DIR, GAME_TEMPLATES_DIR), declared)
    # unused 只看功能级；游戏级公共按钮模板不归这个脚本声明
    _, unused = audit(TEMPLATES_DIR, declared)
    assert not missing, f"缺少声明: {missing}"
    assert not unused, f"没有被声明的图: {unused}"


def test_script_is_registered() -> None:
    spec = get_script("mingjiangsha/qianlidanqi")
    assert spec.title == "千里单骑"
    assert spec.feature.use_pyramid is False
