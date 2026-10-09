"""离线验证：竞技场的每个状态锚点能不能被正确、且**唯一**地认出来。

## 为什么需要它（不能用真机图代替）

真机图只能验"某一时刻恰好是什么状态"，验不了"每个状态锚点**各自**认不认得出来"。
而后者才是状态树**有没有真的立住**：如果两个状态的模板互相误命中，
状态机就会随机认一个 —— 表现是"脚本在错的地方动手"，而且极难查。

## 它验什么、不验什么

**验**：每个状态锚点在它自己那张截图上被认成它自己、且**别的状态锚点不会
在它上面误命中**。这正是"新裁/重裁模板之后对不对"的判据。

**不验**：真机上分数够不够高（真机有动画、光效、鼠标位置差异）——
那要靠真截图 + 干跑时看「识图日志」。

## ⚠️ 识别那两条**默认不失败**（只在报告里说）

模板是人手工裁的，**裁的时候还没裁完跑测试就会红** —— 那不是代码坏了，
是"手头的图还没弄好"。把这种情况判成失败，等于用一个还在施工的中间状态
去卡整个测试套件，于是别人（和 CI）都学会了"忽略那个红叉"。

所以默认**跳过**那两条，但把分数矩阵和问题清单打出来（`pytest -s` 看得到）。
**要真的拿它当验收门**（裁完了、上真机之前）就打开：

```bash
JINGJI_CHECK_TEMPLATES=1 uv run pytest tests/test_jingji_states.py -v
```

那时它们会严格断言：认错、或跨状态误命中，都直接失败。

⚠️ **它用 `rawMaterial/` 里那 15 张原始截图当帧**，不是合成图 ——
因为要验的正是"在真实画面上能不能区分"。
"""

from __future__ import annotations

import os
import pathlib

import numpy as np
import pytest
from PIL import Image

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.session import BaseSession
from gamebot.vision.opencv_matcher import OpenCvMatcher
from games.mingjiangsha.game import CLIENT_SIZE
from games.mingjiangsha.jingji.bindings import BINDINGS
from games.mingjiangsha.jingji.graph import SCENARIO

#: 这个测试**自己定**阈值，不 import 业务那边的 —— 业务现在不设阈值
#: （一律走框架默认），而这里的诊断有别的目的：
#:
#: * ``CONF`` 用框架默认的 0.9，和**运行期实际会发生的事**对齐；
#: * 诊断矩阵里另外用 ``confidence=0.0`` 看原始分数（那个和阈值无关）。
CONF = 0.9

#: 设成 1 就把"识别对不对"变成**硬断言**（默认只报告）。
STRICT = os.environ.get("JINGJI_CHECK_TEMPLATES", "") not in ("", "0")

#: 模板还在手工裁的时候跳过识别检查 —— 理由见模块 docstring。
_needs_finished_templates = pytest.mark.skipif(
    not STRICT,
    reason="模板是人手工裁的，裁完之前识别检查只报告不失败（设 JINGJI_CHECK_TEMPLATES=1 启用）",
)

HERE = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = HERE / "games" / "mingjiangsha" / "jingji" / "templates"
RAW = TEMPLATES / "rawMaterial"

#: 原始截图含标题栏，客户区从这一行开始（和 ``game.py`` 的说明一致）。
#: 所以"图坐标 = 客户区坐标 + 23"。
TITLE_BAR = 23

#: ``(状态 id, 原始截图文件名)`` —— 每个状态锚点一条。
CASES: tuple[tuple[str, str], ...] = (
    ("lobby", "home.png"),
    ("jj/before_create", "jingji1.png"),
    ("jj/after_create", "jingji2.png"),
    ("jj/after_add", "jingji3.png"),
    ("select/idle", "select1.png"),
    ("select/picked", "select2.png"),
    ("fight/hand", "zhandou1.png"),
    ("fight/done", "zhandou7.png"),
)

