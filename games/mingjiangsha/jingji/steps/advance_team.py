"""推进队伍流程：创建队伍 → 添加伙伴 → 开始匹配。

## 三个状态现在是**分开的页面**，所以拆成三个步骤

以前这里只有**一个** ``AdvanceTeamStep``：竞技场的三个阶段是同一个页面，
页面树区分不了它们，所以让一个步骤"按顺序探测三个按钮，点中一个就返回"。

现在页面树能区分了（见 :mod:`.pages` 的三个子状态），拆开的好处立刻显现：

* **每个步骤只负责一个按钮，而且自己带"位置守卫"** —— 它只在对应状态下才被
  执行（节点的 ``page`` 声明），所以不会出现"在错误的阶段点了错误的按钮"；
* **失败不再是静默的** —— 原来三个未命中会合并成一句"三个按钮一个都没看到"；
  现在只有那一个按钮要判断，日志能直接说清是哪个没认出来；
* **流程可见** —— ``describe`` 里能看出"我现在走到第几段"，而不是一个黑盒步骤。

## 每个步骤都会显式验证"按钮真的在"

步骤虽然由位置守卫保护（不在对应状态就不执行），但**仍然自己再查一次**。
两个理由：

1. 状态识别有帧延迟 —— 点完「创建队伍」的那一帧还没刷新，状态可能仍报"建队前"，
   这时如果直接点，就会在同一个地方点第二下；
2. 守卫和步骤用的是同一份依据（节点的 ``page`` 来自树的识别），但它们**发生在
   不同的时刻**（守卫在取帧前用上一轮结论，步骤在取帧后）。多查一次花不了多少，
   换来的是"点下去的时候按钮确实在"。

两个步骤都会 ``needs_fresh_frame=True`` 并在点完后 ``invalidate_frame()`` ——
按钮位置挨得近，用旧帧判断很容易连点两下。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.step import Step
from gamebot.types import ActionResult

from ..pages import CONF_BUTTON, JINGJI_TEAM_ROI, T_ADD_PET, T_CREATE_TEAM, T_START_MATCH

if TYPE_CHECKING:
    from gamebot.context import RunContext
    from gamebot.execution.policy import StepPolicy

__all__ = [
    "DEFAULT_CONF",
    "DEFAULT_SETTLE",
    "TEAM_ROI",
    "T_ADD_PET",
    "T_CREATE_TEAM",
    "T_START_MATCH",
    "AddPetStep",
    "CreateTeamStep",
    "StartMatchStep",
]

#: 三个按钮的搜索区域（客户区坐标）：右下角那块面板。
#: **和页面树共用同一个值** —— 两处各写一份迟早会不一致（改了页面 ROI
#: 忘了改这里，症状是"状态认出来了但按钮找不到"，极难查）。
TEAM_ROI = JINGJI_TEAM_ROI

#: 阈值的默认值（声明在 :mod:`.pages`，这里只是转发给外部引用）。
DEFAULT_CONF = CONF_BUTTON

#: 点完默认等多久（秒）。**只作为声明的镜像** —— 真正生效的值来自运行参数
#: ``jingji.settle``（表单可调）。
DEFAULT_SETTLE = 1.0


class _ClickButtonStep(Step):
    """点一个按钮的公共实现。**只做一件事**：确认它在，然后点它。

    三个子类只差"哪个模板、哪个中文名"。抽这一层是为了让"找到 → 点 → 作废帧"
    这段只有一处 —— 它错了（比如忘了 ``invalidate_frame``）会在三个地方同时错。
    """

    #: 子类填：要点的模板
    TEMPLATE: str = ""
    #: 子类填：中文名（进日志和 action）
    LABEL: str = ""

    def __init__(self, *, policy: StepPolicy | None = None) -> None:
        super().__init__(f"点「{self.LABEL}」", policy=policy, needs_fresh_frame=True)

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        frame = ctx.frame()
        # 阈值和等待时间都来自**运行参数**（表单可调）。每次 run 时现读，
        # 所以同一个步骤对象在两次运行里可以用不同的值。
        confidence = ctx.param("jingji.confidence", DEFAULT_CONF)
        settle = ctx.param("jingji.settle", DEFAULT_SETTLE)

        found = frame.find_image(self.TEMPLATE, region=TEAM_ROI, confidence=confidence)
        if not found.ok or found.value is None:
            return ActionResult.not_found(
                f"没看到「{self.LABEL}」（{self.TEMPLATE} 未达 {confidence:.2f}）",
                template=self.TEMPLATE,
                region=TEAM_ROI.to_tuple(),
                score=found.meta.get("score", 0.0),
            )

        clicked = actions.click_source_point(ctx.session, found.value)
        if not clicked.ok:
            return clicked
        ctx.sleep(settle)
        # 位置挨得近：不作废旧帧，下一轮很可能拿旧帧再点一次同一个地方
        ctx.invalidate_frame()
        return ActionResult.success(
            found.value,
            action=self.LABEL,
            template=self.TEMPLATE,
            score=found.meta.get("score", 0.0),
            message=f"点了「{self.LABEL}」",
        )

    def used_templates(self) -> tuple[str, ...]:
        return (self.TEMPLATE,)


class CreateTeamStep(_ClickButtonStep):
    """建队前：点「创建队伍」。"""

    TEMPLATE = T_CREATE_TEAM
    LABEL = "创建队伍"


class AddPetStep(_ClickButtonStep):
    """建队后：点「添加伙伴」。"""

    TEMPLATE = T_ADD_PET
    LABEL = "添加伙伴"


class StartMatchStep(_ClickButtonStep):
    """加完伙伴：点「开始匹配」。"""

    TEMPLATE = T_START_MATCH
    LABEL = "开始匹配"
