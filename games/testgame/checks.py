"""沙盒测试游戏的自检 —— **这就是这个游戏存在的意义**。

它不连真实窗口，也不点鼠标，只做一件事：把整条视觉链路在合成屏幕上跑一遍，
并且用**同一个事实来源**（:mod:`scene`）去验证结果。

## 八项检查

| # | 检查 | 挡掉什么 |
|---|---|---|
| 1 | 模板文件齐全 | 忘了放图 / 名字拼错 |
| 2 | 页面树 + 流程图校验通过 | id 对不上、走不到的节点、死循环边 |
| 3 | **每一页的特征都能在该页画面上按 ROI 找到** | 匹配算法、ROI 累加、坐标换算出错 |
| 4 | **别的页面的特征在它上面找不到** | 识别没有区分度（"哪个页面都像"） |
| 5 | 叠加层能叠在任意页面之上被找到 | 弹窗语义（与主页面**同时**成立） |
| 6 | 空白画面什么都识别不出来 | 误报 —— 最危险的失败模式 |
| 7 | 没有"没节点认领"的页面 | 漏写流程 |
| 8 | **每个页面的特征都落在自己的 ROI 内** | 子页面特征跑到父页面框外 → 那一页永远定位不到 |

第 3 和第 4 条是一对：只查"能找对"不够，还得查"不会认错"。
第 8 条是写这个测试游戏时发现的真问题 —— 详见 :mod:`.pages` 的说明。

## 为什么这些检查不算"测试代码放错地方"

它们检查的是**这份定义本身对不对**（图齐不齐、ROI 框得对不对、
页面之间有没有区分度），而不是框架内部实现。框架自己的单元测试在
``tests/`` 里；这里是"用这个框架写出来的一个脚本，能不能成立"。
"""

from __future__ import annotations

from gamebot.bootstrap import check_templates
from gamebot.config.schema import AppConfig
from gamebot.state import PageKind
from gamebot.vision.opencv_matcher import OpenCvMatcher

from . import build_scenario, scene
from .pages import build_tree


def run(config: AppConfig, *, matcher: OpenCvMatcher | None = None) -> list[str]:
    """跑全部自检。打印每一项的结论，返回失败说明（空 = 全过）。"""
    failures: list[str] = []
    matcher = matcher or _matcher(config)

    failures += _check_templates(config)
    failures += _check_definitions()
    failures += _check_roi_containment()
    failures += _check_detection(matcher)
    failures += _check_discrimination(matcher)
    failures += _check_overlay(matcher)
    failures += _check_blank(matcher)
    failures += _check_unclaimed()
    return failures


# --------------------------------------------------------------------------- #
# 各项检查
# --------------------------------------------------------------------------- #
def _matcher(config: AppConfig) -> OpenCvMatcher:
    roots = config.template_roots()
    return OpenCvMatcher(
        templates_dir=roots[-1],
        extra_dirs=roots[:-1],
        grayscale=config.vision.grayscale,
        use_pyramid=config.vision.use_pyramid,
        preload=False,
    )


def _check_templates(config: AppConfig) -> list[str]:
    missing = check_templates(config, build_scenario())
    problems = [f"缺 {len(missing)} 个: {', '.join(missing)}"] if missing else []
    return _report("模板文件齐全", problems, detail=f"{len(scene.ELEMENTS)} 个元素")


def _check_definitions() -> list[str]:
    try:
        build_scenario().validate()
    except Exception as exc:
        return _report("定义校验", [f"{type(exc).__name__}: {exc}"])
    return _report("定义校验", [], detail="页面树 + 流程图")


def _check_roi_containment() -> list[str]:
    """每个页面的特征元素必须落在它自己的有效 ROI 内。

    否则按 ROI 搜索时永远看不到那些元素 —— 页面就永远认不出来。
    这是"ROI 到底是干什么用的"的直接推论：它是**整棵子树**的搜索范围，
    不只是这一页自己的。
    """
    tree = build_tree()
    problems: list[str] = []
    for page_id, names in scene.PAGE_ELEMENTS.items():
        roi = tree.effective_roi(page_id)
        if roi is None:
            continue
        for name in names:
            rect = scene.element(name).rect
            if not roi.contains_region(rect):
                problems.append(
                    f"{page_id} 的元素 {name} {rect.to_tuple()} 超出 roi {roi.to_tuple()}"
                )
    return _report("ROI 包含特征", problems, detail=f"{len(scene.PAGE_ELEMENTS)} 个页面")


