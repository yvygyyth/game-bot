"""沙盒测试游戏的专用步骤。

这里放两种步骤，正好覆盖"步骤要不要声明模板"的两种情况：

* :class:`NoteStep` —— **不碰图**的步骤，``used_templates()`` 返回空；
* :class:`ProbeStep` —— **要识图**的步骤，覆写 ``used_templates()``，
  于是 ``python -m games check`` 能查出它的图缺没缺。

第二种是重点：不覆写的话检查就查不到它用的模板，缺图只能在跑的时候才发现。
沙盒把这两种并排放着，就是为了让"该覆写"这件事看得见。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gamebot.atomic import actions
from gamebot.execution.step import Step
from gamebot.types import ActionResult

from .. import scene
from .shortcuts import note

if TYPE_CHECKING:
    from gamebot.context import RunContext
    from gamebot.execution.policy import StepPolicy


class NoteStep(Step):
    """只写黑板、不碰屏幕的步骤。测试流程走向用。"""

    def __init__(self, action: str, *, policy: StepPolicy | None = None) -> None:
        super().__init__(f"记录 {action}", policy=policy)
        self.action = action

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        return note(ctx, self.action)


class ProbeStep(Step):
    """识图并"点击"某个沙盒元素。

    覆写了 :meth:`used_templates`，所以 ``gamebot check`` 会检查这张图在不在。
    默认走 fake 后端，就算引擎跑起来也只写日志。
    """

    def __init__(
        self,
        template: str,
        *,
        confidence: float = 0.9,
        policy: StepPolicy | None = None,
    ) -> None:
        super().__init__(f"找 {template}", policy=policy, needs_fresh_frame=True)
        self.template = template
        self.confidence = confidence

    def run(self, ctx: RunContext) -> ActionResult[Any]:
        result = actions.click_image(ctx.session, self.template, confidence=self.confidence)
        note(ctx, f"click:{self.template}")
        return result

    def used_templates(self) -> tuple[str, ...]:
        return (self.template,)


class PageProbeStep(Step):
    """检查"当前这一页该有的元素"是不是真的在画面上。

    这是沙盒特有的步骤：它把页面树和合成屏幕对了一遍。
    真实游戏里对应的做法是"等某个元素出现再继续"。
    """

    def __init__(self, page_id: str, *, policy: StepPolicy | None = None) -> None:
        super().__init__(f"核对页面 {page_id}", policy=policy)
        self.page_id = page_id

    def run(self, ctx: RunContext) -> ActionResult[list[str]]:
        missing: list[str] = []
        for name in scene.PAGE_ELEMENTS.get(self.page_id, ()):
            item = scene.element(name)
            # is_image_visible 收的是**模板名**，不是 Query ——
            # "不可见"是有效答案（success(False)），所以这里判 value is True
            result = ctx.frame().is_image_visible(name, region=item.rect, confidence=0.9)
            if not (result.ok and result.value is True):
                missing.append(name)
        note(ctx, f"probe:{self.page_id}")
        if missing:
            return ActionResult.not_found(f"页面上看不到这些元素: {missing}", missing=missing)
        return ActionResult.success(list(scene.PAGE_ELEMENTS.get(self.page_id, ())))

    def used_templates(self) -> tuple[str, ...]:
        return scene.PAGE_ELEMENTS.get(self.page_id, ())
