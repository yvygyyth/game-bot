"""关联表 —— **状态末梢 ↔ 流程节点**。

这是这个功能的第三个产物，和前两个并列：

| 文件 | 是什么 |
|---|---|
| :mod:`.pages` | 状态树 —— 靠画面认"我在哪" |
| :mod:`.graph` | 流程图 —— "该做什么" |
| **本文件** | 关联表 —— 两者怎么对上 |

**关联不写在任何一边。** 以前它隐含在 ``graph.py`` 的 ``Node(page=...)`` 里 ——
那是"流程图顺手带了状态信息"，两边边界就模糊了；而且想单看"谁对应谁"，
得把流程图从头翻一遍。

## 这里的四条对应

| 流程节点 | 状态末梢 |
|---|---|
| ``home`` | ``home/lobby`` |
| ``jingji/before_create`` | ``home/jingji/before_create`` |
| ``jingji/after_create`` | ``home/jingji/after_create`` |
| ``jingji/after_add`` | ``home/jingji/after_add`` |

节点 id 和状态 id 的**尾段同名**是刻意的（``jingji/before_create`` 对
``home/jingji/before_create``）：一眼能看出对应关系，改错也看得出。但这不是
框架要求 —— 对应关系只认这张表。

## 为什么 `home` 对的是 `home/lobby` 而不是 `home`

``home`` 是**分类节点**（`kind: group`）：它自己不记录信息、不参与匹配，
只提供 ROI 继承和组织结构。把它关联给流程节点，那个节点就永远不会被执行 ——
定位结果里根本不会出现分类节点。

---
"""

from __future__ import annotations

from gamebot.flow import Binding, NodeBindings

__all__ = ["BINDINGS"]

#: 这个功能的关联表。
BINDINGS = NodeBindings(
    pairs=(
        Binding("home", "home/lobby"),
        Binding("jingji/before_create", "home/jingji/before_create"),
        Binding("jingji/after_create", "home/jingji/after_create"),
        Binding("jingji/after_add", "home/jingji/after_add"),
    )
)
