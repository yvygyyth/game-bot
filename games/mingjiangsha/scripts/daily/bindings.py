"""每日领奖 —— 关联表。"""

from __future__ import annotations

from gamebot.flow import Binding, NodeBindings

__all__ = ["BINDINGS"]

BINDINGS = NodeBindings(
    pairs=(
        # 首页被多个节点认领：root 是主节点，finish 只从边进入
        Binding("root", "daily/root", priority=10),
        Binding("finish", "daily/root", priority=0),
        Binding("mail", "daily/mail"),
        Binding("activity", "daily/activity"),
        Binding("gallery", "daily/gallery"),
        Binding("shop", "daily/shop"),
        Binding("zhu_jiu", "daily/zhu_jiu"),
        Binding("zhan_yi", "daily/zhan_yi"),
        Binding("gong_hui", "daily/gong_hui"),
        Binding("flower", "daily/flower"),
    )
)
