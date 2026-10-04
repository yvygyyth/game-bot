"""竞技场 —— 自检与真机探针。

两者查的是**不同的问题**，别混：

* :func:`run` —— 静态自检。这份定义成不成立？模板在不在？认得出、认得准吗？
  不需要游戏在跑，但需要参考画面（``prepare()`` 抓的 fixtures）和
  你给的资产图（``assets/``）。
* :func:`probe_live` —— 真机探针。**现在**屏幕上认得出哪一页？

## 为什么"认得准不准"要单独查

找得到但位置偏了，比找不到更危险 —— 下一步就照着这个点戳下去了。
而位置偏掉的原因往往很隐蔽：模板裁歪了几像素、ROI 起点算错、
换了分辨率、游戏窗口被拖动过。所以自检里有一条硬断言：
命中的中心必须落在期望点 ± 容差内。

## 用资产图当回归样本

``assets/`` 里那四张图是**真实的四种状态**（首页悬浮 / 竞技场建队前 /
建队后 / 已准备）。自检拿它们当回归样本，能查出三类只有真实截图才暴露的问题：

1. 模板裁歪了（自己图上不是 1.0）；
2. 页面标识不稳（三种状态下分数就会掉）；
3. 按钮之间分不开（位置一样只有文字不同，最容易互相误命中）。
"""

from __future__ import annotations

from pathlib import Path

import cv2

from gamebot.atomic.frame import Frame
from gamebot.config.schema import AppConfig
from gamebot.types import Region
from gamebot.vision.opencv_matcher import OpenCvMatcher

from ..shortcuts import (
    CONF_JINGJI,
    JINGJI_CENTER,
    JINGJI_ROI,
    JINGJI_TOLERANCE,
    T_JINGJI,
)
from .pages import CONF_TITLE, JINGJI_PAGE_ROI
from .steps import (
    CONF_BUTTON,
    T_ADD_PET,
    T_CREATE_TEAM,
    T_START_MATCH,
    T_TITLE,
    TEAM_ROI,
)

#: 资产图目录（你放的四张截图）。这是**本地参考素材**，不入库。
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

#: 资产图含 1px 边框 + 31px 标题栏，客户区 = 资产图 [y+31, x+1]
ASSET_CLIENT_OFFSET = (1, 31)

#: 竞技场那三张（竞技场的三种状态）
JINGJI_STATES = ("jingji.png", "add-pet.png", "start.png")

#: 每个模板"应该在哪张图上拿满分"。首页那张竞技卡不是从资产图裁的 ——
#: 它取自实拍（资产图里的 home.png 是**悬浮态**，卡片被放大 1.1 倍并位移，
#: 所以空闲模板在它上面只有 0.774，那是正常的，不是问题）。
TEMPLATE_ORIGIN = {
    T_TITLE: "jingji.png",
    T_CREATE_TEAM: "jingji.png",
    T_ADD_PET: "add-pet.png",
    T_START_MATCH: "start.png",
}

#: 每种状态下，**顺序探测**应该选中哪个按钮。
#:
#: 这才是要验的不变式 —— 不是"按钮之间分数差多少"（开始匹配三种状态下都在，
#: 它本来就会在别的图上拿高分，那是对的）。要验的是：按 SEQUENCE 的顺序往下找，
#: 第一个过阈值的必须正好是这一步该点的那个。
EXPECTED_ACTION = {
    "jingji.png": T_CREATE_TEAM,
    "add-pet.png": T_ADD_PET,
    "start.png": T_START_MATCH,
}


def run(config: AppConfig) -> list[str]:
    """静态自检。打印每项结论，返回失败说明（空 = 全过）。"""
    failures: list[str] = []
    failures += _check_templates(config)
    failures += _check_definitions()
    failures += _check_geometry(config)
    failures += _check_assets(config)
    failures += _check_detection_on_fixture(config)
    return failures


# --------------------------------------------------------------------------- #
# 真机探针
# --------------------------------------------------------------------------- #
def probe_live(config: AppConfig) -> list[str]:
    """真机探针：抓一张当前画面，报出认得出哪一页。返回失败说明（空 = 认出来了）。"""
    print("真机探针：抓一张当前画面……")
    try:
        from gamebot.bootstrap import build_session_from_config

        session = build_session_from_config(config)
        with session:
            frame = session.capture()
    except Exception as exc:
        problem = f"抓屏失败: {type(exc).__name__}: {exc}"
        print(f"  ✗ {problem}")
        return [problem]

    print(f"  画面 {frame.size[0]}x{frame.size[1]}（客户区）")
    print()
    return _recognize(frame, source="当前画面")


