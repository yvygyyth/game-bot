"""千里单骑（名将杀）—— 进战役 → 选将 → 开始挑战。

## 读代码的顺序

| 想改什么 | 读 |
|---|---|
| 脚本叫什么、表单有哪些 | **本文件** |
| 每个状态靠什么认出来（模板 + roi + 阈值） | :mod:`.pages` |
| 状态和流程节点怎么对上 | :mod:`.bindings` |
| 有哪些节点、什么条件换节点 | :mod:`.graph` |
| 每个节点具体做什么 | :mod:`.steps` |
| 模板路径 | :mod:`.templates` |

## 流程一句话

首页点「战役」→ 点「千里单骑」→ 点「选择武将」→ 搜索入参武将并点第一个结果
→ Esc 退回主界面 → 点「开始挑战」→ 进入局内。

局内（`qianli/flow`）先做**终态占位**：一进局内画面就停，后面的局内流程再补。
"""

from __future__ import annotations

from gamebot.feature import FeatureSpec

from .form import FORM
from .graph import SCENARIO

#: 这个脚本的**唯一导出**。``scripts/__init__.py`` 再按功能名转出去。
SPEC = FeatureSpec(
    name="mingjiangsha/qianlidanqi",
    title="千里单骑",
    slug="qianlidanqi",
    window_title="名将杀",
    description="千里单骑：进战役 → 选将 → 开始挑战（局内待实现）",
    scenario=SCENARIO,
    form=FORM,
    # 游戏固定 2560x1369 客户区，模板按它裁 → 关掉多尺度，只跑 1.0。
    use_pyramid=False,
)

__all__ = ["SPEC"]
