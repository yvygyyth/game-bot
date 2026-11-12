"""名将杀 —— **游戏级公共按钮花纹**。

一个文件夹 = 一种花纹；同一花纹的不同**文字/尺寸/底色版本**都放进去：

```
templates/gold_glow/    金色发光
templates/gold_frame/   金色花纹边框
templates/cyan_glow/    青色发光
```

调用方只用对应家族的方法，**不用关心按钮位置、尺寸、文案**：

```python
from games.mingjiangsha.utils import click_gold_frame

click_gold_frame(ctx)   # 金色花纹大按钮（含「下一步」）
```

加一种文字/尺寸版本不用改代码：把截图裁下来丢进对应文件夹即可。
查找顺序：功能级模板优先，这里兜底。
"""

from __future__ import annotations

__all__ = [
    "BUTTON_CYAN_GLOW",
    "BUTTON_FOLDERS",
    "BUTTON_GOLD_FRAME",
    "BUTTON_GOLD_GLOW",
]

#: 金色发光按钮：创建队伍 / 添加伙伴 / 确定…
BUTTON_GOLD_GLOW = "gold_glow"

#: 金色花纹边框的大按钮：确定 / 开始匹配 / 开始对局…
BUTTON_GOLD_FRAME = "gold_frame"

#: 青色发光按钮：取消
BUTTON_CYAN_GLOW = "cyan_glow"

#: 全部花纹目录。**只作参考**，新加文件夹不必登记到这里才能用。
BUTTON_FOLDERS = (
    BUTTON_GOLD_GLOW,
    BUTTON_GOLD_FRAME,
    BUTTON_CYAN_GLOW,
)
