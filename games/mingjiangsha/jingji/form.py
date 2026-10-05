"""竞技场 —— 动态表单声明。

## 为什么这些值走表单而不是写死在代码里

它们全都是"**同一次跑和下一次跑可以不一样**"的东西：

* 刷几次、点完等多久 —— 网络和机器快慢不同，硬编码的时间不是太短就是太长；
* 按钮阈值 —— 换分辨率、游戏改版、开特效都会让它偏；
* 严格模式 —— 调脚本时想看"认不出来就停"，跑起来时想让它尽量往下走。

写死在代码里的代价是：**每调一次都要改代码、重启脚本、重跑**。而它们在
运行期就能定，没理由不让用户定。

## 和步骤的关系（关键）

步骤是在 ``build_scenario()`` 里构造的**静态对象** —— 那次调用**拿不到**
表单里的值。所以这些值不进步骤的构造函数，而是走**运行参数**：
点「开始」时 ``FORM.fill(表单值)`` 凑齐一份完整参数，交给 ``ctx.params``，
步骤在 ``run()`` 里用 ``ctx.param("jingji.settle")`` 现读：

    FORM 声明 → 用户填 → 点开始 → FORM.fill() → ctx.params → 步骤 run() 时现读

于是"这次用什么值"永远在运行时决定，步骤对象保持无状态、可复用。

**注意步骤里那个 ``ctx.param`` 没有兜底默认值** —— 因为 ``fill()`` 保证
每个声明过的字段都有值。默认值只有一份出处（就是下面的 ``FORM``），
不会出现"声明写 1.0、步骤里写 0.8"这种两处不一致。
"""

from __future__ import annotations

from gamebot.params import FieldKind, FormSpec, ParamField

FORM = FormSpec(
    title="竞技场参数",
    fields=(
        ParamField(
            "jingji.rounds",
            FieldKind.INT,
            1,
            label="刷几轮",
            help="走完一遍「进入竞技场 → 建队 → 匹配」算一轮。0 = 一直刷",
            min=0,
            max=99,
        ),
        ParamField(
            "jingji.settle",
            FieldKind.FLOAT,
            1.0,
            label="点完等多久（秒）",
            help="点一个按钮之后给界面反应的时间。网络慢/机器卡就调大",
            min=0.0,
            max=10.0,
            step=0.1,
        ),
        ParamField(
            "jingji.confidence",
            FieldKind.FLOAT,
            0.85,
            label="按钮阈值",
            help=(
                "识别按钮的最低分数。实测自己的图上 1.000、按钮之间最高 0.690，"
                "所以 0.85 留了很大余量；误认别的按钮就调高，认不出来就调低"
            ),
            min=0.5,
            max=1.0,
            step=0.01,
        ),
        ParamField(
            "jingji.strict",
            FieldKind.BOOL,
            False,
            label="严格模式",
            help="认不出页面时立刻停下并报错，而不是等宽容期过去。调脚本时打开",
        ),
    ),
)
