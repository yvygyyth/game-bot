"""每日领奖 —— 流程图（首页 hub + 独立入口）。

```
home/hub
  ├─ 邮件有红点   → mail     → 一键领取 → 回 home
  ├─ 活动有红点   → activity → 抽两张 + 军需月令 → 回 home
  ├─ 丹青阁有红点 → gallery  → 每日礼包 → 回 home
  ├─ 商店有红点   → shop     → 买每日 → 回 home
  ├─ 煮酒         → zhu_jiu  → 买 → 回 home
  ├─ 战役         → zhan_yi  → 买 → 回 home
  ├─ 公会         → gong_hui → 买 → 回 home
  └─ 送花         → flower   → 送 → 回 home
所有入口处理完 → finish
```

入口之间没有固定顺序；邮件/活动/丹青阁/商店看红点，煮酒/战役/公会/送花
是日常流程没有红点也做。好友的红点只代表加好友，不参与判断。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gamebot.flow import EngineOptions, Node, Transition
from gamebot.scenario_spec import ScenarioSpec
from games import on_page

from .bindings import BINDINGS
from .pages import FEATURE_TREE
from .steps import (
    buy_shop_then_finish,
    claim_gallery_then_finish,
    draw_then_gallery,
    finish_daily,
    gong_hui_step,
    mail_claim_then_activity,
    send_flower_finish,
    visit_next_entry,
    zhan_yi_step,
    zhu_jiu_step,
)

if TYPE_CHECKING:
    from gamebot.context import RunContext

__all__ = ["SCENARIO"]


def _daily_done(ctx: RunContext) -> bool:
    """hub 把所有入口都处理完了。"""
    return bool(ctx.blackboard.get("daily.done"))


SCENARIO = ScenarioSpec(
    name="daily",
    initial="root",
    tree=FEATURE_TREE,
    bindings=BINDINGS,
    nodes=(
        Node(
            "root",
            steps=[visit_next_entry],
            description="首页 hub：按红点挑下一个入口",
            transitions=[
                Transition("finish", _daily_done, 30, "所有入口处理完"),
                Transition("mail", on_page("daily/mail"), 10, "邮件有红点"),
                Transition("activity", on_page("daily/activity"), 10, "活动有红点"),
                Transition("gallery", on_page("daily/gallery"), 10, "丹青阁有红点"),
                Transition("shop", on_page("daily/shop"), 10, "商店有红点"),
                Transition("zhu_jiu", on_page("daily/zhu_jiu"), 10, "煮酒日常"),
                Transition("zhan_yi", on_page("daily/zhan_yi"), 10, "战役日常"),
                Transition("gong_hui", on_page("daily/gong_hui"), 10, "公会日常"),
                Transition("flower", on_page("daily/flower"), 10, "送花日常"),
            ],
        ),
        Node(
            "mail",
            steps=[mail_claim_then_activity],
            description="邮箱：一键领取 → 回首页",
            transitions=[
                Transition("root", on_page("daily/root"), 10, "领完回首页"),
            ],
        ),
        Node(
            "activity",
            steps=[draw_then_gallery],
            description="活动：抽两张 → 军需月令 → 回首页",
            transitions=[
                Transition("root", on_page("daily/root"), 10, "领完回首页"),
            ],
        ),
        Node(
            "gallery",
            steps=[claim_gallery_then_finish],
            description="丹青阁：每日礼包 → 回首页",
            transitions=[
                Transition("root", on_page("daily/root"), 10, "领完回首页"),
            ],
        ),
        Node(
            "shop",
            steps=[buy_shop_then_finish],
            description="商店：买完 → 回首页",
            transitions=[
                Transition("root", on_page("daily/root"), 10, "买完回首页"),
            ],
        ),
        Node(
            "zhu_jiu",
            steps=[zhu_jiu_step],
            description="煮酒：青梅商店买一个 → 回首页",
            transitions=[
                Transition("root", on_page("daily/root"), 10, "买完回首页"),
            ],
        ),
        Node(
            "zhan_yi",
            steps=[zhan_yi_step],
            description="战役：战役商店买一个 → 回首页",
            transitions=[
                Transition("root", on_page("daily/root"), 10, "买完回首页"),
            ],
        ),
        Node(
            "gong_hui",
            steps=[gong_hui_step],
            description="公会：商店买一个 → 回首页",
            transitions=[
                Transition("root", on_page("daily/root"), 10, "买完回首页"),
            ],
        ),
        Node(
            "flower",
            steps=[send_flower_finish],
            description="好友送花：送礼 → 油菜花 → x100 → 回首页",
            transitions=[
                Transition("root", on_page("daily/root"), 10, "送完回首页"),
            ],
        ),
        Node(
            "finish",
            steps=[finish_daily],
            description="收尾：清 hub 状态，末梢结束",
        ),
    ),
    options=EngineOptions(
        tick_interval=0.4,
        require_confirmed=True,
        max_runtime=300.0,
    ),
)
