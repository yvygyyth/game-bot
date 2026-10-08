"""状态判断可以**多张图组合** —— any / all / 自己写函数。

## 三件事，以及为什么值得有测试

用户问："状态判断可以多张图啊……any 任意一张有就算满足状态，all 都有才算，
或者索性让状态的判断方法作为一个函数。当然我也需要快捷函数。"

答案：**三样框架里都已经有了**（``OrQuery`` / ``queries`` 默认 AND /
裸 callable），但**一次都没在业务代码里用过**。所以这里有两条责任：

1. **把语义钉住** —— 免得以后被"顺手改坏"而没人发现；
2. **钉住"快捷函数和手写等价"** —— 这条踩过：组合查询自己没有 ``region``
   字段，``PageTree._specify`` 原来会把它们整个跳过，于是
   ``queries=(any_image(A, B),)`` **不做 roi 剪枝**，而
   ``queries=(ImageQuery(A), ImageQuery(B))`` 会。两者不一致，
   而"用哪种写法"就成了隐形的性能问题。

⚠️ 断言看的是 **``PageMatch.id`` 而不是 ``result.ok``** —— ``locate`` 在
"这一帧不属于任何已知状态"时返回的也是 ``success``（值是
``PageMatch('unknown')``）。那是**正常结果**，不是失败。
"""

from __future__ import annotations

import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.query import (
    AndQuery,
    ImageQuery,
    NotQuery,
    OrQuery,
    all_images,
    any_image,
)
from gamebot.atomic.session import BaseSession
from gamebot.state import Page, PageTree
from gamebot.types import ActionResult, Point, Region

from .conftest import FakeMatcher

CONF = 0.99


def _frame(matcher: FakeMatcher):
    session = BaseSession(build_fake_backends(size=(640, 360)), matcher=matcher)
    return session.capture()


def _locate(page: Page, matcher: FakeMatcher):
    tree = PageTree()
    tree.add(page)
    return tree.locate(_frame(matcher))


def _matches(page: Page, matcher: FakeMatcher) -> bool:
    """这个页面被认出来了吗？（看 id，不看 ``ok`` —— 见模块 docstring）"""
    result = _locate(page, matcher)
    assert result.value is not None, f"locate 没返回值: {result.message}"
    return result.value.id == page.id


def _hit(name: str) -> dict[str, tuple[Point, float]]:
    return {name: (Point(5, 5), CONF)}


# --------------------------------------------------------------------------- #
# 快捷函数本身：形状对不对
# --------------------------------------------------------------------------- #
class TestShortcutConstructors:
    def test_any_image_is_an_or_query(self):
        q = any_image("a.png", "b.png")
        assert isinstance(q, OrQuery)
        assert [inner.template for inner in q.queries] == ["a.png", "b.png"]

    def test_all_images_is_an_and_query(self):
        q = all_images("a.png", "b.png")
        assert isinstance(q, AndQuery)
        assert [inner.template for inner in q.queries] == ["a.png", "b.png"]

    def test_confidence_reaches_every_inner_query(self):
        """不给 confidence 时用 ``ImageQuery`` 的默认值，不能写成 None。"""
        default = ImageQuery("x.png").confidence
        assert all(i.confidence == default for i in any_image("a.png", "b.png").queries)
        with_conf = all_images("a.png", "b.png", confidence=0.7)
        assert all(i.confidence == 0.7 for i in with_conf.queries)

    @pytest.mark.parametrize("factory", [any_image, all_images])
    def test_zero_names_is_a_loud_error(self, factory):
        """空列表会让查询"永远成功" —— 那是静默的错，所以要直接抛。"""
        with pytest.raises(ValueError):
            factory()

    def test_one_image_is_allowed_but_pointless(self):
        assert len(any_image("a.png").queries) == 1


