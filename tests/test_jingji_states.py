"""离线验证：竞技场的三个状态能不能被正确区分。

## 为什么需要这个（不能用真机图代替）

真机图只能验"某一时刻恰好是什么状态"，验不了"三种状态**各自**认不认得出来" ——
而后者才是这次把 ``home/jingji`` 拆成三个子状态**有没有真的成功**。

合成帧能确定性地回答它：把某一张按钮图贴到它该在的位置，树就必须认出
对应的那个状态、而且**只有那一个**。空白帧则必须认不出来（否则就是

"随便什么画面都算竞技场"）。

它**验不了**的是"真机上分数够不够高" —— 那要靠真截图，
见 ``games/mingjiangsha/jingji/pages.py`` 里 ``CONF_BUTTON`` 那条注释的实测数字。

## 为什么用真 Matcher + 假后端

用假 Matcher（返回写死的分数）只能验"逻辑接线对不对"，验不了"三张图彼此的
相似度够不够低" —— 而这三张图**位置完全相同、只有文字不同**，
正是最容易互相误命中的那种。所以这里跑真模板匹配，只把"抓屏"换成假后端。
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest
from PIL import Image

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.session import BaseSession
from gamebot.types import Region
from gamebot.vision.opencv_matcher import OpenCvMatcher
from games.mingjiangsha.jingji.graph import SCENARIO

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "games/mingjiangsha/jingji/templates"

#: 客户区尺寸（和 ``games/mingjiangsha/game.py`` 的 ``SOURCE_SIZE`` 一致）
SIZE = (1918, 1080)

#: 三个按钮的搜索区域（也就是父分类节点的 roi）
PANEL = Region(1400, 630, 470, 360)

#: ``(按钮模板, 它对应的状态, 给人看的名字)``
CASES = (
    ("jingji/create_team.png", "home/jingji/before_create", "建队前"),
    ("jingji/add_pet.png", "home/jingji/after_create", "建队后"),
    ("jingji/start_match.png", "home/jingji/after_add", "加完伙伴"),
)


def _blank() -> np.ndarray:
    return np.zeros((SIZE[1], SIZE[0], 3), dtype=np.uint8)


def _paste(canvas: np.ndarray, name: str) -> None:
    """把某张按钮图贴到面板左上角（真机位置附近，但内容只有它自己）。"""
    img = np.array(Image.open(TEMPLATES / name).convert("RGB"))
    h, w = img.shape[:2]
    canvas[PANEL.y : PANEL.y + h, PANEL.x : PANEL.x + w] = img


def _session(image: np.ndarray) -> BaseSession:
    """真 Matcher + 假后端的 Session —— 用真匹配才验得出"三张图像不像"。"""
    matcher = OpenCvMatcher(templates_dir=str(TEMPLATES), grayscale=True, use_pyramid=True)
    return BaseSession(build_fake_backends(image=image, size=SIZE), matcher=matcher)


class TestJingjiStatesAreDistinguishable:
    """三个按钮各自只该认出自己那一个状态。"""

    @pytest.fixture(scope="class")
    def tree(self):
        return SCENARIO.materialize(name="states-test").tree

    @pytest.mark.parametrize(("template", "want", "label"), CASES)
    def test_button_identifies_its_own_state(self, tree, template, want, label):
        canvas = _blank()
        _paste(canvas, template)
        result = tree.locate(_session(canvas).capture())

        assert result.ok, f"{label}: 定位本身出错了 {result.message}"
        assert result.value is not None
        assert result.value.id == want, f"{label}: 认成了 {result.value.id}"

    def test_blank_frame_matches_no_jingji_state(self, tree):
        """空白画面不该被认成任何一个竞技场状态 —— 否则就是"什么画面都算"。"""
        result = tree.locate(_session(_blank()).capture())

        assert result.ok
        assert result.value is not None
        assert result.value.id not in {want for _, want, _ in CASES}

    def test_the_three_buttons_are_not_interchangeable(self, tree):
        """**关键**：三张图位置相同、只有文字不同，必须彼此区分得开。

        这条是拆三个状态的**前提** —— 若"创建队伍"的图也能达到 0.85 去命中
        "添加伙伴"，那这三个状态就是假的（会按优先级随机认一个）。
        实测交叉分数上限是 0.690，离 0.85 有 0.16 的余量。
        """
        for template, _want, label in CASES:
            canvas = _blank()
            _paste(canvas, template)
            frame = _session(canvas).capture()
            for other, _other_id, other_label in CASES:
                if other == template:
                    continue
                found = frame.find_image(other, region=PANEL, confidence=0.85)
                score = found.meta.get("score", 0.0) if found.ok else 0.0
                assert not found.ok, (
                    f"{label} 的画面被 {other_label} 的模板命中了（分数 {score:.3f}）—— "
                    "两个状态区分不开"
                )
