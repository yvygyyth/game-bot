"""竞技场 —— 自检与真机探针。

两者检查的是**不同的问题**，别混：

* :func:`run` —— 静态自检。这份定义成不成立？模板在不在？ROI 框得对不对？
  **认得出、但认错了地方**这类问题只有它能查出来。不需要游戏在跑，
  但需要一张参考画面（``prepare()`` 抓的）。
* :func:`probe_live` —— 真机探针。**现在**屏幕上能认出竞技入口吗？
  要游戏开着且在首页。

## 为什么"认准不准"要单独查

找得到但位置偏了，比找不到更危险 —— 下一步就照着这个点戳下去了。
而位置偏掉的原因往往很隐蔽：模板裁歪了几像素、ROI 起点算错、
换了分辨率、游戏窗口被拖动过。所以自检里有一条硬断言：
命中的中心必须落在期望点 ± 容差内。
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


def run(config: AppConfig) -> list[str]:
    """静态自检。打印每项结论，返回失败说明（空 = 全过）。"""
    failures: list[str] = []
    failures += _check_templates(config)
    failures += _check_definitions()
    failures += _check_geometry(config)
    failures += _check_detection_on_fixture(config)
    return failures


def probe_live(config: AppConfig) -> list[str]:
    """真机探针：抓一张当前画面试认竞技入口。返回失败说明（空 = 认出来了）。"""
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
    return _report_detection(frame, config, source="当前画面")


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
    """纯算术检查：ROI 能不能装下模板、期望中心在不在 ROI 里。

    这几条不需要任何图片就能查，而且正是"位置偏掉"最常见的几个来源。
    """
    problems: list[str] = []
    roots = config.template_roots()

    path = _resolve(config, T_JINGJI)
    if path is None:
        problems.append(f"{T_JINGJI}: 找不到文件（模板根 {[str(r) for r in roots]}）")
    else:
        image = cv2.imread(str(path))
        if image is None:
            problems.append(f"{T_JINGJI}: 读不出来，可能不是有效图片")
        else:
            height, width = image.shape[:2]
            if width > JINGJI_ROI.w or height > JINGJI_ROI.h:
                problems.append(
                    f"{T_JINGJI} {width}x{height} 比 ROI {JINGJI_ROI.w}x{JINGJI_ROI.h} 还大，"
                    "永远不可能在框内匹配到"
                )
            # 悬浮时卡片会往右上弹（实测位移 (+35,-32)）。ROI 要留得下这个位移，
            # 否则"鼠标正好停在卡上"这个状态会有一半掉到框外。
            left_pad = (JINGJI_CENTER.x - width / 2) - JINGJI_ROI.x
            top_pad = (JINGJI_CENTER.y - height / 2) - JINGJI_ROI.y
            if left_pad < 40:
                problems.append(f"ROI 左边距只有 {left_pad:.0f}px，装不下悬浮时的位移")
            if top_pad < 40:
                problems.append(f"ROI 上边距只有 {top_pad:.0f}px，装不下悬浮时的位移")

    if not 0 < CONF_JINGJI <= 1:
        problems.append(f"阈值 {CONF_JINGJI} 不合法")

    if not JINGJI_ROI.contains(JINGJI_CENTER):
        problems.append(
            f"期望中心 {JINGJI_CENTER.as_tuple()} 不在 ROI {JINGJI_ROI.to_tuple()} 里"
        )

    detail = (
        f"ROI {JINGJI_ROI.to_tuple()}，期望中心 {JINGJI_CENTER.as_tuple()}，"
        f"阈值 {CONF_JINGJI}"
    )
    return _report("几何一致", problems, detail=detail)


def _check_detection_on_fixture(config: AppConfig) -> list[str]:
    """在参考画面上真的跑一遍识别，并断言命中的位置。

    这是唯一能查出"认得出但认错地方"的检查。
    """
    from . import FIXTURES_DIR

    fixture = _game_root() / FIXTURES_DIR / "home.png"
    if not fixture.is_file():
        return _report(
            "参考画面上的识别",
            [],
            detail=f"跳过（没有 {fixture}）—— 跑 python -m games setup mingjiangsha/jingji 生成",
        )
    image = cv2.imread(str(fixture))
    if image is None:
        return _report("参考画面上的识别", [f"{fixture} 读不出来"])

    frame = _make_frame(image, config)
    return _report_detection(frame, config, source="参考画面")


def _report_detection(frame: Frame, config: AppConfig, *, source: str) -> list[str]:
    """在给定帧上跑识别，检查"认出了什么、认在哪"。返回失败说明。"""
    from ..shortcuts import find_jingji_entry

    ctx = _StubContext(frame)
    result = find_jingji_entry(ctx)

    if not result.ok or result.value is None:
        problem = f"{source}上认不出竞技入口：{result.message}"
        print(f"  ✗ {problem}")
        print("      如果游戏不在首页，或者窗口被移动/缩放过，就会出现这个")
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
        f"  {mark} {source}上认出了竞技入口：命中 ({point.x},{point.y})，"
        f"分数 {score:.3f}，偏离期望 {offset} 像素"
    )
    return [f"[{source}] {p}" for p in problems]


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _resolve(config: AppConfig, name: str) -> Path | None:
    for root in config.template_roots():
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _game_root() -> Path:
    from ..game import PROJECT_ROOT

    return PROJECT_ROOT


def _make_frame(image: object, config: AppConfig) -> Frame:
    """把一张 numpy 图包成 Frame，好让识别逻辑原样跑一遍。

    Frame 需要一个"有 ``matcher`` 的 session"才能找图，所以这里塞个最小的替身 ——
    比为了自检去构造一个真 Session 简单得多，也不会碰真实屏幕。
    """
    import numpy as np

    array = np.asarray(image)
    height, width = array.shape[:2]
    matcher = OpenCvMatcher(
        templates_dir=config.template_roots()[-1],
        extra_dirs=config.template_roots()[:-1],
        grayscale=config.vision.grayscale,
        use_pyramid=config.vision.use_pyramid,
        preload=False,
    )
    session = _StubSession(matcher)
    return Frame(array, Region(0, 0, width, height), session=session)


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
