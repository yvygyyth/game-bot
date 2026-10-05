"""推进队伍流程：创建队伍 → 添加伙伴 → 开始匹配。

## 为什么是"顺序找一个能点的按钮"而不是"三个节点三条边"

竞技场的三个状态**是同一个页面**，页面树区分不了它们（见 :mod:`.`）。两条路：

* 画三个节点、用边串起来 —— 但三个节点的 ``page`` 都是 ``home/jingji``，
  位置守卫对它们一视同仁，"现在该在第几段"得靠额外条件判断，反而绕；
* **一个步骤按顺序探测**（这里选的）—— 把"该点哪个"交给游戏自己。

还更抗状态错位：万一某一步没生效，下一轮照样接着往下走，不会卡死在某个节点上。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.step import Step
from gamebot.types import ActionResult, Region

if TYPE_CHECKING:
    from gamebot.context import RunContext
    from gamebot.execution.policy import StepPolicy

__all__ = [
    "CONF_BUTTON",
    "TEAM_ROI",
    "T_ADD_PET",
    "T_CREATE_TEAM",
    "T_START_MATCH",
    "AdvanceTeamStep",
]

#: 三个按钮的模板
T_CREATE_TEAM = "jingji/create_team.png"
T_ADD_PET = "jingji/add_pet.png"
T_START_MATCH = "jingji/start_match.png"

#: 按钮的搜索区域（客户区坐标）：右下角那块面板。
#: 三个按钮都在这儿，而左上角的标题、左边的三个功能按钮都在框外。
TEAM_ROI = Region(1400, 630, 470, 360)

#: 按钮阈值。实测：自己的图上 1.000，**彼此之间最高 0.690**
#: （创建队伍 vs 添加伙伴 —— 位置一样、只有文字不同，所以还能差出 0.31）。
CONF_BUTTON = 0.85


class AdvanceTeamStep(Step):
    """按顺序探测，点中一个就返回。

    每次只点一个，且点完就 ``invalidate_frame`` —— 三个按钮的位置挨得很近，
    用旧帧判断下一步很容易在同一个状态上连点两下。
    """

    #: (模板, 中文名) —— **顺序即优先级，不能变**
    SEQUENCE: tuple[tuple[str, str], ...] = (
        (T_CREATE_TEAM, "创建队伍"),
        (T_ADD_PET, "添加伙伴"),
        (T_START_MATCH, "开始匹配"),
    )

    SETTLE = 1.0
    """点完之后给界面反应的时间（秒）。"""

    def __init__(
        self, *, settle: float | None = None, policy: StepPolicy | None = None
    ) -> None:
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