def _recognize(frame: Frame, *, source: str) -> list[str]:
    """把这两页认出来：先看是不是首页，再看是不是竞技场。

    这不是通用的 ``PageTree.locate()``（那个还没实现），
    而是**只针对这两页**的窄实现 —— 够探针用，也让"到底认成了什么"说得清。
    """
    matcher_hits: list[str] = []

    # ① 首页？看竞技入口在不在
    entry = frame.find_image(T_JINGJI, region=JINGJI_ROI, confidence=CONF_JINGJI)
    if entry.ok and entry.value is not None:
        point = entry.value
        offset = max(abs(point.x - JINGJI_CENTER.x), abs(point.y - JINGJI_CENTER.y))
        line = (
            f"  ✓ 认出来了：**首页**（竞技入口在 ({point.x},{point.y})，"
            f"分数 {entry.meta.get('score', 0):.3f}，偏离期望 {offset} 像素）"
        )
        print(line)
        matcher_hits.append(line)
        # 首页上还能顺便看出队伍流程有没有在跑 —— 不算失败，只报告
        for template, label in (
            (T_CREATE_TEAM, "创建队伍"),
            (T_ADD_PET, "添加伙伴"),
            (T_START_MATCH, "开始匹配"),
        ):
            hit = frame.find_image(template, region=TEAM_ROI, confidence=CONF_BUTTON)
            if hit.ok:
                print(f"      · 右下角还看到「{label}」({hit.meta.get('score', 0):.3f})")

    # ② 竞技场？看左上角标题
    title = frame.find_image(T_TITLE, region=JINGJI_PAGE_ROI, confidence=CONF_TITLE)
    if title.ok and title.value is not None:
        print(
            f"  ✓ 认出来了：**竞技场**（标题分数 {title.meta.get('score', 0):.3f}）"
        )
        matcher_hits.append("jingji")
        _report_team_state(frame)

    if not matcher_hits:
        problem = (
            f"{source}上这两页都不像 —— 既没看到首页的竞技入口，"
            "也没看到竞技场的标题"
        )
        print(f"  ✗ {problem}")
        print("      可能是：游戏在别的页面 / 窗口被移动或缩放 / 分辨率变了")
        return [problem]

    return []


def _report_team_state(frame: Frame) -> None:
    """在竞技场上报告队伍流程走到哪一步了（不参与成败判断）。"""
    for template, label in (
        (T_CREATE_TEAM, "还没建队（看到「创建队伍」）"),
        (T_ADD_PET, "已建队（看到「添加伙伴」）"),
        (T_START_MATCH, "可以匹配（看到「开始匹配」）"),
    ):
        hit = frame.find_image(template, region=TEAM_ROI, confidence=CONF_BUTTON)
        if hit.ok:
            print(f"      · 当前状态：{label}  分数 {hit.meta.get('score', 0):.3f}")


# --------------------------------------------------------------------------- #
# 各项检查
# --------------------------------------------------------------------------- #
def _check_templates(config: AppConfig) -> list[str]:
    from gamebot.bootstrap import check_templates

    from . import build_scenario

    missing = check_templates(config, build_scenario())
    problems = [f"缺 {len(missing)} 个: {', '.join(missing)}"] if missing else []
    roots = " / ".join(str(p) for p in config.template_roots())
    return _report("模板文件齐全", problems, detail=roots)


def _check_definitions() -> list[str]:
    from . import build_scenario

    try:
        build_scenario().validate()
    except Exception as exc:
        return _report("定义校验", [f"{type(exc).__name__}: {exc}"])
    return _report("定义校验", [], detail="页面树 + 流程图")


