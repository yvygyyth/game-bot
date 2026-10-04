"""把 YAML 解析成 :class:`Scenario`（页面树 + 流程图 + 参数）。

目标还是那一句：**改流程不用改 Python**。

```yaml
name: example
initial: home                # 流程图的起始节点
tick_interval: 0.3
max_runtime: 3600
on_unknown: wait             # wait | reload_tick | recovery | stop
recovery_node: home
unknown_grace: 1.5
stop_pages: [closed]
require_confirmed: true

# ---------- 页面树：我在哪 ----------
pages:
  home:
    name: 首页
    queries:
      - {type: ImageQuery, template: home/logo.png}
    children:
      qianli:
        queries: [{type: ImageQuery, template: qianli/entry.png}]
        children:
          battle:
            roi: [1180, 620, 680, 500]     # 相对父页面
            queries: [{type: ImageQuery, template: battle/skillbar.png}]
            children:
              result: {queries: [{type: ImageQuery, template: result/victory.png}]}
  network_error:                            # 顶层 = 全局叠加层
    kind: overlay
    priority: 100
    queries: [{type: ImageQuery, template: common/network_error.png}]

# ---------- 流程图：做什么 ----------
nodes:
  home:
    page: home                              # 声明期望页面（不符就不动作）
    steps:
      - {type: ClickImageStep, template: qianli/entry.png}
  battle:
    page: qianli/battle
    steps:
      - {type: FunctionStep, func: my_scripts.attack}
    cooldown: 0.5
  result:
    page: qianli/battle/result
    steps: [{type: ClickImageStep, template: result/confirm.png}]
    on_enter: [{type: WaitStep, seconds: 0.5}]

edges:
  - {source: battle, target: result, priority: 30,
     condition: {type: ImageQuery, template: result/victory.png}, label: 战斗结束}
  - {source: result, target: home, priority: 20}
  - {source: home, target: battle, priority: 10}
  - {source: home, target: closed, priority: 5, kind: terminal}
```

## 还差两块拼图

``parse_scenario`` 需要把配置里的字典还原成对象，而这两件事还没做：

* ``atomic.query.query_from_dict`` —— ``{type: ImageQuery, ...}`` -> Query。
  它有注册表（``query_registry()``）撑着，实现是查表 + 递归构造嵌套查询；
* ``execution.step.step_from_dict`` —— ``{type: ClickImageStep, ...}`` -> Step。
  同样有 ``step_registry()``，但还要处理 ``policy`` 子字典。

这两块补上之后 ``gamebot check`` 就能真正校验配置了（在那之前，
``tests/test_config.py`` 里的样例检查是直接 ``yaml.safe_load`` 做的）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..exceptions import ConfigError
from ..state.page import PageTree
from .graph import Graph
from .scenario import EngineOptions, Scenario

__all__ = [
    "load_scenario",
    "parse_graph",
    "parse_options",
    "parse_pages",
    "parse_scenario",
]


def load_scenario(path: str | Path) -> Scenario:
    """从 YAML 文件加载脚本定义。

    :raises ConfigError: 文件不存在 / YAML 语法错误 / 顶层不是 mapping。
    :raises StateError / FlowError: 定义自相矛盾（由 ``Scenario.validate`` 抛出）。
    """
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"脚本文件不存在: {file}")

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("缺少 PyYAML，请执行: uv sync") from exc

    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"脚本文件 YAML 解析失败: {file} — {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"脚本文件顶层必须是映射(mapping): {file}")

    scenario = parse_scenario(data)
    scenario.validate()
    return scenario


def parse_scenario(data: dict[str, Any]) -> Scenario:
    """把字典解析成 :class:`Scenario`。

    :raises ConfigError: ``name`` 之类的基础字段类型不对。
    """
    raise NotImplementedError(
        "待实现: parse_pages(data['pages']) + parse_graph(data) + parse_options(data) "
        "-> Scenario；依赖 atomic.query.query_from_dict 与 execution.step.step_from_dict"
    )


def parse_pages(data: dict[str, Any]) -> PageTree:
    """解析嵌套的页面定义（``id`` 由嵌套位置推导成路径形式）。

    ``kind`` 缺省是普通页面（替换式）；``kind: overlay`` 才是叠加层。
    """
    raise NotImplementedError("待实现：委托给 PageTree.from_nested(data)")


def parse_graph(data: dict[str, Any]) -> Graph:
    """解析 ``nodes`` / ``edges``。

    ``edges[].condition`` 要么是 ``{type: ..., ...}``（走 query_from_dict），
    要么是 ``{func: 模块路径}``（导入一个 Python 函数，逃生舱）。
    """
    raise NotImplementedError(
        "待实现: nodes -> Node(steps=step_from_dict(...))；edges -> Edge(condition=...)"
    )


def parse_options(data: dict[str, Any]) -> EngineOptions:
    """解析顶层运行参数。

    只认已知字段，拼错的键直接报错 —— 静默忽略拼错的配置是这类 bug 的头号来源。
    """
    raise NotImplementedError(
        "待实现：按 EngineOptions 的字段白名单取顶层键，"
        "on_unknown 字符串 -> UnknownPolicy，未知键抛 ConfigError"
    )


def _known_option_keys() -> tuple[str, ...]:
    """``EngineOptions`` 的字段名（供 parse_options 做白名单）。"""
    from dataclasses import fields

    return tuple(f.name for f in fields(EngineOptions))
