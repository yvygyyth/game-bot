"""名将杀 —— 游戏级公共快捷方法 / 公共识别逻辑。

竞技入口的识别放在游戏级，因为它是"进竞技场""进房间"这类脚本共同的第一跳。

## 难点只有一个：鼠标悬浮会改变这张卡的样子

你说得对 —— 悬浮确实影响它。我量了三张不同悬浮程度的图，结论如下
（模板统一用**空闲态实拍**裁的那张，搜索范围就是 :data:`JINGJI_ROI`）：

| 状态 | 分数 |
|---|---|
| 首页·空闲（鼠标不在卡上） | **1.000** |
| 悬浮·弱 → 强（你那三张图） | **0.822 / 0.782 / 0.647** |
| **不在首页**（竞技场页 / 队伍面板 / 准备态） | **0.382 / 0.439 / 0.439** |

**正例最低 0.647，反例最高 0.439，中间空出 0.208。** 所以阈值取 **0.55**
（两边各留约 0.1）就够了，**一个模板就够** —— 不需要为每种悬浮状态各做一个。

## 为什么一个模板就够（也是为什么这跟直觉不一样）

关键在于 **ROI 的第二个作用**：`JINGJI_ROI` 只框住这张卡，
而它旁边的"房间/战没/煮酒"三张卡都在框外。

于是阈值要回答的问题**变了**：不是"这是不是竞技卡的某个特定姿态"，
而只是"**这张卡在不在**"。前者要求模板和姿态一一对应（那才需要多模板），
后者只需要一个能容忍姿态变化的下限。

用数据说话：不套 ROI 时全图次高分是 0.611（旁边的卡），留不出余量；
套上 ROI 之后反例最高只有 0.439，余量一下就出来了。

> 一般化的经验：**先想办法把"多分类"变成"二分类"，再谈调阈值。**
> 多做一个模板是下策；把搜索范围收窄往往更有效，也更好维护。

## 顺手排除掉的四个错误猜测（免得以后再花时间）

都实测过，全是否：

* **不是尺度问题** —— 0.80~2.00 倍逐个扫，你那三张图都在 **1.00~1.02** 处达到峰值；
  而且 2% 的尺度误差只值 0.07 分（1.000 -> 0.933），解释不了 0.82；
* **不是压缩噪声** —— 实拍压成 JPEG q70 再匹配还有 0.996；
* **不是"缩小再放大"的往返重采样** —— 模拟 0.897 缩 + 1.115 放，自己匹配自己 0.991；
* **不是亮度/对比度** —— 三张图和实拍的平均亮度 128 vs 124、对比度 73 vs 76，
  几乎一样；而 TM_CCOEFF_NORMED 本来就能吃掉线性亮度变化。

所以那 18% 的差异是**结构性**的（卡片被挪动/重绘），正如你说的那样。

## 待机动画不用管

卡片一直在动（光效扫过会让 38% 的像素变化），但模板分数稳在 **0.985 以上** ——
TM_CCOEFF_NORMED 对"整体叠加一层光"这类变化是稳的。
实测：同一模板在 2.8 秒内的 5 帧上分别是 1.000 / 0.992 / 0.987 / 0.994 / 0.985。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gamebot.types import ActionResult, Point, Region

if TYPE_CHECKING:
    from gamebot.context import RunContext

#: 竞技入口的搜索区域（客户区坐标）。
#:
#: 刻意**只框住这一张卡**：旁边的"房间/战没/煮酒"都在框外。
#: 上下留了余量 —— 悬浮时这张卡会往右上弹（实测位移 (+35,-32)、放大 1.1 倍），
#: 框太紧会让弹出去的卡片部分落到框外。
JINGJI_ROI = Region(850, 260, 320, 450)

#: 竞技卡的模板（空闲态实拍 1:1 裁出来的）。
#:
#: **在功能级模板根下**（``games/mingjiangsha/jingji/templates/``）。
#:
#: 它是**竞技功能的专属入口图**，不是公共资源 —— 首页上还有
#: 「房间 / 战没 / 煮酒」三张并列的兄弟卡，那三张各属它们的功能。
#: 所以它和"用竞技卡认自己"的那个首页页一起待在功能目录里
#: （见 :mod:`games.mingjiangsha.jingji.pages`）。
#:
#: 曾经把它放到游戏级，理由是"声明识别它的是游戏级的首页页"。
#: 那个推理错在第一步：**首页不该用某个功能的入口卡来认自己** ——
#: 那样首页的身份就绑在竞技功能上了，别的功能为了认首页得反过来引用
#: 竞技场的资源。分层里更要紧的一条是：
#: **一个功能的专属资源，不能用来定义游戏级的东西**。
T_JINGJI = "jingji_card.png"

#: 阈值。取的是实测空隙的中点：正例最低 0.647、反例最高 0.439。
#:
#: 偏向哪边？**偏低**是安全的，因为还有第二道闸：``Node.page`` 的位置守卫 ——
#: 页面没被认成 ``home`` 时，这个步骤根本不会执行。
#: 漏认的后果是"它不动"（安全），误认的后果才是"点错地方"（危险），
#: 而误认需要同时骗过位置守卫和这个阈值两层。
CONF_JINGJI = 0.55

#: 竞技卡的**期望中心**（客户区坐标）。自检断言它 ——
#: "找是找到了，但位置对不对"和"找没找到"一样重要：
#: 找错地方比找不到更危险，因为下一步就照着它点下去了。
JINGJI_CENTER = Point(1005, 457)
JINGJI_TOLERANCE = 40


def find_jingji_entry(ctx: RunContext) -> ActionResult[Point]:
    """在首页找到「竞技」入口，返回可点击的中心点（**源坐标**）。

    :return: ``success(Point, template=..., score=...)``；没命中时 ``not_found``。
    """
    frame = ctx.frame()
    result = frame.find_image(T_JINGJI, region=JINGJI_ROI, confidence=CONF_JINGJI)
    if result.ok and result.value is not None:
        return ActionResult.success(
            result.value,
            template=T_JINGJI,
            score=result.meta.get("score", 0.0),
            rect=result.meta.get("rect"),
        )

    return ActionResult.not_found(
        f"在这个区域里找不到竞技入口（{T_JINGJI} 未达 {CONF_JINGJI:.2f}）: {result.message}",
        region=JINGJI_ROI.to_tuple(),
    )


def click_jingji_entry(ctx: RunContext) -> ActionResult[Point]:
    """找到并点击「竞技」入口。

    先找再点，找不到就**什么都不做** —— 绝不"就近点一下试试"。
    识图脚本最危险的失败模式就是在没认出来的情况下动手。
    """
    from gamebot.atomic import actions

    found = find_jingji_entry(ctx)
    if not found.ok or found.value is None:
        return ActionResult(found.status, None, found.message, found.elapsed, found.meta)

    point: Point = found.value
    result = actions.click_source_point(ctx.session, point)
    if result.ok:
        ctx.invalidate_frame()  # 点完之后画面肯定要变，别让后面的步骤看旧帧
    return ActionResult(
        result.status,
        point,
        result.message,
        result.elapsed,
        {**result.meta, **found.meta},
    )