def _check_geometry(config: AppConfig) -> list[str]:
    """纯算术检查：ROI 装得下模板吗？期望点在框里吗？阈值合法吗？

    不需要任何图片就能查，而且正是"位置偏掉"最常见的几个来源。
    """
    problems: list[str] = []

    # ① 首页的竞技卡：ROI 要装得下它，还要留得下悬浮时的位移（实测 (+27,-41)）
    card = _size_of(config, T_JINGJI)
    if card is None:
        problems.append(f"{T_JINGJI}: 找不到或读不出来")
    else:
        width, height = card
        if width > JINGJI_ROI.w or height > JINGJI_ROI.h:
            problems.append(f"{T_JINGJI} {width}x{height} 比 ROI 还大，永远匹配不到")
        left_pad = (JINGJI_CENTER.x - width / 2) - JINGJI_ROI.x
        top_pad = (JINGJI_CENTER.y - height / 2) - JINGJI_ROI.y
        # 悬浮时卡片往右上弹 27/41 像素
        if left_pad < 30:
            problems.append(f"ROI 左边距只有 {left_pad:.0f}px，装不下悬浮位移 (+27)")
        if top_pad < 45:
            problems.append(f"ROI 上边距只有 {top_pad:.0f}px，装不下悬浮位移 (-41)")

    # ② 竞技场的标题：页面 ROI 要装得下它
    title = _size_of(config, T_TITLE)
    if title is None:
        problems.append(f"{T_TITLE}: 找不到或读不出来")
    elif title[0] > JINGJI_PAGE_ROI.w or title[1] > JINGJI_PAGE_ROI.h:
        problems.append(f"{T_TITLE} {title[0]}x{title[1]} 比页面 ROI 还大")

    # ③ 三个按钮：都要装得进按钮 ROI
    for name in (T_CREATE_TEAM, T_ADD_PET, T_START_MATCH):
        size = _size_of(config, name)
        if size is None:
            problems.append(f"{name}: 找不到或读不出来")
        elif size[0] > TEAM_ROI.w or size[1] > TEAM_ROI.h:
            problems.append(f"{name} {size[0]}x{size[1]} 比按钮 ROI 还大")

    # ④ 阈值
    for label, value in (
        ("竞技入口", CONF_JINGJI),
        ("竞技场标题", CONF_TITLE),
        ("队伍按钮", CONF_BUTTON),
    ):
        if not 0 < value <= 1:
            problems.append(f"{label}的阈值 {value} 不合法")

    if not JINGJI_ROI.contains(JINGJI_CENTER):
        problems.append(f"期望中心 {JINGJI_CENTER.as_tuple()} 不在首页 ROI 里")

    detail = (
        f"首页 ROI {JINGJI_ROI.to_tuple()} / 页面 ROI {JINGJI_PAGE_ROI.to_tuple()} / "
        f"按钮 ROI {TEAM_ROI.to_tuple()}"
    )
    return _report("几何一致", problems, detail=detail)


def _check_assets(config: AppConfig) -> list[str]:
    """用你给的四张真实截图做回归。资产图不在时跳过（它们不入库）。"""
    if not ASSETS_DIR.is_dir():
        return _report(
            "资产图回归",
            [],
            detail=f"跳过（没有 {ASSETS_DIR}）—— 那是本地参考素材，不入库",
        )

    templates_dir = config.template_roots()[-1]
    matcher = OpenCvMatcher(
        templates_dir=templates_dir,
        extra_dirs=config.template_roots()[:-1],
        grayscale=config.vision.grayscale,
        use_pyramid=config.vision.use_pyramid,
        preload=True,
    )
    images = {
        path.name: cv2.imread(str(path))
        for path in sorted(ASSETS_DIR.glob("*.png"))
        if cv2.imread(str(path)) is not None
    }
    problems: list[str] = []
    checked = 0

    # ① 每个模板在自己那张图上必须是满分
    for template, origin in TEMPLATE_ORIGIN.items():
        image = images.get(origin)
        if image is None:
            problems.append(f"{template}: 找不到来源图 {origin}")
            continue
        hit = matcher.match(image, template, confidence=0.0)
        checked += 1
        if hit is None or hit.score < 0.95:
            got = "未命中" if hit is None else f"{hit.score:.3f}"
            problems.append(f"{template} 在来源图 {origin} 上只有 {got}，模板裁歪了？")

    # ② 页面标识在竞技场的三种状态下都要稳
    title_scores: list[str] = []
    for name in JINGJI_STATES:
        image = images.get(name)
        if image is None:
            continue
        hit = matcher.match(image, T_TITLE, confidence=0.0)
        score = hit.score if hit else 0.0
        title_scores.append(f"{name}={score:.3f}")
        checked += 1
        if score < CONF_TITLE:
            problems.append(
                f"竞技场标题在 {name} 上只有 {score:.3f} < {CONF_TITLE} —— "
                "页面标识不稳，那一步会认不出自己在哪一页"
            )

    # ③ 顺序探测在每种状态下都必须选中正确的按钮
    sequence = (T_CREATE_TEAM, T_ADD_PET, T_START_MATCH)
    print(f"      {'状态':>14s}{'创建队伍':>12s}{'添加伙伴':>12s}{'开始匹配':>12s}   会点哪个")
    for name, expected in EXPECTED_ACTION.items():
        image = images.get(name)
        if image is None:
            problems.append(f"缺少资产图 {name}")
            continue
        scores: list[float] = []
        picked = ""
        for template in sequence:
            hit = matcher.match(image, template, confidence=0.0)
            score = hit.score if hit else 0.0
            scores.append(score)
            checked += 1
            if not picked and score >= CONF_BUTTON:
                picked = template
        print(
            f"      {name:>14s}"
            + "".join(f"{s:>12.3f}" for s in scores)
            + f"   {picked or '（都不点）'}"
        )
        if picked != expected:
            problems.append(
                f"{name}: 顺序探测会点 {picked or '（都不点）'}，应该是 {expected}"
                f" —— 阈值 {CONF_BUTTON} 要调，或者模板拿错了"
            )

    detail = (
        f"{len(images)} 张资产图，{checked} 次匹配；"
        f"标题分数 {' '.join(title_scores) if title_scores else '—'}"
    )
    return _report("资产图回归", problems, detail=detail)


