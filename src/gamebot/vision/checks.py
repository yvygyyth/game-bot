"""通用的识别检查 —— **逻辑在这里，数值在业务层**。

## 为什么要有这个模块

业务层每个脚本都要回答同一批问题：

* 我引用的模板都在吗？（→ 归通用的 `games check`）
* 我的 ROI **留够余量**了吗（悬停/位移时模板会不会滑出去）？
* 我裁的模板在**真机截图**上拿满分吗？页面标识稳吗？按钮分得开吗？
* 顺序探测在每种状态下会点哪个按钮，是我期望的那个吗？
* 现在屏幕上认得出吗？认出来的**位置**对不对？

**问题一样，答案不一样。** 所以这里放逻辑，业务层只声明数值 ——
见 :class:`ChecksSpec`。这样做的收益不只是少写代码：

* "要声明什么"只有一处能查；
* **语义由框架保证一致**：不会出现 A 脚本把 `tolerance` 当半径、
  B 脚本当边长（检查代码复制粘贴之后，这种歧义一定会发生）；
* 修一次检查逻辑，所有脚本受益。

## ROI 余量为什么值得单独算

名将杀首页的卡片**静止时在中间、鼠标一悬停就往右上弹 `(+27, -41)` 像素**。
ROI 留小了，你一划过入口模板就滑出 ROI、匹配不到 —— 而这是**静态看代码
完全看不出来**的错，只能跑到那一屏才发现。

所以 :class:`EntrySpec.hover` 就是声明这件事的位移量，检查会算出
"从期望中心到 ROI 边界还剩多少"，不够就报出来。

## 阈值和 ROI 的关系

一个模板比它的 ROI 还大 = **永远匹配不到**。这是另一个纯算术就能查的错，
所以每个 :class:`EntrySpec` / :class:`SequenceSpec` 都会算一遍。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..types import Point, Region
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from ..config.schema import AppConfig

log = get_logger("vision.checks")

__all__ = [
    "ChecksSpec",
    "EntrySpec",
    "SequenceSpec",
    "run_checks",
    "run_probe",
]


@dataclass(frozen=True, slots=True)
class EntrySpec:
    """一个"要认出来的东西"：模板 + 它该命中的位置 + 它的搜索范围。

    :param hover: 悬停/位移动画会让这个模板移动多少像素（``(+27, -41)`` 这种）。
        给了就会**自动检查 ROI 余量够不够** —— 见模块 docstring。
    :param origin: 这个模板是从哪张资产图上裁下来的；给了就会检查
        "在它自己的来源图上必须拿满分"（裁歪了几像素，这里才看得出来）。
    """

    template: str
    point: Point
    confidence: float
    tolerance: int = 15
    roi: Region | None = None
    hover: Point | None = None
    origin: str = ""
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

    :param expected: ``{资产图名: 该选中的模板}``。缺哪张就跳过哪张。
    """

    templates: tuple[str, ...]
    roi: Region
    confidence: float
    expected: Mapping[str, str] = field(default_factory=dict)
    names: tuple[str, ...] = ()

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
    """一组"同时该被认出来"的东西 —— 通常就是一个状态的标识。

    :param required: 探针里"一个都没认出来"算不算失败。给 ``True`` 的是
        "我至少得认出这是哪一页"；给 ``False`` 的是"顺便报告一下"
        （比如竞技场那三个按钮的当前状态，用来诊断走到哪一步了）。
    """

    name: str
    entries: tuple[EntrySpec, ...]
    required: bool = True

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class ChecksSpec:
    """一个脚本要检查的全部内容。**业务层只写这个。**

    :param states: 资产图（真机截图）文件名。**这是整个检查里最有价值的一项**——
        静态代码永远查不出来"模板裁歪了"和"两个按钮分不开"，只有真实截图能。
        文件不存在就自动跳过（资产图是本地素材，不入库）。
    :param fixture_path: 参考图（``prepare()`` 抓的那张）的**完整路径**，
        用来验"位置偏没偏"。``None`` 或文件不存在就跳过。

        为什么是路径而不是文件名：**框架不去猜业务层的目录约定**。
        那是业务层自己的事（名将杀放在 ``games/mingjiangsha/fixtures/``，
        别的游戏可以放别处），框架只认一个路径 —— 猜约定就是第二份事实来源。
    """

    title: str
    entries: tuple[EntrySpec, ...] = ()
    groups: tuple[EntryGroup, ...] = ()
    sequences: tuple[SequenceSpec, ...] = ()
    states: tuple[str, ...] = ()
    assets_dir: Path | None = None
    fixture_path: Path | None = None
    fixture_group: str = ""
    """参考图对应 :attr:groups 里的哪一组。参考图是**一张特定界面**的截图，
    所以只要求那一组必须认出来 —— 要求它在同一张图上同时认出别的页面是不讲道理的。
    位置偏差照样全查（那正是参考图的用途）。"""
    page_roi: Region | None = None


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def run_checks(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """跑静态自检。打印每项结论，返回失败说明（空 = 全过）。

    **只管业务层独有的那几项。** "模板文件在不在""定义自不自洽"归通用的
    ``games check`` —— 那边是框架的一份实现，所有脚本共用；在脚本里再写一遍
    等于同一件事两个出处，改了框架的这边不会跟着变。
    """
    failures: list[str] = []
    failures += _check_geometry(spec, config)
    failures += _check_assets(spec, config)
    failures += _check_fixture(spec, config)
    return failures


def _check_geometry(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """纯算术检查：ROI 装得下模板吗？留够位移余量吗？期望点在框里吗？"""
    problems: list[str] = []

    for entry in spec.entries:
        size = _template_size(config, entry.template)
        if size is None:
            problems.append(f"{entry.template}: 找不到或读不出来")
            continue
        width, height = size
        if entry.roi is not None:
            problems += _roi_fit(entry, width, height)
        if entry.roi is not None and not entry.roi.contains(entry.point):
            problems.append(
                f"{entry.name}: 期望中心 {entry.point.as_tuple()} 不在它的 ROI "
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
                    f"{template} {size[0]}x{size[1]} 比搜索范围 {sequence.roi.to_tuple()} 还大，"
                    "永远匹配不到"
                )

    detail = _geometry_detail(spec)
    return _report("几何一致", problems, detail=detail)


def _roi_fit(entry: EntrySpec, width: int, height: int) -> list[str]:
    """模板装得进 ROI 吗？留得下位移吗？"""
    problems: list[str] = []
    roi = entry.roi
    assert roi is not None  # 调用方已经判过

    if width > roi.w or height > roi.h:
        problems.append(
            f"{entry.name} {width}x{height} 比它的 ROI {roi.to_tuple()} 还大，永远匹配不到"
        )
        return problems

    left = (entry.point.x - width / 2) - roi.x
    top = (entry.point.y - height / 2) - roi.y
    right = roi.right - (entry.point.x + width / 2)
    bottom = roi.bottom - (entry.point.y + height / 2)

    if entry.hover is None:
        # 没声明位移：只要求装得下（上面已判），但边距为负就是框裁得不对
        if min(left, top, right, bottom) < 0:
            problems.append(
                f"{entry.name}: 模板按期望中心摆下去会伸出 ROI "
                f"（左{left:.0f} 上{top:.0f} 右{right:.0f} 下{bottom:.0f}）"
            )
        return problems

    # 声明了位移：四个方向都要留得下
    dx, dy = entry.hover.x, entry.hover.y
    need_left = max(0, -dx)
    need_right = max(0, dx)
    need_top = max(0, -dy)
    need_bottom = max(0, dy)
    if left < need_left:
        problems.append(
            f"{entry.name}: ROI 左边距只有 {left:.0f}px，装不下位移 ({dx:+d})"
        )
    if right < need_right:
        problems.append(
            f"{entry.name}: ROI 右边距只有 {right:.0f}px，装不下位移 ({dx:+d})"
        )
    if top < need_top:
        problems.append(
            f"{entry.name}: ROI 上边距只有 {top:.0f}px，装不下位移 ({dy:+d})"
        )
    if bottom < need_bottom:
        problems.append(
            f"{entry.name}: ROI 下边距只有 {bottom:.0f}px，装不下位移 ({dy:+d})"
        )
    return problems


def _check_assets(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """用真机截图做回归。资产目录不在就跳过（它们是本地素材，不入库）。"""
    images = _load_assets(spec)
    if images is None:
        return _report(
            "资产图回归",
            [],
            detail=f"跳过（没有 {spec.assets_dir}）—— 那是本地参考素材，不入库",
        )
    if not images:
        return _report("资产图回归", [f"{spec.assets_dir} 里没有可读的 PNG"])

    matcher = _matcher(config)
    problems: list[str] = []
    checked = 0

    # ① 每个模板在自己的来源图上必须满分（裁歪了分数就掉）
    origin_of = {e.template: e.origin for e in spec.entries if e.origin}
    for entry in spec.entries:
        if not entry.origin:
            continue
        image = images.get(entry.origin)
        if image is None:
            problems.append(f"{entry.template}: 找不到来源图 {entry.origin}")
            continue
        hit = matcher.match(image, entry.template, confidence=0.0)
        checked += 1
        if hit is None or hit.score < 0.95:
            got = "未命中" if hit is None else f"{hit.score:.3f}"
            problems.append(
                f"{entry.template} 在来源图 {entry.origin} 上只有 {got}，模板裁歪了？"
            )

    # ② 页面标识在每种状态下都要稳（不稳的那一步会认不出自己在哪）
    for entry in spec.entries:
        for name in spec.states:
            image = images.get(name)
            if image is None or entry.template == origin_of.get(entry.template):
                continue
            hit = matcher.match(image, entry.template, confidence=0.0)
            checked += 1
            if hit is not None and 0 < hit.score < entry.confidence:
                # 只报告，不判失败：一个模板在别的状态上分数低是**正常的**
                # （比如首页的卡片在竞技场上本来就该认不出来）
                log.debug(
                    "%s 在 %s 上 %s（阈值 %.2f）",
                    entry.template,
                    name,
                    f"{hit.score:.3f}",
                    entry.confidence,
                )

    # ③ 顺序探测在每种状态下都必须选中正确的按钮
    for sequence in spec.sequences:
        problems += _check_sequence(sequence, images, matcher)
        checked += len(sequence.expected) * len(sequence.templates)

    detail = (
        f"{len(images)} 张资产图，{checked} 次匹配；"
        f"状态 {' '.join(spec.states) if spec.states else '—'}"
    )
    return _report("资产图回归", problems, detail=detail)


def _check_sequence(
    sequence: SequenceSpec, images: dict[str, Any], matcher: Any
) -> list[str]:
    """顺序探测：按顺序找，第一个过阈值的必须正好是该点的那个。"""
    if not sequence.expected:
        return []

    header = "".join(f"{sequence.label_of(t):>14s}" for t in sequence.templates)
    print(f"      {'状态':>14s}{header}   会点哪个")
    problems: list[str] = []

    for name, expected in sequence.expected.items():
        image = images.get(name)
        if image is None:
            problems.append(f"缺少资产图 {name}")
            continue
        scores: list[float] = []
        picked = ""
        for template in sequence.templates:
            hit = matcher.match(image, template, confidence=0.0)
            score = hit.score if hit else 0.0
            scores.append(score)
            if not picked and score >= sequence.confidence:
                picked = template
        print(
            f"      {name:>14s}"
            + "".join(f"{s:>12.3f}" for s in scores)
            + f"   {picked or '（都不点）'}"
        )
        if picked != expected:
            problems.append(
                f"{name}: 顺序探测会点 {picked or '（都不点）'}，应该是 {expected}"
                f" —— {_sequence_name(sequence)} 的阈值要调，或者模板拿错了"
            )
    return problems


def _check_fixture(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """在参考画面上真跑一遍识别，并断言**命中的位置**。

    这是唯一能查出"认得出但认错地方"的检查 —— 而认错地方比认不出来更危险：
    下一步就照着这个点戳下去了。
    """
    if spec.fixture_path is None or not Path(spec.fixture_path).is_file():
        detail = (
            f"跳过（没有参考图 {spec.fixture_path}）—— 跑 games setup 生成"
            if spec.fixture_path is not None
            else "跳过（这个脚本没声明参考图）"
        )
        return _report("参考画面上的识别", [], detail=detail)

    from .probe import check_entries_on_frame, load_frame_image

    loaded = load_frame_image(spec, config)
    if loaded is None:
        return _report("参考画面上的识别", [], detail="跳过")
    if isinstance(loaded, str):
        return _report("参考画面上的识别", [loaded])

    problems = check_entries_on_frame(spec, loaded, require_all=False)
    mark = "✓" if not problems else "✗"
    print(f"  {mark} 参考画面上的识别")
    return [f"[参考画面] {p}" for p in problems]


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


def _threshold_check(label: str, value: float) -> list[str]:
    if not 0 < value <= 1:
        return [f"{label} 的阈值 {value} 不合法（必须在 0~1 之间）"]
    return []


def _sequence_name(sequence: SequenceSpec) -> str:
    return "、".join(sequence.label_of(t) for t in sequence.templates) or "顺序探测"


def _matcher(config: AppConfig) -> Any:
    from .opencv_matcher import OpenCvMatcher

    roots = config.template_roots()
    return OpenCvMatcher(
        templates_dir=roots[-1],
        extra_dirs=roots[:-1],
        grayscale=config.vision.grayscale,
        use_pyramid=config.vision.use_pyramid,
        preload=True,
    )


def _load_assets(spec: ChecksSpec) -> dict[str, Any] | None:
    """读资产图。目录不存在返回 None（= 跳过），存在但读不出来返回 ``{}``。"""
    import cv2

    if spec.assets_dir is None or not Path(spec.assets_dir).is_dir():
        return None
    images: dict[str, Any] = {}
    for path in sorted(Path(spec.assets_dir).glob("*.png")):
        image = cv2.imread(str(path))
        if image is not None:
            images[path.name] = image
    return images


def _geometry_detail(spec: ChecksSpec) -> str:
    parts: list[str] = []
    for entry in spec.entries:
        if entry.roi is not None:
            parts.append(f"{entry.name} ROI {entry.roi.to_tuple()}")
    for index, sequence in enumerate(spec.sequences, start=1):
        label = "按钮" if index == 1 else f"序列{index}"
        parts.append(f"{label} ROI {sequence.roi.to_tuple()}")
    return " / ".join(parts)


# --------------------------------------------------------------------------- #
# 真机探针
# --------------------------------------------------------------------------- #
def run_probe(spec: ChecksSpec, config: AppConfig) -> list[str]:
    """真机探针：抓一张当前画面，报出认得出哪些东西。返回失败说明。

    和自检的区别：那个查"这份定义成不成立"（不需要游戏在跑），
    这个查"**现在**屏幕上认不认得出来"。

    **故意不短路**：所有 ``entries`` 都查一遍，而不是认到一个就返回。
    因为"两个都认出来了"本身就是有用的信息（窗口被叠了、分辨率不对）——
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
