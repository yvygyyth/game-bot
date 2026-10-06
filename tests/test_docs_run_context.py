"""`docs/run-context.md` 不许和代码漂移。

这份文档是"步骤里能拿到什么"的**索引** —— 它列错了名字，比不写还坏
（照着写一段代码，报 `AttributeError`，然后开始怀疑框架）。
所以让机器查两件事：

1. **文档里提到的每个成员都真实存在**（用真上下文查，不是查类）；
2. **文档里的代码片段真能跑**（至少 import 得到、调得通）。

反向也给提示：真实存在但文档一句没提的会打印出来（不算失败 ——
有些内部钩子本来就不该进文档）。
"""

from __future__ import annotations

import pathlib
import re

import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.session import BaseSession
from gamebot.config.schema import AppConfig
from gamebot.context import RunContext
from gamebot.state.page import Page, PageTree
from gamebot.state.tracker import PageTracker

from .conftest import FakeMatcher

DOC = pathlib.Path(__file__).resolve().parent.parent / "docs" / "run-context.md"

#: 示意用的占位名，不是真实成员。
_PLACEHOLDER = {"xxx"}


@pytest.fixture
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.fixture
def ctx() -> RunContext:
    config = AppConfig.defaults()
    tree = PageTree()
    tree.add(Page("home"))
    session = BaseSession(build_fake_backends(size=(64, 64)), matcher=FakeMatcher())
    context = RunContext(session, config, tree=tree, frame_ttl=0.5)
    yield context
    context.close()


def _documented_names(doc: str) -> set[str]:
    """文档里提到的 `ctx.xxx`（不管在表格还是正文）。"""
    return set(re.findall(r"ctx\.([a-z_][a-z0-9_]*)", doc))


def _declared_absent(doc: str) -> set[str]:
    """被明确标注为"没有"的名字（"没有的东西"那一节到文件末尾）。

    那两节里有一张"你可能想找 / 为什么没有"的表，还有"已知缺口"里
    **计划中**的接口（如 `ctx.log`）—— 它们**故意还不存在**，不算漏。
    """
    at = doc.find("## 没有的东西")
    assert at > 0, "文档里应该有『没有的东西（故意的）』这一节"
    # 反引号里可能写成 "ctx.log(...)"；不许跨行，也不许后面跟 `.`
    # （"ctx.session.dry_run" 里的 ctx.session 不是被标注为没有的那个）
    return set(re.findall(r"`ctx\.([a-z_][a-z0-9_]*)(?![\w.])[^`\n]*`", doc[at:])) | _PLACEHOLDER


class TestDocMatchesCode:
    def test_every_documented_member_exists(self, doc: str, ctx: RunContext) -> None:
        absent = _declared_absent(doc)
        missing = sorted(
            name
            for name in _documented_names(doc)
            if name not in absent and not hasattr(ctx, name)
        )
        assert missing == [], f"文档提到但上下文上没有: {missing}"

    def test_nothing_is_wrongly_declared_absent(self, doc: str, ctx: RunContext) -> None:
        wrong = sorted(n for n in _declared_absent(doc) if hasattr(ctx, n))
        assert wrong == [], f"文档说这些『故意没有』，但它们存在: {wrong}"

    def test_documented_tracker_members_exist(self, doc: str, ctx: RunContext) -> None:
        """跟踪器那张表里的 `.xxx`（表格里写成裸名字）。"""
        names = set(re.findall(r"^\| `\.([a-z_][a-z0-9_]*)`", doc, re.M))
        assert names, "应该有一张跟踪器成员表"
        missing = sorted(
            n for n in names if not hasattr(PageTracker, n) and not hasattr(ctx.pages, n)
        )
        assert missing == [], f"文档提到但跟踪器上没有: {missing}"

    def test_no_silent_gaps(self, doc: str, ctx: RunContext) -> None:
        """反向提示：真实存在却没进文档的。

        **不是**失败断言 —— 有些成员（如 `reset` / `close`）是内部生命周期，
        只是想让它显式可见，而不是靠"没人提起"。
        """
        named = _documented_names(doc) | _declared_absent(doc)
        undocumented = sorted(
            n for n in dir(ctx) if not n.startswith("_") and n not in named
        )
        # 想让它保持为空就说明覆盖完整了；不为空只在 -s 时提示
        print("\n存在但文档没提:", ", ".join(undocumented) or "（无）")


class TestDocExamplesRun:
    """文档里的代码片段不能只是"看着像"。

    只测**能独立跑通**的那几个（`ctx.frame().find_image` 之类需要真截图的不算）。
    """

    def test_frame_and_invalidate(self, ctx: RunContext) -> None:
        """『一眼看完』那段的三步：读画面 -> 动手 -> 作废帧。"""
        frame = ctx.frame()
        assert frame is not None
        ctx.invalidate_frame()  # 文档里强调必调的那句
        assert ctx.frame_age == float("inf") or ctx.frame_age >= 0.0

    def test_param_with_default(self, ctx: RunContext) -> None:
        ctx.set_params({"jingji.settle": 1.5})
        assert ctx.param("jingji.settle", 1.0) == 1.5
        assert ctx.param("不存在", 1.0) == 1.0

    def test_builtin_click_image_is_callable_as_documented(self, ctx: RunContext) -> None:
        """文档推荐用 `click_image(ctx, ...)` 而不是自己重写三步。"""
        from gamebot.execution.builtins import click_image
        from gamebot.types import ActionResult

        result = click_image(ctx, "不存在.png")
        assert isinstance(result, ActionResult)
        assert result.ok is False, "没这张图就该 not_found"

    def test_sleep_goes_through_context(self, ctx: RunContext) -> None:
        """文档说"等待一律走 ctx.sleep"（可中止）。"""
        ctx.sleep(0.001)

    def test_now_and_paths(self, ctx: RunContext, tmp_path: pathlib.Path) -> None:
        assert ctx.now() > 0
        ctx.config.paths.root = tmp_path
        ctx.config.paths.logs = tmp_path / "logs"
        ctx.config.paths.screenshots = tmp_path / "logs" / "shots"
        assert ctx.screenshot_path("a").name == "a.png"
        assert ctx.journal_path("x").suffix == ".jsonl"

    def test_stop_flags_documented_shape(self, ctx: RunContext) -> None:
        assert ctx.stop_requested is False
        ctx.request_stop("测试")
        assert ctx.stop_requested is True
        assert "测试" in ctx.stop_reason


class TestDocClaimsAboutAbsentThings:
    """文档明确说"没有"的，就该真的没有 —— 否则文档在骗人。"""

    @pytest.mark.parametrize(
        "name", ["dry_run", "tree", "binding", "expected", "log", "log_click"]
    )
    def test_really_absent(self, ctx: RunContext, name: str) -> None:
        assert not hasattr(ctx, name), f"文档说 ctx.{name} 没有，但它存在"

    def test_dry_run_lives_on_the_session(self, ctx: RunContext) -> None:
        """文档说去 `ctx.session.dry_run` 找 —— 那就得真在那儿。"""
        assert hasattr(ctx.session, "dry_run")
