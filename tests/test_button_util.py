"""`click_button` —— 按**按钮家族**找并点击。

这里全部走**假 Matcher**（预设命中点），不碰真截图：要验证的是
"候选多于一个时选谁""家族文件夹怎么写""没候选/写错家族名时怎么说"，
不是模板像不像。真模板能不能命中真实截图，由 `test_button_families.py` 负责。
"""

from __future__ import annotations

import pytest

from gamebot.context import RunContext
from gamebot.exceptions import ConfigError
from gamebot.types import Point, Region
from games.mingjiangsha.utils import click_button, find_buttons, folder_templates

FOLDER = "shadowConfirm"


@pytest.fixture
def button_ctx(session, run_paths) -> RunContext:
    """game 是 ``mingjiangsha``，这样家族目录能真的解析到。"""
    context = RunContext(session, name="mingjiangsha/demo", paths=run_paths)
    yield context
    context.close()


def _hits(ctx, points, *, templates=None) -> list[str]:
    """让假 Matcher 在这些模板上返回命中点；返回模板名列表。"""
    names = templates or [f"{FOLDER}/ok.png"]
    for name in names:
        ctx.session.matcher.all_matches[name] = list(points)
    return names


class TestFolderTemplates:
    def test_resolves_the_real_folder(self, button_ctx) -> None:
        names = folder_templates(button_ctx, FOLDER)
        assert names == [
            f"{FOLDER}/after_create.png",
            f"{FOLDER}/before_create.png",
            f"{FOLDER}/ok.png",
        ]

    def test_unknown_folder_lists_what_exists(self, button_ctx) -> None:
        with pytest.raises(ConfigError) as excinfo:
            folder_templates(button_ctx, "shadowConfrim")  # 故意拼错
        message = str(excinfo.value)
        assert "shadowConfirm" in message, "报错里要列出可用的家族名"

    def test_template_names_carry_the_folder_prefix(self, button_ctx) -> None:
        """运行时按相对名在"功能级/游戏级"两个根里找，所以名字必须带家族目录。"""
        assert all(
            name.startswith(f"{FOLDER}/") for name in folder_templates(button_ctx, FOLDER)
        )


class TestFindButtons:
    def test_no_hits_is_an_empty_list(self, button_ctx) -> None:
        names = _hits(button_ctx, [])
        assert find_buttons(button_ctx, FOLDER, templates=names) == []

    def test_hits_are_sorted_left_to_right(self, button_ctx) -> None:
        names = _hits(button_ctx, [Point(300, 100), Point(100, 100), Point(200, 100)])
        assert [hit.point.x for hit in find_buttons(button_ctx, FOLDER, templates=names)] == [
            100,
            200,
            300,
        ]

    def test_hit_remembers_which_variant_matched(self, button_ctx) -> None:
        names = _hits(button_ctx, [Point(100, 100)])
        hits = find_buttons(button_ctx, FOLDER, templates=names)
        assert hits[0].template == f"{FOLDER}/ok.png"
        assert hits[0].score == pytest.approx(0.95)

    def test_two_variants_both_matching_is_two_hits(self, button_ctx) -> None:
        names = _hits(
            button_ctx,
            [Point(100, 100)],
            templates=[f"{FOLDER}/ok.png", f"{FOLDER}/before_create.png"],
        )
        assert len(find_buttons(button_ctx, FOLDER, templates=names)) == 2


class TestClickButton:
    def test_single_button_is_clicked_at_its_centre(self, button_ctx, input_recorder) -> None:
        names = _hits(button_ctx, [Point(100, 50)])
        result = click_button(button_ctx, FOLDER, templates=names)

        assert result.ok
        assert result.value == Point(100, 50), "整按钮模板的命中点就是按钮中心"
        clicked = [event for event in input_recorder.events if event[0] == "click"]
        assert clicked and clicked[-1][1][0] == Point(100, 50)
        assert button_ctx.current_frame is None, "点完必须作废帧"

    def test_only_is_the_default_and_refuses_to_guess(self, button_ctx) -> None:
        names = _hits(button_ctx, [Point(100, 50), Point(300, 50)])
        result = click_button(button_ctx, FOLDER, templates=names)

        assert not result.ok
        assert result.meta["count"] == 2
        assert "pick" in result.message, "要告诉调用方：给 region 或显式选 pick"

    def test_best_picks_the_highest_score(self, button_ctx) -> None:
        names = _hits(
            button_ctx, [Point(100, 50)], templates=[f"{FOLDER}/a.png", f"{FOLDER}/b.png"]
        )
        button_ctx.session.matcher.matches[f"{FOLDER}/a.png"] = (Point(100, 50), 0.91)
        result = click_button(button_ctx, FOLDER, pick="best", templates=names)
        assert result.ok
        assert result.meta["score"] == pytest.approx(0.95)

    def test_right_and_left(self, button_ctx) -> None:
        names = _hits(button_ctx, [Point(100, 50), Point(300, 50)])
        assert click_button(button_ctx, FOLDER, pick="right", templates=names).value == Point(
            300, 50
        )
        assert click_button(button_ctx, FOLDER, pick="left", templates=names).value == Point(
            100, 50
        )

    def test_nothing_found(self, button_ctx) -> None:
        names = _hits(button_ctx, [])
        result = click_button(button_ctx, FOLDER, templates=names)
        assert not result.ok
        assert FOLDER in result.message

    def test_unknown_pick_is_a_programming_error(self, button_ctx) -> None:
        names = _hits(button_ctx, [Point(100, 50)])
        with pytest.raises(ConfigError, match="pick"):
            click_button(button_ctx, FOLDER, pick="middle", templates=names)

    def test_region_is_forwarded(self, button_ctx) -> None:
        names = _hits(button_ctx, [Point(100, 50)])
        region = Region(10, 10, 200, 100)
        click_button(button_ctx, FOLDER, region, templates=names)
        template, searched = button_ctx.session.matcher.calls[-1]
        assert template == f"{FOLDER}/ok.png"
        assert searched is not None, "给了 region 就该把范围传下去（哪怕被归一化过）"
