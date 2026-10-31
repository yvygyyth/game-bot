"""竞技场 —— 关联表：**状态末梢 ↔ 流程节点**。

这是这个功能的第三个产物，和前两个并列：

| 文件 | 是什么 |
|---|---|
| :mod:`.pages` | 状态树 —— 靠画面认"我在哪" |
| :mod:`.graph` | 流程图 —— "该做什么" |
| **本文件** | 关联表 —— 两者怎么对上 |

## 这里的对应

| 流程节点 | 状态末梢 | 干什么 |
|---|---|---|
| ``lobby`` | ``lobby`` | 点首页的竞技入口 |
| ``create_team`` | ``jj/before_create`` | 点「创建队伍」 |
| ``add_pet`` | ``jj/after_create`` | 点「添加伙伴」 |
| ``match`` | ``jj/after_add`` | 点「开始匹配」 |
| ``tip_check`` | ``tip/unchecked`` | 勾「本次登录不再提示」 |
| ``tip_confirm`` | ``tip/checked`` | 点「确定」关掉提示框 |
| ``pick_general`` | ``select`` | 点第 1 张武将卡 + 「确定」 |
| ``fight`` | ``fight/hand`` | 取消换牌 → 麻花结 → 投降 → 确认 |
| ``victory`` | ``fight/victory`` | 点空白 → 下一步 → 确认（记一局） |
| ``finish`` | ``over`` | 刷够局数的终态 |

## 一个流程节点只关联**一个**状态

``NodeBindings`` 在装配期就会拦下"一个节点写两个状态"—— 不然"进入这个节点后
跑哪个状态的定位代码"就不确定了。提示框/选将/战斗的每一步都是**独立节点**，
所以每一步都有自己的状态守卫：位置不对时那个步骤根本不会被调用。

## 三条不变式

1. 流程节点**不一定**有状态（纯逻辑节点）—— 这里每个都有；
2. 状态末梢**一定**有节点认领 —— 少一个就在装配期报错；
3. 一个流程节点**至多**关联一个状态。
"""

from __future__ import annotations

from gamebot.flow import Binding, NodeBindings

__all__ = ["BINDINGS"]

BINDINGS = NodeBindings(
    pairs=(
        Binding("lobby", "lobby"),
        Binding("create_team", "jj/before_create"),
        Binding("add_pet", "jj/after_create"),
        Binding("match", "jj/after_add"),
        Binding("tip_check", "tip/unchecked"),
        Binding("tip_confirm", "tip/checked"),
        Binding("pick_general", "select"),
        Binding("fight", "fight/hand"),
        Binding("victory", "fight/victory"),
        # 终态也要有节点认领 —— 否则重定位到它就无处可去。
        # "进了就结束"不等于"不需要节点"。
        Binding("finish", "over"),
    )
)
"""这个功能的关联表。

**节点 id 和状态 id 刻意不同名**（``create_team`` vs ``jj/before_create``）：
状态 id 说的是"界面上看到什么"，节点 id 说的是"要做什么"，两件事本来就不一样。
（竞技场那三个状态在同一个界面上，硬要同名也做不到。）"""
