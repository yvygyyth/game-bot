"""每日领奖 —— 流程图。

```
root --点邮件--> mail --一键领取/关邮箱/点活动--> activity
     --抽两张卡/关活动/点丹青阁--> gallery --每日礼包/关--> finish（回首页）
```
"""

from __future__ import annotations

from gamebot.flow import EngineOptions, Node, Transition
from gamebot.scenario_spec import ScenarioSpec
from games import on_page

from .bindings import BINDINGS
from .pages import FEATURE_TREE
from .steps import (
    claim_gallery_then_finish,
    draw_then_gallery,
    finish_daily,
    mail_claim_then_activity,
    open_mail,
)

__all__ = ["SCENARIO"]


SCENARIO = ScenarioSpec(
    name="daily",
    initial="root",
    tree=FEATURE_TREE,
    bindings=BINDINGS,
    nodes=(
        Node(
            "root",
            steps=[open_mail],
            description="首页：点邮件入口",
            transitions=[
                Transition("mail", on_page("daily/mail"), 10, "进入邮箱"),
            ],
        ),
        Node(
            "mail",
            steps=[mail_claim_then_activity],
            description="邮箱：一键领取 → 关邮箱 → 点活动",
            transitions=[
                Transition("activity", on_page("daily/activity"), 10, "进入活动"),
            ],
        ),
        Node(
            "activity",
            steps=[draw_then_gallery],
            description="活动：抽两张卡 → 关活动 → 点丹青阁",
            transitions=[
                Transition("gallery", on_page("daily/gallery"), 10, "进入丹青阁"),
            ],
        ),
        Node(
            "gallery",
            steps=[claim_gallery_then_finish],
            description="丹青阁：关购买弹窗 → 每日礼包 → 关",
            transitions=[
                Transition("finish", on_page("daily/root"), 10, "回首页，结束"),
            ],
        ),
        Node(
            "finish",
            steps=[finish_daily],
            description="收尾（返回 not_found，走末梢结束）",
        ),
    ),
    options=EngineOptions(
        tick_interval=0.4,
        require_confirmed=True,
        max_runtime=300.0,
    ),
)
