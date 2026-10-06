"""离线验证：竞技场的每个状态锚点能不能被正确、且**唯一**地认出来。

## 为什么需要它（不能用真机图代替）

真机图只能验"某一时刻恰好是什么状态"，验不了"每个状态锚点**各自**认不认得出来"。
而后者才是状态树**有没有真的立住**：如果两个状态的模板互相误命中，
状态机就会随机认一个 —— 表现是"脚本在错的地方动手"，而且极难查。

## 它验什么、不验什么

**验**：每个状态锚点在它自己那张截图上被认成它自己、且**别的状态锚点不会
在它上面误命中**。这正是"重裁模板之后对不对"的判据。

**不验**：真机上分数够不够高（真机有动画、光效、鼠标位置差异）——
那要靠真截图 + 干跑时看「识图日志」。

## 怎么用它验证你重裁的模板

```bash
uv run pytest tests/test_jingji_states.py -v
```

* 全绿 -> 每张模板都只认自己那个状态，可以上真机试了；
* 红 -> 报错信息里会写清"谁的画面被谁的模板命中了、分数多少"，
  照着收窄 roi（优先）或换识别特征（下策）。

⚠️ **它用 `rawMaterial/` 里那 15 张原始截图当帧**，不是合成图 ——
因为要验的正是"在真实画面上能不能区分"。
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
from games.mingjiangsha.game import CLIENT_SIZE
from games.mingjiangsha.jingji.bindings import BINDINGS
from games.mingjiangsha.jingji.graph import SCENARIO
from games.mingjiangsha.jingji.pages import (
    CONF,
    ROI_FIGHT_DONE,
    ROI_FIGHT_HAND,
    ROI_JJ_BUTTON,
    ROI_JJ_START,
    ROI_LOBBY,
    ROI_SELECT_CONFIRM,
)

HERE = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = HERE / "games" / "mingjiangsha" / "jingji" / "templates"
RAW = TEMPLATES / "rawMaterial"

#: 原始截图含标题栏，客户区从这一行开始（和 ``game.py`` 的说明一致）。
#: 所以"图坐标 = 客户区坐标 + 23"。
TITLE_BAR = 23

#: ``(状态 id, 原始截图, 它的 roi)`` —— 每个状态锚点一条。
CASES: tuple[tuple[str, str, Region], ...] = (
    ("lobby", "home.png", ROI_LOBBY),
    ("jj/before_create", "jingji1.png", ROI_JJ_BUTTON),
    ("jj/after_create", "jingji2.png", ROI_JJ_BUTTON),
    ("jj/after_add", "jingji3.png", ROI_JJ_START),
    ("select/idle", "select1.png", ROI_SELECT_CONFIRM),
    ("select/picked", "select2.png", ROI_SELECT_CONFIRM),
    ("fight/hand", "zhandou1.png", ROI_FIGHT_HAND),
    ("fight/done", "zhandou7.png", ROI_FIGHT_DONE),
)


def _frame_of(raw_name: str) -> np.ndarray:
    """把原始截图裁成**客户区大小**的帧。

    为什么不是直接贴到空白画布上：那样"没贴到的地方"是黑的，
    会额外影响匹配。直接从原图裁客户区那一段，得到的就是**真机抓屏会拿到的
    同一张图**（同一像素、同一位置），检验才有效。
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

    @pytest.mark.parametrize(("want", "raw_name", "_roi"), CASES, ids=[c[1] for c in CASES])
    def test_anchor_matches_its_own_screen(self, tree, want, raw_name, _roi):
        result = tree.locate(_session(_frame_of(raw_name)).capture())

        assert result.ok, f"{raw_name}: 定位本身出错了 {result.message}"
        assert result.value is not None
        assert result.value.id == want, (
            f"{raw_name} 应该认成 {want!r}，实际认成 {result.value.id!r} —— "
            f"检查 {want.replace('/', '__')}.png 的裁剪范围和 pages.py 里的 roi"
        )


class TestAnchorsDoNotCrossMatch:
    """**关键性质**：一张状态锚点不能在别的状态的画面上误命中。

    这条不成立的话，状态机就会随机认一个 —— 状态树等于没立住。
    真机上的表现是"脚本在错的地方动手"，而且只在偶发帧上出现，极难查。
    """

    @pytest.mark.parametrize(("want", "raw_name", "_roi"), CASES, ids=[c[1] for c in CASES])
    def test_no_other_anchor_hits_this_screen(self, tree, want, raw_name, _roi):
        frame = _session(_frame_of(raw_name)).capture()
        offenders = []
        for other_id, _other_raw, other_roi in CASES:
            if other_id == want:
                continue
            # 直接问"这张模板会不会在这块区域命中" —— 和运行期同一套判据
            found = frame.find_image(
                f"{other_id.replace('/', '__')}.png", region=other_roi, confidence=CONF
            )
            if found.ok:
                offenders.append(f"{other_id}({found.meta.get('score', 0):.3f})")

        assert not offenders, (
            f"{raw_name}（应该是 {want}）被这些状态的模板误命中了: {', '.join(offenders)} —— "
            "两个状态区分不开。优先收窄 roi，其次换识别特征"
        )


class TestDefinitionIsConsistent:
    """状态树 / 关联表 / 流程图三边对得上。"""

    @pytest.fixture(scope="class")
    def real_tree(self):
        """组装出来的 **PageTree**（`FEATURE_TREE` 是 PageGroup，没有 walk）。"""
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
        import games.mingjiangsha.jingji.pages as pages

        names = [v for k, v in vars(pages).items() if k.startswith("T_CLICK_")]
        assert names, "pages.py 里应该有 T_CLICK_* 系列的点击模板常量"
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
