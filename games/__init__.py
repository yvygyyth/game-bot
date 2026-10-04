"""业务层 —— 具体游戏的脚本。

和 ``src/gamebot/`` 的区别：**框架不认识任何具体游戏，业务层只认一个游戏。**

```
games/
├── __init__.py            业务层入口（注册表）
├── _spec.py               脚本注册表：自动发现"有哪些脚本"
├── __main__.py            python -m games list / check / describe
└── <游戏>/                 一级分类：一个游戏一个目录
    ├── game.py            游戏级定义：窗口、分辨率、公共页面、公共模板根
    ├── pages.py           游戏级公共页面（首页、断线弹窗……）
    ├── shortcuts.py       游戏级快捷方法（回主界面、关弹窗……）
    ├── templates/         游戏级公共模板
    └── <功能>/             二级分类：一个脚本功能一个目录
        ├── __init__.py    ★ 必须暴露 build_config() / build_scenario()
        ├── pages.py       该功能的状态对象（页面树节点）
        ├── graph.py       该功能的流程对象（节点 + 边）
        ├── steps.py       该功能专用步骤
        ├── shortcuts.py   该功能专用快捷方法
        └── templates/     该功能的图片资源
```

## 为什么一级按游戏、二级按功能

* **游戏级**放"这个游戏所有脚本都要用"的东西：窗口标题、锁定分辨率、
  公共页面（首页、断线重连）、公共模板、公共快捷方法。
  改一次全体受益，不需要在每个脚本里重复。
* **功能级**放"只跟这个玩法有关"的东西：页面、流程、专用图、专用步骤。
  一个功能改坏了不会影响别的功能。

## 唯一需要记住的规则

功能包的 ``__init__.py`` 暴露两个函数，注册表就能自动发现它：

```python
def build_config() -> AppConfig: ...     # 这个脚本怎么跑（窗口、分辨率、模板根）
def build_scenario() -> Scenario: ...    # 这个脚本做什么（页面树 + 流程图 + 参数）
```

（可选再给 ``TITLE`` / ``DESCRIPTION`` 字符串，``python -m games list`` 会显示。）

加了这两个函数，runner / GUI / CI 就能统一列出、校验、运行所有脚本，
不需要维护一张手写的清单 —— 也不会出现"新加了脚本但忘了登记"。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让业务层在"框架还没安装"时也能直接跑（和 main.py 一个思路）。
# 装了之后这行是无害的：src 已经在 sys.path 里了。
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:  # pragma: no cover - 取决于怎么启动
    sys.path.insert(0, str(_SRC))

from ._spec import (  # noqa: E402  （必须先处理 sys.path 再导入 gamebot）
    ScriptSpec,
    discovery_errors,
    get_script,
    list_scripts,
    on_page,
)

__all__ = [
    "ScriptSpec",
    "discovery_errors",
    "get_script",
    "list_scripts",
    "on_page",
]