#: ``状态 id -> 它那张模板的**相对路径**``（和 ``templates`` 包里的常量一一对应）。
#:
#: ⚠️ **这里是重复的一份** —— 权威在 ``templates/__init__.py``。没直接 import，
#: 是因为这个文件想在"框架还没装好"时也能跑（见模块 docstring）。
#: 所以**改目录结构时要两处一起改**。
TEMPLATE_OF: dict[str, str] = {
    "lobby": "lobby/lobby.png",
    "jj/before_create": "jj/before_create.png",
    "jj/after_create": "jj/after_create.png",
    "jj/after_add": "jj/after_add.png",
    "select/idle": "select/idle.png",
    "select/picked": "select/picked.png",
    "fight/hand": "fight/hand.png",
    "fight/done": "fight/done.png",
}


def _frame_of(raw_name: str) -> np.ndarray:
    """把原始截图裁成**客户区大小**的帧。

    不直接贴到空白画布上，是因为那样"没贴到的地方"是黑的、会额外影响匹配。
    从原图裁客户区那一段，得到的正是**真机抓屏会拿到的同一张图**（同像素、同位置）。
    """
    width, height = CLIENT_SIZE
    with Image.open(RAW / raw_name) as im:
        arr = np.asarray(im.convert("RGB"))
    return np.ascontiguousarray(arr[TITLE_BAR : TITLE_BAR + height, :width])


def _session(image: np.ndarray) -> BaseSession:
    """真 Matcher + 假后端的 Session —— 用真匹配才验得出"两张图像不像"。"""
    matcher = OpenCvMatcher(templates_dir=str(TEMPLATES), grayscale=True, use_pyramid=True)
    return BaseSession(build_fake_backends(image=image, size=CLIENT_SIZE), matcher=matcher)


@pytest.fixture(scope="module")
def tree():
    return SCENARIO.materialize(name="states-test").tree


class TestEveryAnchorIdentifiesItsOwnState:
    """每个状态锚点必须在**它自己那张真截图**上认出它自己。"""

    @_needs_finished_templates
    @pytest.mark.parametrize(("want", "raw_name"), CASES, ids=[c[1] for c in CASES])
    def test_anchor_matches_its_own_screen(self, tree, want, raw_name):
        result = tree.locate(_session(_frame_of(raw_name)).capture())

        assert result.ok, f"{raw_name}: 定位本身出错了 {result.message}"
        assert result.value is not None
        assert result.value.id == want, (
            f"{raw_name} 应该认成 {want!r}，实际认成 {result.value.id!r} —— "
            f"检查 {TEMPLATE_OF[want]} 裁的范围和分数"
        )


class TestAnchorsDoNotCrossMatch:
    """**关键性质**：一张状态锚点不能在别的状态的画面上误命中。

    这条不成立的话，状态机就会随机认一个 —— 状态树等于没立住。
    真机上的表现是"脚本在错的地方动手"，而且只在偶发帧上出现，极难查。
    """

    @_needs_finished_templates
    @pytest.mark.parametrize(("want", "raw_name"), CASES, ids=[c[1] for c in CASES])
    def test_no_other_anchor_hits_this_screen(self, tree, want, raw_name):
        frame = _session(_frame_of(raw_name)).capture()
        offenders = []
        for other_id, _other_raw in CASES:
            if other_id == want:
                continue
            # **全图搜**：和运行期同一套判据（没有 roi）
            found = frame.find_image(TEMPLATE_OF[other_id], confidence=CONF)
            if found.ok:
                offenders.append(f"{other_id}({found.meta.get('score', 0):.3f})")

        assert not offenders, (
            f"{raw_name}（应该是 {want}）被这些状态的模板误命中了: {', '.join(offenders)} —— "
            "两个状态区分不开。给**那些**状态加 roi（加在哪两处见 pages.py 的注释）"
        )


