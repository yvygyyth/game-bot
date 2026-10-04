"""沙盒测试游戏的「屏幕」—— 完全用代码合成，不需要真实游戏窗口。

## 为什么要有这个

框架的定位是"看图操作"，所以最难测的恰恰是视觉：模板匹配找没找对、
ROI 继承算没算对、坐标有没有偏。传统做法是录几张真截图提交进仓库，
但那样有几个问题：体积大、改一次 UI 就全部失效、而且"图里到底该有什么"说不清。

这里换个做法：**用确定性噪声画出假界面**。

* 每个 UI 元素 = 一块固定矩形 + 一段由**名字**决定的伪随机噪声。
  种子取 ``zlib.crc32(名字)``，所以每次生成、每台机器上都一模一样。
  （不能用内置 ``hash()`` —— 它带进程随机盐，模板和屏幕会画得不一样。）
* 用噪声而不是纯色块：纯色会在整张图上**到处**匹配（score 都是 1.0），
  噪声只有一个尖锐峰值 —— 匹配器要是算错位置，测试立刻能看出来。
* 模板 = 从合成屏幕上裁下来的那一块。于是"模板一定能在对应页面上找到"
  这条性质是**构造出来**的，不需要人工录图。

## 页面是怎么"画"出来的

子页面画在父页面之上（真实 UI 就是这样：进了子菜单，父页面的顶栏底栏还在），
所以 :func:`render` 会把**根到自己的全部元素**都画上去。这正好让
"子页面继承父页面的 ROI"这个设计能在合成图上验证。

## 这个模块刻意是"假游戏的全部事实"

``PAGE_PARENT`` / ``PAGE_ROI`` / ``PAGE_ELEMENTS`` 同时被三处使用：
:mod:`pages` 拿它建页面树、:func:`render` 拿它画屏幕、:mod:`selftest`
拿它算"应该匹配到哪"。**一处定义、三处一致**，所以测试不可能是自说自话。
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from gamebot.types import Region

# --------------------------------------------------------------------------- #
# 屏幕
# --------------------------------------------------------------------------- #
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720

BACKGROUND = (26, 26, 32)
"""深灰底。**刻意是纯色**：合成背景要跟元素的噪声反差极大，
这样"元素没找到"和"找到了别的东西"能一眼区分开。"""


@dataclass(frozen=True, slots=True)
class Element:
    """一个 UI 元素 = 一块矩形 + 一段由名字决定的噪声。"""

    name: str
    """模板名（相对模板根，可带子目录）—— 同时也是噪声种子的来源。"""

    x: int
    y: int
    w: int
    h: int

    @property
    def rect(self) -> Region:
        return Region(self.x, self.y, self.w, self.h)


#: 屏幕上的全部元素。坐标是**屏幕绝对坐标**。
#:
#: 布局上有一条硬约束（selftest 会查）：**页面特征不能被全局弹窗盖住**。
#: 所以菜单和结算页的特征用各自面板顶部的**标题条**，而不是整块面板 ——
#: 弹窗一冒出来就把面板盖掉一半，那"现在在哪个页面"就永远认不出来了。
#: 这条规则在真实游戏里同样成立：**特征要选弹窗盖不到的地方**（顶栏、底栏、角落）。
ELEMENTS: tuple[Element, ...] = (
    Element("home/logo.png", 40, 28, 160, 48),
    Element("home/bottom_bar.png", 0, 664, 1280, 56),
    Element("menu/header.png", 240, 120, 800, 40),
    Element("menu/list_header.png", 280, 150, 240, 36),
    Element("battle/skill_bar.png", 740, 540, 520, 160),
    Element("battle/skill.png", 900, 590, 72, 72),
    Element("result/header.png", 380, 200, 520, 40),
    Element("result/confirm.png", 560, 440, 160, 48),
    Element("popup/confirm.png", 480, 250, 320, 160),
    Element("common/done.png", 520, 60, 240, 80),
)

_BY_NAME: dict[str, Element] = {e.name: e for e in ELEMENTS}

# --------------------------------------------------------------------------- #
# 页面层级（这是"假游戏"的结构事实，pages.py 和 selftest.py 都从这里读）
# --------------------------------------------------------------------------- #
PAGE_PARENT: dict[str, str | None] = {
    "root": None,
    "root/menu": "root",
    "root/menu/list": "root/menu",
    "root/battle": "root",
    "root/battle/skill": "root/battle",
    "root/result": "root",
    # 叠加层和终态没有父页面（顶层）
    "popup_confirm": None,
    "done": None,
}

#: 每一页**自己新增**的元素。注意子页面的元素必须落在父页面的 ROI 里，
#: 否则那一页永远定位不到 —— :func:`selftest` 里有一条专门查这个。
PAGE_ELEMENTS: dict[str, tuple[str, ...]] = {
    "root": ("home/logo.png", "home/bottom_bar.png"),
    "root/menu": ("menu/header.png",),
    "root/menu/list": ("menu/list_header.png",),
    "root/battle": ("battle/skill_bar.png",),
    "root/battle/skill": ("battle/skill.png",),
    "root/result": ("result/header.png", "result/confirm.png"),
    "popup_confirm": ("popup/confirm.png",),
    "done": ("common/done.png",),
}

#: 每一页自己的 ROI，**相对父页面的 ROI 原点**（和 ``Page.roi`` 的语义一致）
PAGE_ROI: dict[str, Region | None] = {
    "root": None,
    "root/menu": Region(240, 120, 800, 480),
    # 相对 menu：(280,150) = (240+40, 120+30)
    "root/menu/list": Region(40, 30, 240, 36),
    "root/battle": Region(740, 540, 520, 160),
    # 相对 battle：(900,590) = (740+160, 540+50)
    "root/battle/skill": Region(160, 50, 72, 72),
    "root/result": Region(380, 200, 520, 320),
    "popup_confirm": None,
    "done": None,
}


def element(name: str) -> Element:
    """按模板名取元素。名字写错直接报错 —— 测试里不该有"静默找不到"。"""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"没有这个元素: {name!r}；已定义的有 {sorted(_BY_NAME)}") from None


def ancestors_of(page_id: str) -> tuple[str, ...]:
    """``(最顶层, ..., 父页面)``，不含自己。"""
    chain: list[str] = []
    current = PAGE_PARENT.get(page_id)
    while current is not None:
        chain.append(current)
        current = PAGE_PARENT.get(current)
    return tuple(reversed(chain))


def elements_on(page_id: str) -> tuple[str, ...]:
    """这一页上**实际能看到**的全部元素：祖先的 + 自己的（父在前）。"""
    names: list[str] = []
    for page in (*ancestors_of(page_id), page_id):
        names.extend(PAGE_ELEMENTS.get(page, ()))
    return tuple(names)


# --------------------------------------------------------------------------- #
# 合成
# --------------------------------------------------------------------------- #
def pattern(name: str, width: int, height: int) -> np.ndarray:
    """由**名字**决定的确定性噪声块（BGR，uint8）。

    同一个名字永远画出同一张图，所以"模板 == 屏幕上的那一块"成立。
    """
    seed = zlib.crc32(name.encode("utf-8"))
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def blank() -> np.ndarray:
    """一张什么都没有的屏幕（用来模拟"认不出来的画面"）。"""
    canvas = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH, 3), dtype=np.uint8)
    canvas[:, :] = BACKGROUND
    return canvas


def render(page_id: str, *, overlay: str | None = None) -> np.ndarray:
    """画出这一页应该长什么样。

    :param page_id: 页面 id（必须在 :data:`PAGE_PARENT` 里）。
    :param overlay: 额外叠一个全局弹窗（模拟"页面 + 弹窗同时成立"）。
    """
    if page_id not in PAGE_PARENT:
        raise KeyError(f"没有这个页面: {page_id!r}")
    canvas = blank()
    for name in elements_on(page_id):
        _draw(canvas, name)
    if overlay is not None:
        for name in PAGE_ELEMENTS.get(overlay, ()):
            _draw(canvas, name)
    return canvas


def _draw(canvas: np.ndarray, name: str) -> None:
    item = element(name)
    canvas[item.y : item.y + item.h, item.x : item.x + item.w] = pattern(name, item.w, item.h)


def generate_templates(root: Path, *, force: bool = False) -> int:
    """把所有元素裁成模板 PNG 写到 ``root`` 下。返回新写入的数量。

    幂等：文件已存在就跳过（``force=True`` 才覆盖）。这样反复跑
    ``python -m games setup testgame`` 不会每次都重写一堆文件。
    """
    import cv2

    written = 0
    for item in ELEMENTS:
        path = root / item.name
        if path.is_file() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        image = pattern(item.name, item.w, item.h)
        if not cv2.imwrite(str(path), image):
            raise RuntimeError(f"写模板失败: {path}")
        written += 1
    return written


def template_names() -> tuple[str, ...]:
    """全部模板名（就是全部元素名）。"""
    return tuple(e.name for e in ELEMENTS)
