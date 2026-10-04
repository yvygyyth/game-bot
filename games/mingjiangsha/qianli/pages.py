"""千里单骑 —— 本功能的页面（状态对象）。

挂在游戏级的 ``home`` 下面，所以 id 是路径形式：

```
home                                    游戏级：首页
└── home/qianli                         本功能：千里单骑主页面
    └── home/qianli/battle              本功能：战斗中
        └── home/qianli/battle/result   本功能：战斗结算
```

## roi 相对父页面

``battle`` 声明了 ``roi``，它的所有子页面和子页面上的查询都会在那块区域内进行。
这既快（少算一大片像素）又准（不会被别处的相似图标骗到）。

## min_stable_frames

``result`` 设了 2：结算画面有弹出动画，第一帧可能只出来一半。
要求连续 2 帧命中，能挡掉这种"闪现"。

## 模板名

相对**本功能的模板根** ``games/mingjiangsha/qianli/templates/``。
公共模板（断线弹窗之类）不在这里写 —— 它们在游戏级页面上。
"""

from __future__ import annotations

from gamebot.atomic.query import ImageQuery, OrQuery
from gamebot.state import Page
from gamebot.types import Region

#: 战斗页面的观察区域（相对父页面）。只看右下角技能栏，不用整屏匹配。
BATTLE_ROI = Region(680, 400, 600, 320)

FEATURE_PAGES: list[tuple[Page, str | None]] = [
    (
        Page(
            "home/qianli",
            name="千里单骑",
            queries=(ImageQuery("page_header.png", confidence=0.9),),
            description="千里单骑主页面：有关卡列表和「开始挑战」按钮",
        ),
        "home",
    ),
    (
        Page(
            "home/qianli/battle",
            name="战斗中",
            roi=BATTLE_ROI,
            queries=(ImageQuery("battle/skill_bar.png", confidence=0.9),),
            description="战斗界面：只看右下角技能栏就能确认",
        ),
        "home/qianli",
    ),
    (
        Page(
            "home/qianli/battle/result",
            name="战斗结算",
            min_stable_frames=2,  # 结算面板有弹出动画，要求连续 2 帧才算
            queries=(
                OrQuery(
                    (
                        ImageQuery("result/victory.png", confidence=0.9),
                        ImageQuery("result/defeat.png", confidence=0.9),
                    ),
                    short_circuit=True,
                ),
            ),
            description="胜利或失败都进这里，区别只在文案",
        ),
        "home/qianli/battle",
    ),
]
