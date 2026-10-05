"""通用的识别检查 —— **逻辑在这里，数值在业务层**。

## 这个模块只做两件事

1. **几何一致**（纯算术，不需要图片）：模板装得进它的搜索范围吗？
   留得下悬停位移吗？期望点在自己的框里吗？阈值合法吗？
2. **参考画面上的识别**（需要一张 ``prepare()`` 抓的真机截图）：
   真跑一遍识别，并断言**命中的位置**。

## 为什么"几何一致"值得单独做

名将杀首页的卡片**静止时在中间、鼠标一悬停就往右上弹 `(+27, -41)` 像素**。
搜索范围留小了，你一划过入口模板就滑出范围、匹配不到 —— 而这是
**静态看代码完全看不出来**的错，只能跑到那一屏才发现。

所以 :class:`EntrySpec.hover` 就是声明这个位移量的地方，检查会算出
"从期望中心到框边界还剩多少"，不够就报出来。

同一个道理还有两条纯算术的错：**模板比它的搜索范围还大**（永远匹配不到）、
**阈值不在 0~1 之间**。

## 为什么"参考画面"那一项要断言位置

"认得出但认错地方"比"认不出"更危险 —— 下一步就照着这个点戳下去了。
位置偏掉的原因往往很隐蔽：模板裁歪几像素、ROI 起点算错、换了分辨率、
窗口被拖动过。所以它不只报"认出来了"，还要报**偏离期望多少像素**。

## 为什么不在这里查"模板文件在不在"

那归 ``games check``（框架的通用检查，所有脚本共用一份）。
在脚本里再写一遍等于同一件事两个出处：改了框架那边这边不会跟着变，
两边还会给出不一样的说法。

## 关于曾经有过的"资产图回归"

早期这里还有一项：拿几张真机截图当回归样本，验"模板在自己那张图上必须满分"
（= 裁歪没有）、"页面标识在几种状态下都稳"、"按钮顺序探测会点哪个"。

它被去掉了，原因是**样本图不入库、实际也没人维护** —— 而留着它有个真问题：
目录不存在时它报的是"✓ 跳过"，**打绿勾**。那比没有这项更糟：
加新脚本时你会看到一个勾，以为验过了，其实一张样本都没有。

真要有回归样本，正确做法是把它做成**测试**（放 ``tests/``，样本随测试一起
入库），而不是一个"没有样本就算过"的自检项。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..types import Point, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from ..config.schema import AppConfig

log = get_logger("vision.checks")

__all__ = [
    "ChecksSpec",
    "EntryGroup",
    "EntrySpec",
    "SequenceSpec",
    "run_checks",
    "run_probe",
]


@dataclass(frozen=True, slots=True)
class EntrySpec:
    """一个"要认出来的东西"：模板 + 它该命中的位置 + 它的搜索范围。

    :param hover: 悬停/位移动画会让这个模板移动多少像素（``(+27, -41)`` 这种）。
        给了就会**自动检查搜索范围的余量够不够** —— 见模块 docstring。
    """

    template: str
    point: Point
    confidence: float
    tolerance: int = 15
    roi: Region | None = None
    hover: Point | None = None
    label: str = ""

    @property
    def name(self) -> str:
        return self.label or self.template


@dataclass(frozen=True, slots=True)
class SequenceSpec:
    """一组"按顺序找一个能点的"模板 —— 验的是**探测顺序的不变式**。

    要验的不是"按钮之间分数差多少"（有些按钮天然会在别的状态上拿高分，
    比如名将杀的「开始匹配」在三种状态下都是 0.999），而是：

    > 按 ``templates`` 的顺序往下找，第一个过 ``confidence`` 的，
    > 必须正好是这一步该点的那个。

    :param expected: ``{样本图名: 该选中的模板}``。早期用它做"资产图回归"，
    现在没有样本图了，这个字段留给以后要做回归时用（那时应该做成测试）。
    """

    templates: tuple[str, ...]
    roi: Region
    confidence: float
    names: tuple[str, ...] = ()
    expected: Mapping[str, str] = field(default_factory=dict)

    def label_of(self, template: str) -> str:
        """给人看的名字（``names`` 和 ``templates`` 一一对应）。"""
        try:
            index = self.templates.index(template)
        except ValueError:
            return template
        if index < len(self.names):
            return self.names[index]
        return Path(template).name


@dataclass(frozen=True, slots=True)
class EntryGroup:
    """一组"同时该被认出来"的东西 —— 通常就是一个界面的标识。

    :param required: 真机探针里"一个都没认出来"算不算失败。给 ``True`` 的是
        "我至少得认出这是哪一页"；给 ``False`` 的是"顺便报告一下"
        （比如竞技场那三个按钮的当前状态，用来诊断走到哪一步了）。
    """

    name: str
    entries: tuple[EntrySpec, ...]
    required: bool = True


@dataclass(frozen=True, slots=True)
class ChecksSpec:
    """一个脚本要检查的全部内容。**业务层只写这个。**

    :param fixture_path: 参考图（``prepare()`` 抓的那张）的**完整路径**，
        用来验"位置偏没偏"。``None`` 或文件不存在就跳过。

        为什么是路径而不是文件名：**框架不去猜业务层的目录约定**。
        那是业务层自己的事（名将杀放在 ``games/mingjiangsha/fixtures/``，
        别的游戏可以放别处），框架只认一个路径 —— 猜约定就是第二份事实来源。
    :param fixture_group: 参考图对应 :attr:`groups` 里的哪一组。参考图是
        **一张特定界面**的截图，所以只要求那一组必须认出来 ——
        要求它在同一张图上同时认出别的页面是不讲道理的。
        位置偏差照样全查（那正是这张参考图的用途）。
    """

    title: str
    entries: tuple[EntrySpec, ...] = ()
    groups: tuple[EntryGroup, ...] = ()
    sequences: tuple[SequenceSpec, ...] = ()
    fixture_path: Path | None = None
    fixture_group: str = ""


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def run_checks(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """跑静态自检。打印每项结论，返回失败说明（空 = 全过）。

    **只管业务层独有的那几项。** "模板文件在不在""定义自不自洽"归通用的
    ``games check``。
    """
    failures: list[str] = []
    failures += _check_geometry(spec, config)
    failures += _check_fixture(spec, config)
    return failures


def _check_geometry(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """纯算术检查：装得下吗？留够位移余量吗？期望点在框里吗？阈值合法吗？"""
    problems: list[str] = []

    for entry in spec.entries:
        size = _template_size(config, entry.template)
        if size is None:
            problems.append(f"{entry.template}: 找不到或读不出来")
            continue
        width, height = size
        if entry.roi is not None:
            problems += _roi_fit(entry, width, height)
            if not entry.roi.contains(entry.point):
                problems.append(
                    f"{entry.name}: 期望中心 {entry.point.as_tuple()} 不在它的搜索范围 "
                    f"{entry.roi.to_tuple()} 里"
                )
        problems += _threshold_check(entry.name, entry.confidence)

    for sequence in spec.sequences:
        problems += _threshold_check(_sequence_name(sequence), sequence.confidence)
        for template in sequence.templates:
            size = _template_size(config, template)
            if size is None:
                problems.append(f"{template}: 找不到或读不出来")
            elif size[0] > sequence.roi.w or size[1] > sequence.roi.h:
                problems.append(
                    f"{template} {size[0]}x{size[1]} 比搜索范围 {sequence.roi.to_tuple()} "
                    "还大，永远匹配不到"
                )

    return _report("几何一致", problems, detail=_geometry_detail(spec))


def _roi_fit(entry: EntrySpec, width: int, height: int) -> list[str]:
    """模板装得进搜索范围吗？留得下位移吗？"""
    problems: list[str] = []
    roi = entry.roi
    assert roi is not None  # 调用方已经判过

    if width > roi.w or height > roi.h:
        problems.append(
            f"{entry.name} {width}x{height} 比它的搜索范围 {roi.to_tuple()} 还大，"
            "永远匹配不到"
        )
        return problems

    left = (entry.point.x - width / 2) - roi.x
    top = (entry.point.y - height / 2) - roi.y
    right = roi.right - (entry.point.x + width / 2)
    bottom = roi.bottom - (entry.point.y + height / 2)

    if entry.hover is None:
        # 没声明位移：只要求摆下去不伸出去
        if min(left, top, right, bottom) < 0:
            problems.append(
                f"{entry.name}: 模板按期望中心摆下去会伸出搜索范围 "
                f"（左{left:.0f} 上{top:.0f} 右{right:.0f} 下{bottom:.0f}）"
            )
        return problems

    dx, dy = entry.hover.x, entry.hover.y
    for side, margin, need, value in (
        ("左", left, max(0, -dx), dx),
        ("右", right, max(0, dx), dx),
        ("上", top, max(0, -dy), dy),
        ("下", bottom, max(0, dy), dy),
    ):
        if margin < need:
            problems.append(
                f"{entry.name}: 搜索范围{side}边距只有 {margin:.0f}px，"
                f"装不下位移 ({value:+d})"
            )
    return problems


def _check_fixture(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """在参考画面上真跑一遍识别，并断言**命中的位置**。

    这是唯一能查出"认得出但认错地方"的检查 —— 而认错地方比认不出来更危险：
    下一步就照着这个点戳下去了。
    """
    if spec.fixture_path is None:
        return []
    if not Path(spec.fixture_path).is_file():
        return _report(
            "参考画面上的识别",
            [],
            detail=f"跳过（还没有 {spec.fixture_path}）—— 跑 games setup 生成",
        )

    from .probe import check_entries_on_frame, load_frame_image

    loaded = load_frame_image(spec, config)
    if loaded is None:
        return []
    if isinstance(loaded, str):
        return _report("参考画面上的识别", [loaded])

    problems = check_entries_on_frame(spec, loaded, require_all=False)
    mark = "✓" if not problems else "✗"
    print(f"  {mark} 参考画面上的识别")
    return [f"[参考画面] {p}" for p in problems]


# --------------------------------------------------------------------------- #
# 真机探针
# --------------------------------------------------------------------------- #
def run_probe(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """真机探针：抓一张当前画面，报出认得出哪些东西。返回失败说明。

    和自检的区别：那个查"这份定义成不成立"（不需要游戏在跑），
    这个查"**现在**屏幕上认不认得出来"。

    **故意不短路**：所有 ``groups`` 都查一遍，而不是认到一个就返回。
    因为"不止一组都认出来了"本身就是有用的信息（窗口被叠了、分辨率不对）——
    跑流程用的定位要短路（快、且和流程判断一致），探针要的是全貌。
    """
    from .probe import capture_now, check_entries_on_frame

    print(f"{spec.title}真机探针：抓一张当前画面……")
    try:
        frame = capture_now(spec, config)
    except Exception as exc:
        problem = f"抓屏失败: {type(exc).__name__}: {exc}"
        print(f"  ✗ {problem}")
        return [problem]

    print(f"  画面 {frame.size[0]}x{frame.size[1]}（客户区）")
    print()
    problems = check_entries_on_frame(spec, frame)
    if not problems:
        print("  ✓ 认出来了")
    return problems


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _report(name: str, problems: list[str], *, detail: str = "") -> list[str]:
    mark = "✓" if not problems else "✗"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {mark} {name}{suffix}")
    for problem in problems:
        print(f"      - {problem}")
    return [f"[{name}] {p}" for p in problems]


def _template_size(config: AppConfig, name: str) -> tuple[int, int] | None:
    import cv2

    for root in config.template_roots():
        candidate = root / name
        if candidate.is_file():
            image = cv2.imread(str(candidate))
            if image is None:
                return None
            height, width = image.shape[:2]
            return width, height
    return None


def _matcher(config: AppConfig):
    """造一个按当前配置的模板匹配器。

    公开是给 :mod:`.probe` 用的 —— 探针要把一张静态图包成 ``Frame`` 再跑识别，
    而 ``Frame`` 需要一个"有 matcher 的 session"。**共用这一份**而不是各造一个：
    两边的灰度/多尺度设置必须一致，否则"自检说认得出来、真机认不出"。
    """
    from .opencv_matcher import OpenCvMatcher

    roots = config.template_roots()
    return OpenCvMatcher(
        templates_dir=roots[-1],
        extra_dirs=roots[:-1],
        grayscale=config.vision.grayscale,
        use_pyramid=config.vision.use_pyramid,
        preload=False,
    )


def _threshold_check(label: str, value: float) -> list[str]:
    if not 0 < value <= 1:
        return [f"{label} 的阈值 {value} 不合法（必须在 0~1 之间）"]
    return []


def _sequence_name(sequence: SequenceSpec) -> str:
    return "、".join(sequence.label_of(t) for t in sequence.templates) or "顺序探测"


def _geometry_detail(spec: ChecksSpec) -> str:
    parts: list[str] = []
    for entry in spec.entries:
        if entry.roi is not None:
            parts.append(f"{entry.name} 范围 {entry.roi.to_tuple()}")
    for index, sequence in enumerate(spec.sequences, start=1):
        label = "按钮" if index == 1 else f"序列{index}"
        parts.append(f"{label} 范围 {sequence.roi.to_tuple()}")
    return " / ".join(parts)