def _check_detection(matcher: OpenCvMatcher) -> list[str]:
    """每一页的元素都能在该页画面上、按其 ROI 找到，且位置精确。"""
    tree = build_tree()
    problems: list[str] = []
    checked = 0
    for page_id, names in scene.PAGE_ELEMENTS.items():
        image = scene.render(page_id)
        roi = tree.effective_roi(page_id)
        for name in names:
            expected = scene.element(name).rect
            found = matcher.match(image, name, region=roi, confidence=0.9)
            checked += 1
            if found is None:
                where = "整帧" if roi is None else f"roi {roi.to_tuple()}"
                problems.append(f"{page_id}: 在 {where} 里找不到 {name}")
                continue
            hit = found.region
            if (hit.x, hit.y, hit.w, hit.h) != expected.to_tuple():
                problems.append(
                    f"{page_id}: {name} 命中 {hit.to_tuple()}，应该是 {expected.to_tuple()}"
                )
    return _report("按 ROI 能找对", problems, detail=f"{checked} 次匹配")


def _check_discrimination(matcher: OpenCvMatcher) -> list[str]:
    """一个页面的特征，不该在"跟它无关"的页面上被找到。

    "无关"的精确定义：那个页面既不是当前页面，也不是它的祖先
    （祖先的元素本来就该出现在它上面 —— 真实 UI 就是这样）。
    """
    problems: list[str] = []
    checked = 0
    for page_id in scene.PAGE_ELEMENTS:
        visible = set(scene.elements_on(page_id))
        image = scene.render(page_id)
        for other, names in scene.PAGE_ELEMENTS.items():
            for name in names:
                if name in visible:
                    continue
                checked += 1
                found = matcher.match(image, name, confidence=0.9)
                if found is not None:
                    problems.append(
                        f"{page_id} 上不该出现 {other} 的 {name}，"
                        f"却在 {found.region.to_tuple()} 命中 (score={found.score:.3f})"
                    )
    return _report("不会认错页面", problems, detail=f"{checked} 次反向匹配")


def _check_overlay(matcher: OpenCvMatcher) -> list[str]:
    """叠加层要能叠在任意主页面之上被找到 —— 这是"同时成立"的语义。"""
    problems: list[str] = []
    hosts = [p for p in scene.PAGE_ELEMENTS if p != "popup_confirm"]
    for host in hosts:
        image = scene.render(host, overlay="popup_confirm")
        for name in scene.PAGE_ELEMENTS["popup_confirm"]:
            expected = scene.element(name).rect
            found = matcher.match(image, name, confidence=0.9)
            if found is None:
                problems.append(f"{host} + popup_confirm: 找不到 {name}")
            elif (found.region.x, found.region.y) != (expected.x, expected.y):
                problems.append(f"{host} + popup_confirm: {name} 命中位置偏了")
        # 主页面自己的特征也不能被弹窗盖没了（两者的矩形不重叠）
        probe = scene.PAGE_ELEMENTS[host][0]
        if matcher.match(image, probe, confidence=0.9) is None:
            problems.append(f"{host} + popup_confirm: 主页面特征 {probe} 被盖住了")
    return _report("叠加层与主页面并存", problems, detail=f"{len(hosts)} 个宿主页面")


def _check_blank(matcher: OpenCvMatcher) -> list[str]:
    """空白画面上任何模板都不该命中 —— 误报是最危险的失败模式。"""
    image = scene.blank()
    problems: list[str] = []
    for name in scene.template_names():
        found = matcher.match(image, name, confidence=0.9)
        if found is not None:
            problems.append(f"空白画面上误报 {name} @ {found.region.to_tuple()}")
    return _report("空白画面不误报", problems, detail=f"{len(scene.ELEMENTS)} 个模板")


def _check_unclaimed() -> list[str]:
    scenario = build_scenario()
    unclaimed = scenario.unclaimed_pages()
    overlays = [p.id for p in scenario.tree.walk() if p.kind is PageKind.OVERLAY]
    detail = f"叠加层 {len(overlays)} 个、终态页面不需要节点"
    problems = [f"未认领: {unclaimed}"] if unclaimed else []
    return _report("没有漏写流程的页面", problems, detail=detail)


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def _report(name: str, problems: list[str], *, detail: str = "") -> list[str]:
    mark = "✓" if not problems else "✗"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {mark} {name}{suffix}")
    for problem in problems:
        print(f"      - {problem}")
    return [f"[{name}] {p}" for p in problems]
