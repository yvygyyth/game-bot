"""业务层 —— 具体游戏的脚本。

和 ``src/gamebot/`` 的区别：**框架不认识任何具体游戏，业务层只认游戏与脚本。**

```
games/
├── __init__.py            业务层入口（注册表）
├── _spec.py               脚本注册表：读各游戏 scripts/__all__
├── _templates.py          模板审计（声明 vs 磁盘）
└── <游戏>/
    ├── __init__.py        游戏包：导出脚本清单 + 跨脚本纯函数
    ├── utils/             跨脚本纯函数（如 go_back）
    └── scripts/
        ├── __init__.py    ★ 按功能名导出各 SPEC
        └── <功能>/
            ├── __init__.py    ★ SPEC = FeatureSpec(...)（含 window_title）
            ├── pages.py / graph.py / steps/ / templates/
            └── ...
```

## 唯一需要记住的规则

功能包导出一个 ``SPEC``，再在 ``scripts/__init__.py`` 里按功能名转出去：

```python
# games/<游戏>/scripts/<功能>/__init__.py
SPEC = FeatureSpec(
    name="<游戏>/<功能>",
    title="给人看的名字",
    slug="<功能>",
    window_title="找窗用的标题",
    scenario=SCENARIO,
    form=FORM,  # 可选
)
```

注册表、CLI、UI 都只认这份声明；装配走 ``bootstrap_from_spec``，
不再经过 ``AppConfig`` / YAML。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让业务层在"框架还没安装"时也能直接跑。
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
    within_page,
)

__all__ = [
    "ScriptSpec",
    "discovery_errors",
    "get_script",
    "list_scripts",
    "on_page",
    "within_page",
]
