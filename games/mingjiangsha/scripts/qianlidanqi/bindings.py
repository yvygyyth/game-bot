"""千里单骑 —— 关联表：状态末梢 ↔ 流程节点。"""

from __future__ import annotations

from gamebot.flow import Binding, NodeBindings

__all__ = ["BINDINGS"]

BINDINGS = NodeBindings(
    pairs=(
        Binding("root", "root"),
        Binding("campaign", "campaign"),
        Binding("open_pick", "qianli/select1"),
        Binding("pick_general", "qianli/select2"),
        Binding("leave_pick", "qianli/select3"),
        Binding("start_run", "qianli/select4"),
        Binding("continue_run", "qianli/select5"),
        # ---- 局内 ----
        Binding("skill_panel", "qianli/skill_panel"),
        Binding("map", "qianli/map"),
        Binding("pre_battle", "qianli/pre_battle"),
        Binding("fight", "qianli/fight"),
        Binding("gift", "qianli/gift"),
        Binding("gift_kind", "qianli/gift_kind"),
        Binding("shop_ba_qing", "qianli/shop/ba_qing"),
        Binding("rest", "qianli/rest"),
        Binding("pocket_choice", "qianli/pocket/choice"),
        Binding("pocket_confirm", "qianli/pocket/confirm"),
        Binding("event_intro", "qianli/event/intro"),
        Binding("event_choice", "qianli/event/choice"),
        Binding("shi_chang", "qianli/event/shi_chang"),
        Binding("end", "qianli/end"),
        Binding("end2", "qianli/end2"),
    )
)
