"""竞技场 —— 运行参数表单。

## 只有一个参数：刷几局

玩家要求："脚本入参就一个循环次数"。

## 为什么用 ``INT`` 而不是文本

``FieldKind.INT`` 在界面上渲染成**数字控件**（带上下限和步进），填错会被拦住。
用文本的话得在步骤里自己 ``int()`` 加判错 —— 那是把校验从声明挪进了逻辑里。

## 这个值怎么到步骤手里

    声明（本文件） → 用户填 → 点开始 → FORM.fill() → ctx.params → 步骤里 ctx.param 现读

步骤拿不到构造期的表单值（它是静态对象），所以一律**运行期现读**。
`fill()` 保证每个声明过的字段都有值，所以步骤里**不写兜底默认值** ——
默认值只有这一处出处，不会出现"声明写 5、步骤里写 3"的不一致。

## 为什么循环次数**不**做成参数、而是走黑板

"刷几局"是**输入**（进去之前定好的），所以在这儿。
"已经刷了几局"是**跑出来的状态**，写在 ``ctx.blackboard`` 里（见
:func:`games.mingjiangsha.jingji.steps.finish_round.finish_round`）。
两件事都在 ``ctx`` 上，但不能混 —— 判断方法："用户还没点开始时它就有值了吗？"
"""

from __future__ import annotations

from gamebot.params import FieldKind, FormSpec, ParamField

__all__ = ["FORM", "ROUNDS_PARAM"]

#: "刷几局"的参数名。
ROUNDS_PARAM = "jingji.rounds"

FORM = FormSpec(
    title="竞技场参数",
    fields=(
        ParamField(
            ROUNDS_PARAM,
            FieldKind.INT,
            5,
            label="刷几局",
            help="打完这么多局就停。一局 = 从「开始匹配」到结算页点确认。",
            min=1,
            max=999,
            step=1,
        ),
    ),
)
"""表单声明。

参数名用点分层级（``jingji.rounds``）—— 参数是**跨功能共享的一个命名空间**
（都落在 ``ctx.params`` 里），点分层级能避免和别的脚本撞名。
"""
