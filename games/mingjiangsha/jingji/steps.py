"""竞技场 —— 本功能的步骤。

## 为什么是"顺序找一个能点的按钮"而不是"三个节点三条边"

竞技场的三个状态（建队前 / 建队后 / 已准备）**是同一个页面**，
页面标识（左上角标题）在三种状态下都是 1.000 —— 也就是说
**页面树区分不了它们**。

那就要在同一个页面上表达三段行为。两条路：

* 画三个节点、用边把它们串起来 —— 但三个节点的 ``page`` 都是 ``home/jingji``，
  位置守卫对它们一视同仁，"现在该在第几段"得靠额外条件判断，反而绕；
* **一个节点 + 一个按顺序探测的步骤**（这里选的）—— 把"该点哪个"交给游戏自己：
  哪个按钮在就点哪个。状态机在游戏那边，脚本这边不需要重复维护一份。

这也更抗状态错位：万一某一步没生效，下一轮照样能接着往下走，不会卡死在某个节点上。

## 一个必须记住的实测事实

**「开始匹配」在三个状态下都在**（start_match 模板在 jingji.png 上也是 0.999）。
所以它不能用来区分状态 —— 顺序检测里它必须排最后，否则第一轮就直接点它了。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.step import Step
from gamebot.types import ActionResult, Region

from ..shortcuts import T_JINGJI, click_jingji_entry

if TYPE_CHECKING:
    from gamebot.context import RunContext
    from gamebot.execution.policy import StepPolicy

__all__ = [
    "T_ADD_PET",
    "T_CREATE_TEAM",
    "T_START_MATCH",
    "T_TITLE",
    "AdvanceTeamStep",
    "EnterJingjiStep",
]

#: 页面标识：左上角「竞技场」标题
T_TITLE = "jingji/title.png"

#: 三个按钮
T_CREATE_TEAM = "jingji/create_team.png"
T_ADD_PET = "jingji/add_pet.png"
T_START_MATCH = "jingji/start_match.png"

#: 按钮的搜索区域（客户区坐标）：右下角那块面板。
#: 三个按钮都在这儿，而左上角的标题、左边的三个功能按钮都在框外。
TEAM_ROI = Region(1400, 630, 470, 360)

#: 按钮阈值。实测：自己的图上 1.000，**彼此之间最高 0.690**
#: （创建队伍 vs 添加伙伴 —— 位置一样、只有文字不同，所以还能差出 0.31）。
CONF_BUTTON = 0.85


class EnterJingjiStep(Step):
    """在首页点「竞技」入口。

    点完之后**等一下再让出**：点下去到竞技场渲染出来有个过渡，
    不等的话下一轮还在首页（视觉上"多点了一下"），而且会白跑一轮识别。
    """

    SETTLE = 1.2

    def __init__(self, *, settle: float | None = None, policy: StepPolicy | None = None) -> None:
        super().__init__("进入竞技场", policy=policy, needs_fresh_frame=True)
        self.settle = self.SETTLE if settle is None else settle

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        result = click_jingji_entry(ctx)
        if not result.ok:
            # 找不到就如实返回，**绝不"就近点一下试试"**
            return result
        ctx.sleep(self.settle)
        ctx.invalidate_frame()
        return result

    def used_templates(self) -> tuple[str, ...]:
        return (T_JINGJI,)


class AdvanceTeamStep(Step):
    """推进队伍流程：创建队伍 → 添加伙伴 → 开始匹配。

    **按顺序探测**，点中一个就返回。顺序不能变：``开始匹配`` 在三个状态下
    都存在（实测 0.999），排前面的话第一轮就直接点它了。

    每次只点一个，且点完就 ``invalidate_frame`` —— 三个按钮的位置挨得很近，
    用旧帧判断下一步很容易在同一个状态上连点两下。
    """

    #: (模板, 中文名) —— 顺序即优先级
    SEQUENCE: tuple[tuple[str, str], ...] = (
        (T_CREATE_TEAM, "创建队伍"),
        (T_ADD_PET, "添加伙伴"),
        (T_START_MATCH, "开始匹配"),
    )

    SETTLE = 1.0
    """点完之后给界面反应的时间（秒）。"""

    def __init__(self, *, settle: float | None = None, policy: StepPolicy | None = None) -> None:
        super().__init__("推进队伍流程", policy=policy, needs_fresh_frame=True)
        self.settle = self.SETTLE if settle is None else settle

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        frame = ctx.frame()
        seen: list[str] = []

        for template, label in self.SEQUENCE:
            found = frame.find_image(template, region=TEAM_ROI, confidence=CONF_BUTTON)
            if not found.ok or found.value is None:
                seen.append(f"{label} 未达 {CONF_BUTTON:.2f}")
                continue

            clicked = actions.click_source_point(ctx.session, found.value)
            if not clicked.ok:
                return clicked
            ctx.sleep(self.settle)
            ctx.invalidate_frame()
            return ActionResult.success(
                found.value,
                action=label,
                template=template,
                score=found.meta.get("score", 0.0),
                message=f"点了「{label}」",
            )

        return ActionResult.not_found(
            "右下角三个按钮一个都没看到 —— " + "；".join(seen),
            region=TEAM_ROI.to_tuple(),
        )

    def used_templates(self) -> tuple[str, ...]:
        return tuple(template for template, _ in self.SEQUENCE)
