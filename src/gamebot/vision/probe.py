"""真机探针 —— "现在屏幕上认得出什么"。

和自检（``checks.run_checks``）是两件事：

* 那个查"**这份定义**成不成立"（静态、不需要游戏在跑）；
* 这个查"**现在**屏幕上认得出什么"（要游戏开着）。

## 为什么故意不短路

跑流程用的 :meth:`PageTree.locate` 是**短路**的：按优先级找到第一个命中的状态就
返回（快，而且和流程自己的判断完全一致）。探针要的恰恰相反 —— 它要的是**全貌**：

* 一个组都没认出来 → 失败，说明游戏不在预期界面（或者窗口/分辨率不对）；
* **两组都认出来了** → 也是重要信息：画面被叠了、或者分辨率不对；
* 认出来了但**位置偏了** → 最危险的情况，下一步就照着这个点戳下去。

所以这里把 ``ChecksSpec.groups`` 里的每一项都查一遍，逐个报告。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..types import Region

if TYPE_CHECKING:
    from ..atomic.frame import Frame
    from ..config.schema import AppConfig
    from .checks import ChecksSpec

__all__ = ["capture_now", "check_entries_on_frame", "load_frame_image"]


def capture_now(spec: ChecksSpec, config: AppConfig) -> Frame:
    """抓一张真机画面（客户区）。探针用。"""
    from ..bootstrap import build_session_from_config

    session = build_session_from_config(config)
    with session:
        return session.capture()


def load_frame_image(spec: ChecksSpec, config: AppConfig) -> Frame | str | None:
    """把参考图读成一个 :class:`Frame`。

    :return: ``Frame`` / 出错说明（str）/ ``None``（没有参考图，跳过）。
    """
    import cv2

    path = spec.fixture_path
    if path is None or not Path(path).is_file():
        return None
    image = cv2.imread(str(path))
    if image is None:
        return f"参考图读不出来: {path}"
    height, width = image.shape[:2]
    return _wrap_frame(image, Region(0, 0, width, height), config)


def check_entries_on_frame(
    spec: ChecksSpec,
    frame: Frame,
    *,
    require_all: bool = True,
) -> list[str]:
    """在给定帧上逐个查 :class:`ChecksSpec` 里的东西，打印结论，返回失败说明。

    :param require_all: ``True``（真机探针）：所有标了 ``required`` 的组都必须
        认出来 —— "至少得认出这是哪一页"。
        ``False``（参考画面）：**只把 ``spec.fixture_group`` 那一组当作必须** ——
        参考图就是一张特定界面的截图（名将杀抓的是首页），要求它在同一张图上
        同时认出竞技场是不讲道理的。但**位置偏差照样要查**（那是这张图存在的
        理由：验"认得准不准"，而不只是"认不认得出"）。

    判定规则：

    * 必须认出来的组一个都没命中 → 失败；
    * 认出来了的每一项都报告分数 + 偏离期望多少像素；
    * 偏离超过 ``entry.tolerance`` → 失败（"认得出但认错地方"最危险）；
    * **命中点落在 ROI 外面** → 失败（ROI 逻辑有问题）。
    """
    found_groups: set[str] = set()
    required = _required_groups(spec) if require_all else {spec.fixture_group}
    problems: list[str] = []
    reports: list[str] = []

    for group in spec.groups:
        hits: list[str] = []
        for entry in group.entries:
            found = frame.find_image(
                entry.template,
                region=entry.roi,
                confidence=entry.confidence,
            )
            if not found.ok or found.value is None:
                continue
            point = found.value
            score = float(found.meta.get("score", 0.0) or 0.0)
            offset = max(abs(point.x - entry.point.x), abs(point.y - entry.point.y))
            line = (
                f"{entry.name}: ({point.x},{point.y}) 分数 {score:.3f} "
                f"偏离期望 {offset} 像素"
            )
            hits.append(line)
            if offset > entry.tolerance:
                problems.append(
                    f"{entry.name} 位置偏了 {offset} 像素：命中 "
                    f"({point.x},{point.y})，期望 ({entry.point.x},{entry.point.y}) "
                    f"± {entry.tolerance}"
                )
            if entry.roi is not None and not entry.roi.contains(point):
                problems.append(
                    f"{entry.name} 命中点 ({point.x},{point.y}) 落在 ROI 外面 —— ROI 逻辑有问题"
                )

        if hits:
            found_groups.add(group.name)
            for line in hits:
                reports.append(f"  ✓ {group.name}：{line}")
        elif group.name in required:
            problems.append(
                f"{group.name} 没认出来 —— "
                "可能是：游戏在别的界面 / 窗口被移动或缩放 / 分辨率变了"
            )

    for line in reports:
        print(line)
    for problem in problems:
        print(f"  ✗ {problem}")

    # "不止一组认出来了"是有用信息，不是失败 —— 说明画面可能被叠了
    if require_all and len(found_groups) > 1 and not problems:
        print(
            f"  · 注意：{'、'.join(sorted(found_groups))} 都认出来了。"
            "正常情况只会命中一组 —— 画面被叠了或者分辨率不对？"
        )
    return problems


def _required_groups(spec: ChecksSpec) -> set[str]:
    return {group.name for group in spec.groups if group.required}


def _wrap_frame(image: Any, origin: Region, config: AppConfig) -> Frame:
    """把一张 numpy 图包成 ``Frame``，好让识别逻辑原样跑一遍。

    ``Frame`` 需要一个"有 ``matcher`` 的 session"才能找图，所以这里塞个最小替身 ——
    比为了自检去构造一个真 ``Session`` 简单得多，也不会碰真实屏幕。
    """
    import numpy as np

    from ..atomic.frame import Frame as FrameClass
    from .checks import _matcher

    array = np.asarray(image)
    return FrameClass(array, origin, session=_StubSession(_matcher(config)))


class _StubSession:
    """只为 ``Frame._matcher()`` 存在的替身。"""

    def __init__(self, matcher: Any) -> None:
        self.matcher = matcher
        self.reader = None