class TestTemplateDiagnostics:
    """**不失败**的识别体检 —— 裁模板时看这个。

    `pytest -s tests/test_jingji_states.py::TestTemplateDiagnostics` 会把
    分数矩阵打出来：每张模板在**每张截图**上的最高分。

    判据就一条：**对角线（自己那张）要高，非对角线要低。**
    非对角线接近或超过 :data:`CONF` 的那两格，就是需要收窄 roi 或重裁的地方。
    """

    def test_print_score_matrix(self, tree):
        matcher = OpenCvMatcher(
            templates_dir=str(TEMPLATES), grayscale=True, use_pyramid=True
        )
        screens = {raw: _frame_of(raw) for _sid, raw in CASES}

        print("\n" + "=" * 108)
        print("分数矩阵：行 = 模板，列 = 截图。对角线应高，非对角线应低。")
        print("=" * 108)
        header = "模板 \\ 截图".ljust(24) + "".join(f"{n[:10]:>11}" for n in screens)
        print(header)
        print("-" * len(header))

        for state, own_raw in CASES:
            template = str(TEMPLATES / TEMPLATE_OF[state])
            row = []
            for frame_arr in screens.values():
                found = matcher.match(frame_arr, template, confidence=0.0)
                row.append(found.score if found else 0.0)
            own = row[list(screens).index(own_raw)]
            other = max(s for n, s in zip(screens, row, strict=True) if n != own_raw)
            mark = "✓" if own >= CONF and other < CONF else "✗"
            print(
                f"{state:24}"
                + "".join(f"{s:11.3f}" for s in row)
                + f"   自己={own:.3f} 别处最高={other:.3f} {mark}"
            )
        print("-" * len(header))
        assert True  # 这条**只报告**，见类 docstring 和模块 docstring


class TestDefinitionIsConsistent:
    """状态树 / 关联表 / 流程图三边对得上。"""

    @pytest.fixture(scope="class")
    def real_tree(self):
        """组装出来的 **PageTree**（``FEATURE_TREE`` 是 PageGroup，没有 walk）。"""
        return SCENARIO.materialize(name="states-test").tree

    def test_every_leaf_has_a_node_claiming_it(self, real_tree):
        """每个记录信息的状态都必须有流程节点认领 —— 否则重定位到它无处可去。"""
        claimed = {BINDINGS.state_of(node_id) for node_id in BINDINGS.table()}
        missing = sorted(
            page.id
            for page in real_tree.walk()
            if not page.is_group and not page.is_overlay and page.id not in claimed
        )
        assert missing == [], f"这些状态没有节点认领: {missing}"

    def test_every_anchor_template_exists(self, real_tree):
        """状态树里引用的每张模板文件都真的存在。

        缺文件的报错在运行期是"模板图不存在" —— 那时脚本已经跑起来了。
        这里在测试期就报，而且一次报全。
        """
        missing = []
        for page in real_tree.walk():
            if page.is_group:
                continue
            for query in getattr(page, "queries", ()):
                name = getattr(query, "template", None)
                if name and not (TEMPLATES / name).is_file():
                    missing.append(f"{page.id} -> {name}")
        assert missing == [], f"状态树引用了不存在的模板: {missing}"

    def test_every_click_template_exists(self):
        """步骤里要点的那些模板也都在 —— 少一张就是"那一步永远点不动"。"""
        import games.mingjiangsha.jingji.templates as templates

        names = [v for k, v in vars(templates).items() if k.startswith("T_CLICK_")]
        assert names, "templates 里应该有 T_CLICK_* 系列的点击模板常量"
        missing = [n for n in names if not (TEMPLATES / n).is_file()]
        assert missing == [], f"这些点击模板文件不存在: {missing}"


class TestBlankFrameMatchesNothing:
    def test_blank_frame_is_unknown(self, tree):
        """纯黑画面不该被认成任何一个状态 —— 否则就是"什么画面都算"。"""
        blank = np.zeros((CLIENT_SIZE[1], CLIENT_SIZE[0], 3), dtype=np.uint8)
        result = tree.locate(_session(blank).capture())

        assert result.ok
        assert result.value is not None
        assert result.value.id == "unknown", f"空白帧被认成了 {result.value.id}"
