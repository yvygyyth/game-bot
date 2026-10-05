"""沙盒测试游戏 —— 框架的验证床。

它不是"某个真实游戏的脚本"，而是**用这个框架写出来的一个最小但完整的脚本**，
外加一个合成屏幕。用途有三个：

1. **验证视觉链路**：模板匹配、ROI 累加、坐标换算有没有错。
   合成屏幕让"正确答案"是构造出来的，不需要人工录图；
2. **当写脚本的参考样板**：页面树怎么写、边怎么写、自己的步骤怎么写，
   这里都有一份能跑的；
3. **当回归测试**：框架改了之后跑一遍 ``python -m games selftest testgame``，
   八项检查全过就说明没把视觉链路改坏。

## 为什么不录真截图

真截图有几个绕不开的问题：体积大、改一次游戏 UI 全部失效、
而且"图里到底该有什么"说不清 —— 测试就成了"和上次的截图一样"，
而不是"和应该的样子一样"。合成屏幕把**应该的样子**变成代码，
于是它成了唯一的事实来源，页面树、模板、断言全都从它推出来。

## 命令行

```bash
python -m games setup   testgame     # 生成合成模板（幂等）
python -m games check   testgame     # 校验定义 + 查模板（会自动生成）
python -m games describe testgame    # 看页面树和流程图
python -m games selftest testgame    # 跑八项自检
```

后端是 ``fake``：即使引擎跑起来也不会真的动鼠标。
"""

from __future__ import annotations

from gamebot.config.schema import AppConfig
from gamebot.flow import EngineOptions, Scenario, UnknownPolicy

from .. import base_config as _game_base_config
from ..game import PROJECT_ROOT, TEMPLATES_DIR
from .graph import build_graph
from .pages import build_tree

SLUG = "sandbox"
TITLE = "沙盒测试游戏"
DESCRIPTION = "合成屏幕 + 完整脚本结构；用来验证视觉链路和当写脚本的样板"

#: 声明"check 之前可以自动帮我准备资源"。真实游戏别开：
#: prepare 可能是下载几百张图，在 check 里偷偷做会让人莫名其妙。
AUTO_PREPARE = True


def build_config() -> AppConfig:
    """沙盒配置：游戏级配置 + 本脚本自己的节奏。"""
    config = _game_base_config()
    config.name = f"testgame/{SLUG}"
    return config


def build_scenario() -> Scenario:
    """沙盒脚本：页面树 + 流程图 + 运行参数。"""
    return Scenario(
        name=SLUG,
        tree=build_tree(),
        graph=build_graph(),
        options=EngineOptions(
            tick_interval=0.1,
            max_runtime=60.0,
            on_unknown=UnknownPolicy.WAIT,
            unknown_grace=0.5,
        ),
        meta={"purpose": "框架验证床", "synthetic": True},
    )


def prepare(*, force: bool = False) -> int:
    """生成合成模板。返回新写入的文件数。幂等。"""
    from .. import scene

    return scene.generate_templates(PROJECT_ROOT / TEMPLATES_DIR, force=force)


def selftest() -> list[str]:
    """跑八项自检，返回失败说明（空 = 全过）。

    实现放在 :mod:`.checks`，而且**延迟导入** —— 那边模块级要从本包拿
    ``build_scenario``，提前导入会变成半初始化状态。
    """
    from . import checks

    return checks.run(build_config())


__all__ = [
    "AUTO_PREPARE",
    "DESCRIPTION",
    "SLUG",
    "TEMPLATES_DIR",
    "TITLE",
    "build_config",
    "build_scenario",
    "build_tree",
    "prepare",
    "selftest",
]