# --------------------------------------------------------------------------- #
# 语义：any / all
# --------------------------------------------------------------------------- #
class TestSemantics:
    def test_any_image_hits_when_only_one_is_present(self):
        page = Page("s", queries=(any_image("a.png", "b.png"),))
        assert _matches(page, FakeMatcher(matches=_hit("b.png"))) is True

    def test_any_image_misses_when_none_are_present(self):
        page = Page("s", queries=(any_image("a.png", "b.png"),))
        assert _matches(page, FakeMatcher(matches={})) is False

    def test_listing_two_queries_is_and(self):
        """``queries`` 默认 AND —— 只到一张不算这个状态。"""
        page = Page("s", queries=(ImageQuery("a.png"), ImageQuery("b.png")))
        assert _matches(page, FakeMatcher(matches=_hit("a.png"))) is False
        both = FakeMatcher(matches={**_hit("a.png"), **_hit("b.png")})
        assert _matches(page, both) is True

    def test_all_images_matches_listing_them_directly(self):
        """``all_images(A, B)`` 和"直接列两条"必须等价。"""
        both = FakeMatcher(matches={**_hit("a.png"), **_hit("b.png")})
        listed = _matches(Page("s", queries=(ImageQuery("a.png"), ImageQuery("b.png"))), both)
        wrapped = _matches(Page("s", queries=(all_images("a.png", "b.png"),)), both)
        assert listed is True
        assert wrapped is True

        only_a = FakeMatcher(matches=_hit("a.png"))
        listed2 = _matches(Page("s", queries=(ImageQuery("a.png"), ImageQuery("b.png"))), only_a)
        wrapped2 = _matches(Page("s", queries=(all_images("a.png", "b.png"),)), only_a)
        assert listed2 is False
        assert wrapped2 is False

    def test_not_query_vetoes(self):
        page = Page("s", queries=(ImageQuery("a.png"), NotQuery(ImageQuery("bad.png"))))
        vetoed = FakeMatcher(matches={**_hit("a.png"), **_hit("bad.png")})
        assert _matches(page, vetoed) is False, "bad.png 在，就不该算这个状态"
        assert _matches(page, FakeMatcher(matches=_hit("a.png"))) is True

    def test_and_or_together_reads_like_a_sentence(self):
        """``all_images(...)`` + ``any_image(...)`` 并排写，两组意图一眼看清。"""
        page = Page(
            "s",
            queries=(
                all_images("p.png", "q.png"),
                any_image("x.png", "y.png"),
            ),
        )
        # p、q 都有 + y（x 缺）-> 命中
        good = FakeMatcher(matches={**_hit("p.png"), **_hit("q.png"), **_hit("y.png")})
        assert _matches(page, good) is True
        # p、q 都有 + x、y 都没有 -> 不命中
        half = FakeMatcher(matches={**_hit("p.png"), **_hit("q.png")})
        assert _matches(page, half) is False
        # p 缺一个 -> 不命中
        missing = FakeMatcher(matches={**_hit("p.png"), **_hit("y.png")})
        assert _matches(page, missing) is False


# --------------------------------------------------------------------------- #
# 自己写函数当查询
# --------------------------------------------------------------------------- #
class TestCallableQuery:
    def test_a_bare_function_works_as_a_query(self):
        """``callable(frame) -> ActionResult`` 可以直接放进 ``queries``。"""

        def sees_a(frame) -> ActionResult:
            found = frame.find_image("a.png")
            if found.ok:
                return ActionResult.success(found.value)
            return ActionResult.not_found("没 a")

        page = Page("s", queries=(sees_a,))
        assert _matches(page, FakeMatcher(matches=_hit("a.png"))) is True
        assert _matches(page, FakeMatcher(matches={})) is False

    def test_a_function_can_combine_anything_inside(self):
        """函数内部随便组合 —— 这是"想怎么组合都行"的兜底。"""

        def either_way(frame) -> ActionResult:
            for name in ("a.png", "b.png", "c.png"):
                found = frame.find_image(name)
                if found.ok:
                    return ActionResult.success(found.value)
            return ActionResult.not_found("三张都没有")

        page = Page("s", queries=(either_way,))
        for present in ("a.png", "c.png"):
            assert _matches(page, FakeMatcher(matches=_hit(present))) is True, present
        assert _matches(page, FakeMatcher(matches={})) is False

    def test_a_function_that_raises_lands_in_the_log(self, caplog):
        """⚠️ 你的函数抛异常时，``locate`` **按"未命中"处理**（不是报错）。

        实测行为（这条测试钉的就是它）：页面级 ``match`` 把查询的 ``error``
        转成"这个页面没认出来"，只在日志里留一条 WARNING::

            WARNING  页面 's' 识别出错（按未命中处理）: ... 查询执行异常: 故意炸

        于是**"函数炸了"和"画面变了"在返回值上分不出来** —— 这是这里最容易
        骗到自己的一点。所以自己写的查询函数要：

        * **别让它抛** —— 拿不准就当"没命中"返回 ``not_found``；
        * 排查"怎么老是认不出来"时，**先翻日志有没有这条 WARNING**。

        （框架层面保留这个行为是有意的：单个查询炸了不该让整轮定位崩掉。
        但代价就是上面这条，所以写在这里。）
        """

        def boom(frame) -> ActionResult:  # pragma: no cover - 就是让它抛
            raise RuntimeError("故意炸")

        with caplog.at_level("WARNING"):
            result = _locate(Page("s", queries=(boom,)), FakeMatcher(matches={}))

        assert result.status.name == "SUCCESS", f"实际是 {result.status}：按未命中处理"
        assert result.value is not None
        assert result.value.id != "s", "抛异常的查询不该让页面命中"
        assert "故意炸" in caplog.text, "原始异常必须留在日志里，否则查不出来"

    def test_mixing_function_and_combinator(self):
        def any_of_two(frame) -> ActionResult:
            for name in ("a.png", "b.png"):
                if frame.find_image(name).ok:
                    return ActionResult.success(True)
            return ActionResult.not_found("都没有")

        page = Page("s", queries=(any_of_two, NotQuery(ImageQuery("bad.png"))))
        assert _matches(page, FakeMatcher(matches=_hit("b.png"))) is True
        vetoed = FakeMatcher(matches={**_hit("b.png"), **_hit("bad.png")})
        assert _matches(page, vetoed) is False


