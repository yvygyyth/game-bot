"""千里单骑 —— 这个玩法专用的步骤。

通用的步骤在 ``gamebot.execution.step``（点击、按键、等待、条件……）；
这里只放"跟这个玩法绑死"的，别的脚本用不到。

两条约定：

* 步骤**不截图**（除了显式声明 ``needs_fresh_frame=True``）——
  帧从 ``ctx`` 拿，保证一轮里的多个步骤看的是同一张画面；
* 步骤**不重试**、不 sleep 等重试 —— 那是 ``policy`` 的事。
  这里只写"做一次"的逻辑，失败就返回失败。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.step import Step
from gamebot.types import ActionResult

if TYPE_CHECKING:
    from gamebot.context import RunContext
    from gamebot.execution.policy import StepPolicy


class EnterQianliStep(Step):
    """从首页进入千里单骑。

    先点入口按钮；点了之后等一下页面切换 —— 不等的话，
    下一轮可能还停在首页，会重复点一次（游戏里表现为"多点了两下"）。
    """

    TEMPLATE = "enter_button.png"
    SETTLE = 1.0
    """点完之后给页面切换留的时间。"""

    def __init__(self, *, policy: StepPolicy | None = None) -> None:
        super().__init__("进入千里单骑", policy=policy, needs_fresh_frame=True)

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        result = actions.click_image(ctx.session, self.TEMPLATE, confidence=0.85)
        if not result.ok:
            return result
        # 点成功之后再等；失败就直接返回，不浪费这一秒
        ctx.sleep(self.SETTLE)
        ctx.invalidate_frame()  # 画面肯定变了，别让后面的步骤看旧帧
        return result

    def used_templates(self) -> tuple[str, ...]:
        return (self.TEMPLATE,)


class CastSkillStep(Step):
    """放一个技能，然后等冷却。

    战斗中就靠这个循环。**不判断血量、不选技能** —— 那些属于流程层
    （用边和条件表达），步骤只负责"点一下"。
    """

    TEMPLATE = "battle/skill.png"

    def __init__(
        self,
        *,
        cooldown: float = 1.2,
        confidence: float = 0.85,
        policy: StepPolicy | None = None,
    ) -> None:
        super().__init__("放技能", policy=policy, needs_fresh_frame=True)
        self.cooldown = cooldown
        self.confidence = confidence

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        result = actions.click_image(ctx.session, self.TEMPLATE, confidence=self.confidence)
        if result.ok:
            # 可被中止的等待：点了停止就立刻抛 Cancelled，不会睡满
            ctx.sleep(self.cooldown)
        return result

    def used_templates(self) -> tuple[str, ...]:
        return (self.TEMPLATE,)


class ClaimRewardStep(Step):
    """在结算页面点确认，把奖励收下。

    点两次是为了兜住"领奖之后又弹一个奖励框"的情况 ——
    这是这个玩法里常见的一步（第一次确认 → 掉落实物 → 再点一次关闭）。
    第二次找不到不算失败。
    """

    TEMPLATE = "result/confirm.png"

    def __init__(self, *, policy: StepPolicy | None = None) -> None:
        super().__init__("领取奖励", policy=policy, needs_fresh_frame=True)

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        first = actions.click_image(ctx.session, self.TEMPLATE, confidence=0.85)
        if not first.ok:
            return first
        ctx.sleep(0.4)
        ctx.invalidate_frame()
        # 第二次是"有就点、没有就算"，所以忽略结果
        actions.click_image(ctx.session, self.TEMPLATE, confidence=0.85)
        return first

    def used_templates(self) -> tuple[str, ...]:
        return (self.TEMPLATE,)


class HasStaminaStep(Step):
    """判断体力够不够打一轮。

    只查询、不动作 —— 结果写进黑板，让边的条件去读。
    这是"步骤与条件解耦"的标准写法：步骤负责**采集事实**，
    流程负责**根据事实做决定**。
    """

    TEMPLATE = "stamina_text.png"
    KEY = "qianli.stamina"

    def __init__(self, *, minimum: int = 6, policy: StepPolicy | None = None) -> None:
        super().__init__("检查体力", policy=policy)
        self.minimum = minimum

    def run(self, ctx: RunContext) -> ActionResult[int]:
        from gamebot.types import Region

        region = ctx.config.region("qianli.stamina") or Region(1140, 24, 90, 28)
        result = ctx.frame().read_number(region)
        if result.ok:
            value = int(result.value or 0)
            ctx.blackboard.set(self.KEY, value)
            if value < self.minimum:
                return ActionResult.not_found(
                    f"体力 {value} 不够打一轮（需要 {self.minimum}）", value=value
                )
            return ActionResult.success(value, stamina=value)
        # 读不出来不算致命：让流程继续，靠别的条件兜底
        ctx.blackboard.set(self.KEY, None)
        return ActionResult.not_found(f"读不到体力值: {result.message}")


def stamina_enough(ctx: RunContext, minimum: int = 6) -> bool:
    """边条件：体力够不够。读 :class:`HasStaminaStep` 写进黑板的值。"""
    value = ctx.blackboard.get(HasStaminaStep.KEY)
    return isinstance(value, int) and value >= minimum
