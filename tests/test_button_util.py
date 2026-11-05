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

FOLDER = "gold_glow"


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
        assert "gold_glow" in message, "报错里要列出可用的家族名"

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

    def test_two_variants_on_two_buttons_are_two_hits(self, button_ctx) -> None:
        """家族里两张不同图的模板，分别命中**两个不同位置** —— 那是两个按钮。"""
        names = _hits(
            button_ctx,
            [Point(100, 100)],
            templates=[f"{FOLDER}/ok.png", f"{FOLDER}/before_create.png"],
        )
        button_ctx.session.matcher.all_matches[f"{FOLDER}/before_create.png"] = [Point(400, 100)]
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

    def test_two_templates_on_the_same_button_are_merged(self, button_ctx) -> None:
        """同一按钮的两张模板（不同裁法/缩放）都命中时，只能算一个按钮。

        不去重的后果：`pick="only"` 报"找到 2 个"，看起来像按钮重复了 ——
        而实际只是**模板重复**（同一种按钮的多张截图）。
        """
        names = _hits(
            button_ctx,
            [Point(100, 50)],
            templates=[f"{FOLDER}/ok.png", f"{FOLDER}/ok_old.png"],
        )
        button_ctx.session.matcher.all_matches[f"{FOLDER}/ok_old.png"] = [Point(108, 54)]

        hits = find_buttons(button_ctx, FOLDER, templates=names)

        assert len(hits) == 1, f"同一按钮被算成了 {len(hits)} 个"
        assert hits[0].point.x in (100, 108)

    def test_two_buttons_far_apart_stay_two(self, button_ctx) -> None:
        names = _hits(button_ctx, [Point(100, 50), Point(400, 50)])
        assert len(find_buttons(button_ctx, FOLDER, templates=names)) == 2