# --------------------------------------------------------------------------- #
# 快捷函数和手写等价 —— 连 roi 都要一样
# --------------------------------------------------------------------------- #
class TestShortcutIsEquivalentToSpellingItOut:
    """**这条是这次改动真正的价值。**

    组合查询自己没有 ``region`` 字段，所以 ``PageTree._specify`` 原来会把
    它们整个跳过 —— ``queries=(any_image(A, B),)`` 拿不到页面的 roi，
    而直接列两条能拿到。表现上只是"慢一点"（不做 roi 剪枝），不报错，
    所以很难发现。

    ⚠️ **断言必须查 region 的具体值**，不能只查"是不是 None"。
    第一版就是查 ``r is not None`` —— 而**旧行为也传 region**（只是传的
    是整帧 ``0,0,640,360``），所以那条断言对旧行为同样成立，等于没测。
    踩过之后改成"必须等于页面的 roi"。
    """

    ROI = Region(100, 200, 300, 160)

    @classmethod
    def _regions(cls, matcher: FakeMatcher, *names: str) -> list[Region | None]:
        return [region for name, region in matcher.calls if name in names]

    @classmethod
    def _assert_roi_applied(cls, matcher: FakeMatcher, *names: str) -> None:
        regions = cls._regions(matcher, *names)
        assert regions, f"{names} 里的查询根本没被跑"
        for region in regions:
            assert region is not None, f"{names}: 没拿到 region（旧行为会传整帧）"
            assert (region.x, region.y) == (cls.ROI.x, cls.ROI.y), (
                f"{names}: 传下去的 region 是 {region}，应该被页面的 roi 限制在 "
                f"{cls.ROI} 内 —— 说明组合查询没被套上 roi"
            )

    def test_roi_reaches_images_inside_an_or(self):
        matcher = FakeMatcher(matches=_hit("a.png"))
        page = Page("s", roi=self.ROI, queries=(any_image("a.png", "b.png"),))
        assert _matches(page, matcher) is True
        self._assert_roi_applied(matcher, "a.png", "b.png")

    def test_roi_reaches_images_inside_an_and(self):
        matcher = FakeMatcher(matches={**_hit("a.png"), **_hit("b.png")})
        page = Page("s", roi=self.ROI, queries=(all_images("a.png", "b.png"),))
        assert _matches(page, matcher) is True
        self._assert_roi_applied(matcher, "a.png", "b.png")

    def test_roi_reaches_images_inside_a_not(self):
        matcher = FakeMatcher(matches=_hit("a.png"))
        page = Page(
            "s",
            roi=self.ROI,
            queries=(ImageQuery("a.png"), NotQuery(ImageQuery("bad.png"))),
        )
        assert _matches(page, matcher) is True
        self._assert_roi_applied(matcher, "bad.png")

    def test_wrapped_and_listed_produce_the_same_regions(self):
        """最直接的等价性：两种写法传下去的 roi 一模一样。"""
        listed = FakeMatcher(matches={**_hit("a.png"), **_hit("b.png")})
        _locate(
            Page("s", roi=self.ROI, queries=(ImageQuery("a.png"), ImageQuery("b.png"))),
            listed,
        )
        wrapped = FakeMatcher(matches={**_hit("a.png"), **_hit("b.png")})
        _locate(Page("s", roi=self.ROI, queries=(all_images("a.png", "b.png"),)), wrapped)

        def relevant(matcher: FakeMatcher):
            return sorted(
                (name, region)
                for name, region in matcher.calls
                if name in ("a.png", "b.png") and region is not None
            )

        # 顺带钉住"手写那版确实带 roi"（否则两边都是整帧，比较就白比了）
        self._assert_roi_applied(listed, "a.png", "b.png")
        assert relevant(listed) == relevant(wrapped), (
            "``all_images`` 和『直接列两条』传下去的 roi 不一样"
        )


class TestExcludeStillWorks:
    """``exclude`` 是否决条件，和 ``queries`` 是两套（任一命中就排除）。"""

    def test_exclude_vetoes_an_otherwise_matching_page(self):
        page = Page("s", queries=(ImageQuery("a.png"),), exclude=(ImageQuery("no.png"),))
        vetoed = FakeMatcher(matches={**_hit("a.png"), **_hit("no.png")})
        assert _matches(page, vetoed) is False

    def test_without_the_veto_it_matches(self):
        page = Page("s", queries=(ImageQuery("a.png"),), exclude=(ImageQuery("no.png"),))
        assert _matches(page, FakeMatcher(matches=_hit("a.png"))) is True
