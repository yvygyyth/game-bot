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
        # 局内先做终态占位：进入 flow 画面就停。
        Binding("flow", "qianli/flow"),
    )
)
