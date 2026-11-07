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
    buy_shop_then_finish,
    claim_gallery_then_finish,
    draw_then_gallery,
    finish_daily,
    gong_hui_step,
    mail_claim_then_activity,
    open_mail,
    send_flower_finish,
    zhan_yi_step,
    zhu_jiu_step,
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
                Transition("activity", on_page("daily/activity"), 5, "邮件已领，直接活动"),
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
                Transition("shop", on_page("daily/shop"), 10, "打开商店"),
            ],
        ),
        Node(
            "shop",
            steps=[buy_shop_then_finish],
            description="商店：黄金免费兵力 → 铜钱灵犀盒 → 金兰名将册 → 开煮酒",
            transitions=[
                Transition("zhu_jiu", on_page("daily/zhu_jiu"), 10, "进煮酒"),
            ],
        ),
        Node(
            "zhu_jiu",
            steps=[zhu_jiu_step],
            description="煮酒：青梅商店买一个 → 开战役",
            transitions=[
                Transition("zhan_yi", on_page("daily/zhan_yi"), 10, "进战役"),
            ],
        ),
        Node(
            "zhan_yi",
            steps=[zhan_yi_step],
            description="战役：战役商店买一个 → 开公会",
            transitions=[
                Transition("gong_hui", on_page("daily/gong_hui"), 10, "进公会"),
            ],
        ),
        Node(
            "gong_hui",
            steps=[gong_hui_step],
            description="公会：商店买一个 → 结束",
            transitions=[
                Transition("flower", on_page("daily/flower"), 10, "进好友送花"),
            ],
        ),
        Node(
            "flower",
            steps=[send_flower_finish],
            description="好友送花：送礼 → 油菜花 → x100 → 好友",
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
