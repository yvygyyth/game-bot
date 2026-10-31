"""按钮快捷方法 —— **一个文件夹 = 一种按钮，一个方法按文件夹点**。

## 为什么这样分

这游戏满屏都是"同一副金框、只换中间几个字"的按钮：创建队伍 / 添加伙伴 / 开始匹配 /
确定 / 下一步…… 每加一个按钮裁一张图、登记一个 `T_*`、写一个步骤，图会越攒越多，
而它们其实只是**同一种按钮的不同文字版本**。

所以按**家族**组织：

```
games/mingjiangsha/templates/shadowConfirm/   ← 金色确认按钮：各种文字版本都放这儿
games/mingjiangsha/templates/shadowCancel/    ← 青色取消按钮
```

调用时只说"点哪种按钮"，不说"点哪句字"：

```python
from games.mingjiangsha.templates import BUTTON_SHADOW_CANCEL, BUTTON_SHADOW_CONFIRM
from games.mingjiangsha.utils import click_button

click_button(ctx, BUTTON_SHADOW_CONFIRM)   # 金色确认（创建队伍 / 添加伙伴 / 确定…）
click_button(ctx, BUTTON_SHADOW_CANCEL)    # 取消
```

## 为什么不用"边框模板"统一所有按钮

试过：取一条 12x33 的边线去匹配所有金框按钮，**裁剪图上**能命中四类按钮、
还分得开青色取消。但在**整屏截图**上它命中 100 次 —— 面板边框、图标边缘全是
"亮竖边"。这类误命中在裁剪图上完全看不出来。

**整按钮模板**没这个问题：同一个家族的不同文字版本互相不会命中（文字就是差异），
在 15 张真机截图上是"每个家族最多命中 1 次、分数 0.979~0.999"。
代价是**一种按钮一个文件夹、一张图一个文字版本** —— 但那是"丢张图"的成本，
比"点错按钮"低得多。

## 约定

* 文件夹里的图**必须完整包含按钮**（四周留 2~3 像素），别裁到按钮外的大片背景 ——
  背景会随界面变；
* 同一家族里，不同文字版本**同一时刻只会出现一个**。要是某次真出现两个，
  `pick="only"`（默认）会直接报错而不是猜 —— 猜错的代价是点错按钮；
* 一种按钮一个文件夹。**别把两种不同的按钮混进一个文件夹**，那会让 `pick` 失效。

阈值：实测 0.979~0.999，默认取 **0.90**（跨渲染差异留余量）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.bootstrap import project_root
from gamebot.exceptions import ConfigError
from gamebot.types import ActionResult, Point, Region

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = [
    "BUTTON_CONFIDENCE",
    "ButtonHit",
    "click_button",
    "find_buttons",
    "folder_templates",
]

#: 默认阈值。实测同一家族的文字版本互相不命中，真按钮 0.979~0.999 —— 0.90 有余量。
BUTTON_CONFIDENCE = 0.90

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
