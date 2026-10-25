"""名将杀 —— **游戏级公共模板**（多个脚本共用）。

放"换个脚本还是那张图"的东西。查找顺序是**功能级优先、这里兜底**
（见 ``bootstrap.build_matcher`` 的 ``fallback_dirs``），所以功能级可以放同名图覆盖。

## 按钮：**一个文件夹 = 一种按钮**

```
templates/<家族>/*.png     ← 这个家族的**所有文字版本**都放进来
```

同一家族里，不同文字版本（创建队伍 / 添加伙伴 / 确定…）**同一个位置只会出现一个**，
所以"把家族里每张都试一遍，谁命中就点谁"不会歧义。调用方只关心**哪种按钮**：

```python
from games.mingjiangsha.utils import click_button
from games.mingjiangsha.templates import BUTTON_SHADOW_CONFIRM

click_button(ctx, BUTTON_SHADOW_CONFIRM)      # 金色确认按钮，具体是哪句字无所谓
```

加一种文字版本**不用改代码**：把这个按钮的截图裁下来丢进对应文件夹即可。
加一种**新按钮**：新建一个文件夹，调用时把文件夹名传进去。

现有家族见 :data:`BUTTON_FOLDERS`。
"""

from __future__ import annotations

__all__ = [
    "BUTTON_FOLDERS",
    "BUTTON_PATTERN_CONFIRM",
    "BUTTON_QJ_NEXT",
    "BUTTON_SHADOW_CANCEL",
    "BUTTON_SHADOW_CONFIRM",
]

# ---- 按钮家族（相对 games/<游戏>/templates/ 的目录名）----

#: 金色发光按钮：创建队伍 / 添加伙伴 / 确定…（最常用的一种"确认"）
BUTTON_SHADOW_CONFIRM = "shadowConfirm"

#: 金色花纹边框的大按钮：确定（弹窗里那种更花的）
BUTTON_PATTERN_CONFIRM = "patternConfirm"

#: 青色发光按钮：取消
BUTTON_SHADOW_CANCEL = "shadowCancel"

#: 蓝底金框按钮：下一步（千里单骑/结算）
BUTTON_QJ_NEXT = "QJ"

#: 全部按钮家族目录。**只作参考**，新加文件夹不必登记到这里才能用。
BUTTON_FOLDERS = (
    BUTTON_SHADOW_CONFIRM,
    BUTTON_PATTERN_CONFIRM,
    BUTTON_SHADOW_CANCEL,
    BUTTON_QJ_NEXT,
)
