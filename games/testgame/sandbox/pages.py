"""沙盒测试游戏的页面树（状态对象）。

页面结构和 ROI 全部从 :mod:`scene` 读 —— **一处定义、多处一致**，
所以这个页面树和合成屏幕不可能对不上。

```
root                        全屏（无 roi）
├── root/menu               roi=(240,120,800,480)      菜单面板
│   └── root/menu/list      roi=(40,30,240,36)         列表表头，在面板内部
├── root/battle             roi=(740,540,520,160)      技能栏
│   └── root/battle/skill   roi=(160,50,72,72)         技能图标，在技能栏内部
└── root/result             roi=(380,200,520,320)      结算面板
popup_confirm               [overlay]  全局弹窗
done                        [terminal] 跑完的标记
```

## 两层 ROI 偏移是故意的

``root/menu/list`` 的 roi 是 ``(40,30,...)``，相对的是 ``root/menu``；
而 ``root/battle/skill`` 的 roi 是 ``(160,50,...)``，相对的是 ``root/battle``。
两层叠起来才是屏幕绝对坐标，正好验证 :meth:`PageTree.effective_roi` 的累加。

## 一个容易踩的坑（这个测试游戏专门演示它）

**子页面的特征元素必须落在父页面的 roi 里**，否则那一页永远定位不到 ——
父页面的 roi 是整棵子树的搜索范围。比如把结算面板做成 ``root/battle`` 的
子页面、而 ``battle`` 的 roi 只框住技能栏，那结算页就永远认不出来。
所以这里 ``root/result`` 是 ``root/battle`` 的**兄弟**，不是子页面。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery
from gamebot.state import Page, PageKind, PageTree

from .. import scene


def build_tree() -> PageTree:
    """按 :data:`scene.PAGE_PARENT` 的顺序建树（父必须先建好）。"""
    tree = PageTree()
    for page_id in _ordered(scene.PAGE_PARENT):
        tree.add(_page(page_id), scene.PAGE_PARENT[page_id])
    return tree


def _ordered(parent_map: dict[str, str | None]) -> list[str]:
    """把页面排成"父一定在子前面"的顺序（保持定义顺序稳定）。"""
    ordered: list[str] = []
    pending = list(parent_map)
    while pending:
        for page_id in list(pending):
            parent = parent_map[page_id]
            if parent is None or parent in ordered:
                ordered.append(page_id)
                pending.remove(page_id)
    return ordered


#: 页面显示名 + 是不是叠加层 / 终态。识别条件从 scene 推。
_META: dict[str, tuple[str, PageKind, bool]] = {
    "root": ("沙盒首页", PageKind.PAGE, False),
    "root/menu": ("菜单面板", PageKind.PAGE, False),
    "root/menu/list": ("列表页", PageKind.PAGE, False),
    "root/battle": ("技能栏", PageKind.PAGE, False),
    "root/battle/skill": ("技能详情", PageKind.PAGE, False),
    "root/result": ("结算面板", PageKind.PAGE, False),
    "popup_confirm": ("确认弹窗", PageKind.OVERLAY, False),
    "done": ("跑完了", PageKind.PAGE, True),
}


def _page(page_id: str) -> Page:
    title, kind, terminal = _META[page_id]
    queries = tuple(
        ImageQuery(name, confidence=0.9) for name in scene.PAGE_ELEMENTS[page_id]
    )
    return Page(
        page_id,
        name=title,
        kind=kind,
        roi=scene.PAGE_ROI[page_id],
        queries=queries,
        terminal=terminal,
        priority=100 if kind is PageKind.OVERLAY else 0,
        # 结算/完成这类面板有弹出动画，要求连续两帧命中才算
        min_stable_frames=2 if page_id in ("root/result", "done") else 1,
        description=f"沙盒页面 {page_id}",
    )


def title_of(page_id: str) -> str:
    """页面显示名。"""
    return _META[page_id][0]
