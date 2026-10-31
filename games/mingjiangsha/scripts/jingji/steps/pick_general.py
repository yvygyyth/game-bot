"""选将：点一个武将的血条 → 点「确定」。

## 为什么是一步、一个状态

选将界面的「确定」按钮**两种样子**（没选武将时灰、选了之后金），本来拆过
``select/idle`` / ``select/picked`` 两个状态。但**真机上那个按钮的尺寸和截图里
不一样**（实拍 435x89，旧模板 401x105），两个状态的模板都匹配不上；而"金/灰"
又只差在颜色上，模板匹配对颜色不敏感。

所以改成：**一个状态 ``select``**（认「换座」按钮 —— 它在两种状态下完全一样，
实测 1.000），步骤里点完卡睡 0.5s、再点固定坐标的「确定」。
「确定」在选将界面是**居中固定**的（实拍中心约 (1276, 739)），和首页的
竞技入口一样，固定坐标在这里是安全的。

## 怎么认出"武将卡"：找**血条**

卡面上**每局都不一样**的是立绘和名字 —— 拿它们当模板，下一局就失效了。
而**每个武将必定有血条**，血条的长相和位置都不变，所以：

    find_all_images(T_SELECT_HEALTH)   ->  8 张卡各命中一处  ->  挑一个点

实测（``logs/tools/check_select_health.py``）：``select1.png`` 在阈值 0.85 下
命中 **22** 个 —— 因为模板是"竖排三个勾玉"，而每列勾玉在竖直方向能
错开落位（每列约 3 个）。所以这里**按 x 聚组**，一组 = 一张卡。

## 点哪张

"随便点一个" —— 这里固定挑 **x 最小那一组**（最左边那张卡）。
挑最左边而不是"第一个命中的"：``find_all_images`` 是按**分数**降序返回的，
分数会随画面细节浮动，"第一个"其实是随机的；按 x 挑才是确定的
（同一局里结果稳定，出问题也好复现）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.types import ActionResult
from gamebot.types import Point as _Point

from ..templates import T_SELECT_HEALTH

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["CONFIRM_POINT", "CONFIRM_SETTLE", "PICK_SETTLE", "pick_general"]

#: 点武将卡之后等它变成选中态（秒）。界面要重画那张卡的边框。
PICK_SETTLE = 0.5

#: 点「确定」之后等进战斗（秒）。战斗加载比一般界面慢，给宽一点。
CONFIRM_SETTLE = 1.5

#: 「确定」的中心（源坐标）。选将界面居中固定，灰/金两态位置不变。
CONFIRM_POINT = _Point(1276, 739)

#: 判定"这两个命中属于同一张卡"的 x 容差（像素）。
#:
#: 同一张卡的几个勾玉 x **几乎相同**（实测抖动 0，同列就是同一个 x），
#: 而相邻两张卡的勾玉列相距 **约 268px**（实测：8 张卡等距）。
#: 所以 60 很宽松：同卡必合并，邻卡必不合并。
COLUMN_GAP = 60


def _group_by_column(points: list[_Point], gap: int = COLUMN_GAP) -> list[list[_Point]]:
    """把命中点**按 x 聚成列** —— 一列 = 一张武将卡。

    返回按 x 升序（最左边那张卡在最前），列内按 y 排序。

    ## 为什么按"相邻间隔"切，而不是"和列首比"

    第一版写的是 ``point.x - columns[-1][0].x <= tolerance``（和**列首**比），
    两个后果都踩到了：

    * 列首在 1213，下一个点在 1479（**另一张卡**）：差 266 > 60，正确切分；
    * 但列首在 1479、下一个点在 1537（**同一个大列里的漂移**）：
      差 58 < 60，被并进同一列 —— 于是 8 列变成 7 列，
      而那一列吃了 4 个点（实测 ``[4,4,4,2,2,2,4]``）。

    按**相邻两点的间隔**切就没这个问题：链式传播不会让一张卡的漂移
    把下一张卡也吞进来。

    ## 为什么不让 matcher 的 ``min_distance`` 去重

    那个是按**中心距**去重的，而同卡的勾玉竖直相距 29px、邻卡相距 268px ——
    想合并同卡的就得把阈值开到 29 以上，那会把"同卡间距"和"邻卡间距"
    混进同一个数字。**语义不同的东西就该分开表达**，所以自己按 x 分组。
    """
    columns: list[list[_Point]] = []
    previous_x: int | None = None
    for point in sorted(points, key=lambda p: (p.x, p.y)):
        if previous_x is None or point.x - previous_x > gap:
            columns.append([point])
        else:
            columns[-1].append(point)
        previous_x = point.x
    for column in columns:
        column.sort(key=lambda p: p.y)
    return columns


def pick_general(ctx: RunContext) -> ActionResult[Any]:
    """选将：找血条，点一张武将卡，再点「确定」。

    点完卡先等 ``PICK_SETTLE``（界面要重画选中态），然后点居中固定的
    「确定」；进战斗的加载用 ``CONFIRM_SETTLE`` 兜底。
    """
    # 全图找。提速时加 region= —— 武将卡那一排大致在
    # 客户区 y 200~620、x 100~2450（8 张等距，间距约 268）。
    found = ctx.frame().find_all_images(T_SELECT_HEALTH)
    if not found.ok or not found.value:
        return ActionResult.not_found(
            "选将界面里一个血条都没找到（界面还没画出来？）",
            template=T_SELECT_HEALTH,
        )

    columns = _group_by_column(list(found.value))
    if not columns:
        return ActionResult.not_found("血条命中点分组后为空", template=T_SELECT_HEALTH)

    # **挑最左边那一列**（确定，不随分数浮动）。
    column = columns[0]
    target = column[len(column) // 2]  # 列内取中间的勾玉，离卡的上下边都远

    # ⚠️ 这个点来自 find_all_images = **源坐标**，所以必须走
    # click_source_point，不能再走 click_logic_point（那会二次换算）。
    clicked = actions.click_source_point(ctx.session, target)
    if not clicked.ok:
        return clicked
    ctx.invalidate_frame()
    ctx.sleep(PICK_SETTLE)

    # 「确定」：选将界面居中固定；点完等战斗加载。
    confirmed = actions.click_source_point(ctx.session, CONFIRM_POINT)
    if not confirmed.ok:
        return confirmed
    ctx.invalidate_frame()
    ctx.sleep(CONFIRM_SETTLE)
    return confirmed.with_meta(
        cards=len(columns),
        column_x=target.x,
        picked_at=(target.x, target.y),
        confirmed_at=(CONFIRM_POINT.x, CONFIRM_POINT.y),
    )
