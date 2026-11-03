"""每日领奖（名将杀）—— 邮件 / 活动 / 丹青阁。"""

from __future__ import annotations

from gamebot.feature import FeatureSpec

from .form import FORM
from .graph import SCENARIO

__all__ = ["SPEC"]

SPEC = FeatureSpec(
    name="mingjiangsha/daily",
    title="每日领奖",
    slug="daily",
    window_title="名将杀",
    description="每日领奖：邮件 → 活动（卜卦）→ 丹青阁（每日礼包）",
    scenario=SCENARIO,
    form=FORM,
    use_pyramid=False,
)