def _check_detection_on_fixture(config: AppConfig) -> list[str]:
    """在参考画面上真的跑一遍识别，并断言命中的位置。

    这是唯一能查出"认得出但认错地方"的检查。
    """
    from . import FIXTURES_DIR, _project_root

    fixture = _project_root() / FIXTURES_DIR / "home.png"
    if not fixture.is_file():
        return _report(
            "参考画面上的识别",
            [],
            detail=(
                f"跳过（没有 {fixture}）—— "
                "跑 python -m games setup mingjiangsha/jingji 生成"
            ),
        )
    image = cv2.imread(str(fixture))
    if image is None:
        return _report("参考画面上的识别", [f"{fixture} 读不出来"])

    frame = _make_frame(image, config)
    from ..shortcuts import find_jingji_entry

    result = find_jingji_entry(_StubContext(frame))
    if not result.ok or result.value is None:
        problem = f"参考画面上认不出竞技入口：{result.message}"
        print(f"  ✗ {problem}")
        print("      抓参考画面的时候游戏不在首页？")
        return [problem]

    point = result.value
    score = float(result.meta.get("score", 0.0))
    offset = max(abs(point.x - JINGJI_CENTER.x), abs(point.y - JINGJI_CENTER.y))
    problems: list[str] = []
    if offset > JINGJI_TOLERANCE:
        problems.append(
            f"位置偏了 {offset} 像素：命中 ({point.x},{point.y})，"
            f"期望 ({JINGJI_CENTER.x},{JINGJI_CENTER.y}) ± {JINGJI_TOLERANCE}"
        )
    if not JINGJI_ROI.contains(point):
        problems.append(f"命中点 ({point.x},{point.y}) 落在 ROI 外面 —— ROI 逻辑有问题")

    mark = "✓" if not problems else "✗"
    print(
        f"  {mark} 参考画面上认出了竞技入口：命中 ({point.x},{point.y})，"
        f"分数 {score:.3f}，偏离期望 {offset} 像素"
    )
    return [f"[参考画面] {p}" for p in problems]


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _resolve(config: AppConfig, name: str) -> Path | None:
    for root in config.template_roots():
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _size_of(config: AppConfig, name: str) -> tuple[int, int] | None:
    path = _resolve(config, name)
    if path is None:
        return None
    image = cv2.imread(str(path))
    if image is None:
        return None
    height, width = image.shape[:2]
    return width, height


def _make_frame(image: object, config: AppConfig) -> Frame:
    """把一张 numpy 图包成 Frame，好让识别逻辑原样跑一遍。

    Frame 需要一个"有 ``matcher`` 的 session"才能找图，所以这里塞个最小的替身 ——
    比为了自检去构造一个真 Session 简单得多，也不会碰真实屏幕。
    """
    import numpy as np

    array = np.asarray(image)
    height, width = array.shape[:2]
    roots = config.template_roots()
    matcher = OpenCvMatcher(
        templates_dir=roots[-1],
        extra_dirs=roots[:-1],
        grayscale=config.vision.grayscale,
        use_pyramid=config.vision.use_pyramid,
        preload=False,
    )
    return Frame(array, Region(0, 0, width, height), session=_StubSession(matcher))


class _StubSession:
    """只为 ``Frame._matcher()`` 存在的替身。"""

    def __init__(self, matcher: OpenCvMatcher) -> None:
        self.matcher = matcher
        self.reader = None


class _StubContext:
    """只为识别逻辑存在的替身：它只用到 ``frame()`` 和 ``invalidate_frame()``。"""

    def __init__(self, frame: Frame) -> None:
        self._frame = frame

    def frame(self, *args: object, **kwargs: object) -> Frame:
        return self._frame

    def invalidate_frame(self) -> None:
        pass


def _report(name: str, problems: list[str], *, detail: str = "") -> list[str]:
    mark = "✓" if not problems else "✗"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {mark} {name}{suffix}")
    for problem in problems:
        print(f"      - {problem}")
    return [f"[{name}] {p}" for p in problems]
