"""按钮快捷方法 —— **认边框，不认文字**。

## 为什么

这游戏满屏都是"同一副金框、只换中间几个字"的按钮：创建队伍 / 添加伙伴 /
开始匹配 / 确定 / 下一步…… 按文字裁模板的话，每加一句新文案就要多一张图，
而且**换个文字就匹配不上了**。但边框是**不变的那部分**。

所以比对时只比**边框环**：

* 从裁剪图的四周取一圈（``BUTTON_RING_WIDTH`` 像素宽），外沿内缩
  ``BUTTON_RING_INSET`` 像素 —— 内缩是为了跳过裁图带进来的背景
  （浅色弹窗和深色面板的背景差 140 个亮度级）；
* 中间的字**用遮罩排除**，比对时完全不看它 —— 换文字不影响；
* 比对用**减均值的遮罩相关**，不是 OpenCV 的 masked ``TM_CCORR_NORMED``：
  后者不减均值、被亮度主导，同一块环能到 0.98，整屏全是误命中。

实测（创建队伍 225×82 的模板，只比边框）：

| 目标 | 分数 |
|---|---|
| 同一张图上的「创建队伍」 | 0.998 |
| **同一位置换成「添加伙伴」**（同尺寸、换文字） | **0.997** |
| 没有这类按钮的画面 | 0.65~0.77 |

## 一个文件夹 = 一种按钮

```
games/mingjiangsha/templates/shadowConfirm/   ← 金色确认按钮：各种文字版本都放这儿
games/mingjiangsha/templates/shadowCancel/    ← 青色取消按钮
```

调用时只说"点哪种按钮"，不说"点哪句字"：

```python
from games.mingjiangsha.templates import BUTTON_SHADOW_CONFIRM
from games.mingjiangsha.utils import click_button

click_button(ctx, BUTTON_SHADOW_CONFIRM)   # 创建队伍 / 添加伙伴 / 确定…都算
```

## 尺寸 / 底色的限制（重要）

"只比边框"解决的是**换文字**，不解决**换尺寸**：

* **同尺寸、不同文字** -> 一张模板就够（环的位置完全一致）；
* **不同尺寸**（确定 257×87 vs 添加伙伴 218×72）-> 环的四条边位置跟着尺寸走，
  仍然是**两张模板**，各比各的。不用重裁文字版本，但尺寸版本要各存一张；
* **不同底色**（浅色弹窗 / 深色面板）-> 环外沿的像素不同，靠 ``BUTTON_RING_INSET``
  把背景让开；同一按钮换底色时按新底色再存一张。

## 约定

* 文件夹里的图要**完整包含按钮**，四周留 2~3 像素；
* 同一家族里，不同文字版本**同一时刻只会出现一个**。要是真出现两个，
  `pick="only"`（默认）会直接报错而不是猜 —— 猜错的代价是点错按钮；
* 一种按钮一个文件夹。**别把两种不同的按钮混进一个文件夹**，那会让 `pick` 失效；
* 同一个按钮的多张截图版本可以共存（按位置去重，只留分数最高的）。

阈值：实测正例 0.99+，反例 ≤0.83，默认取 **0.90**。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.bootstrap import project_root
from gamebot.exceptions import ConfigError
from gamebot.types import ActionResult, Point, Region
from games.mingjiangsha.templates import (
    BUTTON_PATTERN_CONFIRM,
    BUTTON_QJ_NEXT,
    BUTTON_SHADOW_CANCEL,
    BUTTON_SHADOW_CONFIRM,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "BUTTON_CONFIDENCE",
    "BUTTON_RING_INSET",
    "BUTTON_RING_WIDTH",
    "ButtonHit",
    "click_button",
    "click_pattern_confirm",
    "click_qj_next",
    "click_shadow_cancel",
    "click_shadow_confirm",
    "find_buttons",
    "folder_templates",
    "ring_mask",
]

#: 默认阈值。实测只比边框时：真按钮 0.99+，没有它的画面 ≤0.83 —— 0.90 有余量。
BUTTON_CONFIDENCE = 0.90

#: 边框环：从裁剪图外沿**内缩**多少像素再开始取（跳过裁图带进来的背景）。
BUTTON_RING_INSET = 4

#: 边框环的宽度（像素）。只比这一圈，中间的文字被遮掉。
BUTTON_RING_WIDTH = 12

#: 同一个模板形状的遮罩只造一次
_MASK_CACHE: dict[tuple[str, int, int], Any] = {}

#: 两个命中相距多近算"同一个按钮"（单张模板内的 NMS 间距）。按钮宽 200+，30 足够。
BUTTON_MIN_DISTANCE = 30

#: **跨模板**去重半径：同一个按钮被家族里多张图同时命中时，只留分数最高的。
#: 允许"同一个按钮的不同截图版本"共存在一个文件夹（不同分辨率重裁的、悬浮与常态
#: 都像的）—— 这是加新截图时最容易发生的事。不去重就会变成"找到 2 个按钮"，
#: `pick="only"` 直接报错，看起来像"按钮重复了"。
BUTTON_SAME_SPOT = 60

#: ``pick`` 的合法值。
PICK_CHOICES = ("only", "best", "right", "left", "top", "bottom")


@dataclass(frozen=True, slots=True)
class ButtonHit:
    """一个按钮命中。``point`` 是按钮**中心**（源坐标），``template`` 是命中的那张图。"""

    point: Point
    score: float
    template: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "point": (self.point.x, self.point.y),
            "score": round(self.score, 3),
            "template": self.template,
        }


def _folder_of(ctx: RunContext, folder: str) -> Path:
    """把家族名解析成目录（相对**游戏级**模板根）。"""
    game = ctx.name.split("/", 1)[0]
    return project_root() / "games" / game / "templates" / folder


def ring_mask(shape: tuple[int, int], *, inset: int, width: int) -> Any:
    """按模板尺寸生成"边框环"遮罩：只保留四周 ``width`` 像素、从边缘内缩 ``inset``。

    为什么要有它：按钮换文字时**中间的字变了**，但边框没变。整块模板比对会因为
    文字不同而失配；只比这个环（遮罩中心）就能忽略文字。

    :param shape: 模板的 ``(高, 宽)``。
    :param inset: 从裁剪图**外沿**往里缩多少像素再取环 —— 用来跳过裁剪时带进来的
        背景（背景随界面变，浅色弹窗和深色面板差 140 个亮度级）。
    :param width: 环的宽度。
    """
    import numpy as np  # 业务层用，不把它带到状态/流程层的导入期

    height, width_px = shape[:2]
    mask = np.zeros((height, width_px), np.uint8)
    top, bottom = inset, height - inset
    left, right = inset, width_px - inset
    if bottom - top <= 0 or right - left <= 0:
        raise ConfigError(
            f"按钮模板太小（{width_px}x{height}），放不下 inset={inset} 的边框环"
        )
    mask[top:bottom, left : left + width] = 1
    mask[top:bottom, right - width : right] = 1
    mask[top : top + width, left:right] = 1
    mask[bottom - width : bottom, left:right] = 1
    return mask


def _mask_for(ctx: RunContext, template: str) -> Any:
    """这个模板对应的边框环遮罩（按模板原始尺寸生成，缓存住）。"""
    height, width_px = ctx.session.matcher.load_template(template).shape[:2]
    key = (template, height, width_px)
    cached = _MASK_CACHE.get(key)
    if cached is None:
        cached = ring_mask(
            (height, width_px),
            inset=BUTTON_RING_INSET,
            width=BUTTON_RING_WIDTH,
        )
        _MASK_CACHE[key] = cached
    return cached


def folder_templates(ctx: RunContext, folder: str) -> list[str]:
    """这个按钮家族里的全部模板名（相对模板根，含文件夹前缀）。

    名字要带 ``<家族>/`` 前缀：运行时 Matcher 就是按相对名去功能级 / 游戏级两个根里找的。

    :raises ConfigError: 文件夹不存在或里面没有图 —— 写错家族名时当场报，
        而不是表现成"这个按钮没找到"。
    """
    path = _folder_of(ctx, folder)
    if not path.is_dir():
        games_dir = project_root() / "games" / ctx.name.split("/", 1)[0] / "templates"
        existing = (
            sorted(p.name for p in games_dir.iterdir() if p.is_dir())
            if games_dir.is_dir()
            else []
        )
        raise ConfigError(
            f"按钮家族 {folder!r} 不存在（找不到目录 {path}）。"
            f"现有家族: {', '.join(existing) or '（一个都没有）'}"
        )
    names = sorted(
        f"{folder}/{p.name}" for p in path.glob("*") if p.suffix.lower() in {".png", ".jpg", ".bmp"}
    )
    if not names:
        raise ConfigError(f"按钮家族 {folder!r} 里一张图都没有: {path}")
    return names


def find_buttons(
    ctx: RunContext,
    folder: str,
    region: Region | None = None,
    *,
    confidence: float = BUTTON_CONFIDENCE,
    templates: list[str] | None = None,
) -> list[ButtonHit]:
    """在画面上找**某一种按钮**的所有命中，按 x 从左到右排序。

    :param folder: 按钮家族（``games/<游戏>/templates/<家族>/`` 的目录名）。
    :param region: 搜索范围（源坐标）。**给了更稳** —— 不带 region 是整屏找，
        虽然整按钮模板误命中很少，但画面里同时有两种按钮时会多出候选。
    :param templates: 覆盖"家族里有哪些图"（测试用；平时不用传）。
    :return: 命中列表，可能为空。
    """
    names = templates if templates is not None else folder_templates(ctx, folder)
    frame = ctx.frame()
    hits: list[ButtonHit] = []
    for name in names:
        found = frame.find_all_images(
            name,
            region=region,
            confidence=confidence,
            min_distance=BUTTON_MIN_DISTANCE,
            mask=_mask_for(ctx, name),
        )
        if not found.ok or not found.value:
            continue
        scores = list(found.meta.get("scores") or [])
        for index, point in enumerate(found.value):
            hits.append(
                ButtonHit(
                    point=point,
                    score=float(scores[index]) if index < len(scores) else 0.0,
                    template=name,
                )
            )
    return _dedupe(hits)


def _dedupe(hits: list[ButtonHit]) -> list[ButtonHit]:
    """同一个按钮被多张模板命中时，只留分数最高的那个。

    为什么需要：文件夹里**允许**放同一个按钮的不同截图版本（不同分辨率重裁的）。
    那两张图会同时命中同一个按钮 —— 不去重就是"找到 2 个按钮"，
    而 `pick="only"` 会报错，看起来像"按钮重复了"，其实只是模板重复了。
    """
    kept: list[ButtonHit] = []
    for hit in sorted(hits, key=lambda item: item.score, reverse=True):
        too_close = any(
            abs(hit.point.x - other.point.x) <= BUTTON_SAME_SPOT
            and abs(hit.point.y - other.point.y) <= BUTTON_SAME_SPOT
            for other in kept
        )
        if not too_close:
            kept.append(hit)
    return sorted(kept, key=lambda item: (item.point.x, item.point.y))


def click_button(
    ctx: RunContext,
    folder: str,
    region: Region | None = None,
    *,
    pick: str = "only",
    confidence: float = BUTTON_CONFIDENCE,
    templates: list[str] | None = None,
    settle: float = 0.0,
) -> ActionResult[Point]:
    """找到**某一种按钮**并点击它的中心。

    :param pick: 多个候选时挑哪个 ——

        * ``only``（默认）：**多于一个就报错**。最安全：不知道点哪个就别点。
        * ``best``：分数最高的那个（同族两张图都像时有用）；
        * ``right`` / ``left`` / ``top`` / ``bottom``：按位置挑。

    :param settle: 点完等多久让界面反应（秒，走 ``ctx.sleep``，可被停止打断）。
    :return: ``success(按钮中心, folder=..., template=..., score=..., count=...)`` /
        ``not_found``（没找到，或 ``only`` 时多于一个）。
    """
    if pick not in PICK_CHOICES:
        raise ConfigError(f"pick 只能是 {PICK_CHOICES}，收到 {pick!r}")

    hits = find_buttons(ctx, folder, region, confidence=confidence, templates=templates)
    if not hits:
        return ActionResult.not_found(
            f"没找到 {folder} 这类按钮（阈值 {confidence:.2f}）",
            folder=folder,
            region=region,
        )
    if pick == "only" and len(hits) > 1:
        return ActionResult.not_found(
            f"找到 {len(hits)} 个 {folder} 按钮，pick='only' 不知道点哪个"
            f"（{[(hit.point.x, hit.point.y) for hit in hits[:5]]}）—— "
            f"给 region 缩小范围，或显式选 pick",
            folder=folder,
            count=len(hits),
        )

    hit = _pick(hits, pick)
    clicked = actions.click_source_point(ctx.session, hit.point)
    if not clicked.ok:
        return clicked

    ctx.invalidate_frame()
    if settle:
        ctx.sleep(settle)
    clicked = replace(clicked, message=f"点了 {hit.template} 的中心（{folder}）")
    return clicked.with_meta(
        folder=folder,
        template=hit.template,
        score=round(hit.score, 3),
        count=len(hits),
        pick=pick,
    )


def _pick(hits: list[ButtonHit], pick: str) -> ButtonHit:
    if pick == "best":
        return max(hits, key=lambda hit: hit.score)
    if pick == "right":
        return max(hits, key=lambda hit: hit.point.x)
    if pick == "left":
        return min(hits, key=lambda hit: hit.point.x)
    if pick == "top":
        return min(hits, key=lambda hit: hit.point.y)
    if pick == "bottom":
        return max(hits, key=lambda hit: hit.point.y)
    return hits[0]  # only


# --------------------------------------------------------------------------- #
# 四种按钮各一个入口
#
# 底层是同一个 :func:`click_button`（只比边框环），但**写脚本的人知道
# 自己要的是哪种按钮** —— 让调用点直接说清"金色确认 / 花纹确认 / 青色取消 /
# 蓝色下一步"，比传一个字符串文件夹名更难写错，日志里也一眼看出意图。
# --------------------------------------------------------------------------- #
def click_shadow_confirm(
    ctx: RunContext,
    region: Region | None = None,
    *,
    pick: str = "only",
    confidence: float = BUTTON_CONFIDENCE,
    templates: list[str] | None = None,
    settle: float = 0.0,
) -> ActionResult[Point]:
    """点**金色发光确认按钮**：创建队伍 / 添加伙伴 / 确定 / 投降确认…"""
    return click_button(
        ctx,
        BUTTON_SHADOW_CONFIRM,
        region,
        pick=pick,
        confidence=confidence,
        templates=templates,
        settle=settle,
    )


def click_pattern_confirm(
    ctx: RunContext,
    region: Region | None = None,
    *,
    pick: str = "only",
    confidence: float = BUTTON_CONFIDENCE,
    templates: list[str] | None = None,
    settle: float = 0.0,
) -> ActionResult[Point]:
    """点**金色花纹边框的大确认按钮**：选将确定 / 开始匹配 / 结算确认…"""
    return click_button(
        ctx,
        BUTTON_PATTERN_CONFIRM,
        region,
        pick=pick,
        confidence=confidence,
        templates=templates,
        settle=settle,
    )


def click_shadow_cancel(
    ctx: RunContext,
    region: Region | None = None,
    *,
    pick: str = "only",
    confidence: float = BUTTON_CONFIDENCE,
    templates: list[str] | None = None,
    settle: float = 0.0,
) -> ActionResult[Point]:
    """点**青色发光取消按钮**。"""
    return click_button(
        ctx,
        BUTTON_SHADOW_CANCEL,
        region,
        pick=pick,
        confidence=confidence,
        templates=templates,
        settle=settle,
    )


def click_qj_next(
    ctx: RunContext,
    region: Region | None = None,
    *,
    pick: str = "only",
    confidence: float = BUTTON_CONFIDENCE,
    templates: list[str] | None = None,
    settle: float = 0.0,
) -> ActionResult[Point]:
    """点**蓝底金框的「下一步」**。"""
    return click_button(
        ctx,
        BUTTON_QJ_NEXT,
        region,
        pick=pick,
        confidence=confidence,
        templates=templates,
        settle=settle,
    )
