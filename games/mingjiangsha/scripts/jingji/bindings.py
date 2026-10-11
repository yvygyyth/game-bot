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
| ``team`` | ``jj/before_create`` | 点「创建队伍」 |
| ``team`` | ``jj/after_create`` | 点「添加伙伴」 |
| ``match`` | ``jj/after_add`` | 点「开始匹配」（+ 提示框善后） |
| ``select`` | ``select/idle`` | 点第 1 张武将卡 |
| ``select`` | ``select/picked`` | 点「确定」 |
| ``fight`` | ``fight/hand`` | 取消换牌 → 麻花结 → 投降 → 确认 |
| ``settle`` | ``fight/done`` | 结算三步 + 记一局 |

## 为什么一个流程节点能关联多个状态

``team`` 关联两个状态、``match`` 一个、``select`` 两个 —— 它们**共用同一个步骤**：

* ``team``：创建队伍和添加伙伴都是"点那个按钮"，只是按钮文字不同。
  一个函数里写"点当前状态那个按钮"比写两个节点更省事，而且不会漏掉其中一个；
* ``select``：点卡和点确定是两个**不同**的步骤，所以它们各自是独立的
  ``Node``（同名 ``select`` 不行），见 :mod:`.graph`。

⚠️ **一个节点只能关联一个状态**（``NodeBindings`` 会在装配期拦下写两个的）——
不然"进入这个节点后跑哪个状态的定位代码"就不确定了。所以上面表格里
``team`` 出现两次是**两条关联**（两个不同节点），不是一条关联对应两个状态。

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
        Binding("pick_general", "select/idle"),
        Binding("confirm_general", "select/picked"),
        Binding("fight", "fight/hand"),
        Binding("settle", "fight/done"),
        # 终态也要有节点认领 —— 否则重定位到它就无处可去。
        # "进了就结束"不等于"不需要节点"。
        Binding("finish", "over"),
    )
)
"""这个功能的关联表。

**节点 id 和状态 id 刻意不同名**（``create_team`` vs ``jj/before_create``）：
状态 id 说的是"界面上看到什么"，节点 id 说的是"要做什么"，两件事本来就不一样。
（竞技场那三个状态在同一个界面上，硬要同名也做不到。）"""
