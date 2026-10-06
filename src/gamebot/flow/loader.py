"""把 YAML 解析成 :class:`Scenario`（状态树 + 流程图 + 参数）。

目标还是那一句：**改流程不用改 Python**。

```yaml
name: example
initial: home                # 流程图的起始节点
tick_interval: 0.3
on_unknown: wait             # wait | reload_tick | recovery | stop
unknown_grace: 1.5
stop_pages: [closed]

# ---------- 状态树：我在哪 ----------
# 分类节点（group）只组织结构和提供 ROI 继承，自己不记录信息；
# 记录信息的只有末梢状态节点。
states:
  home:
    name: 首页
    kind: group
    children:
      lobby:      {queries: [{type: ImageQuery, template: home/logo.png}]}
      jingji:     {queries: [{type: ImageQuery, template: jingji/title.png}]}
  network_error:                            # 顶层 = 全局叠加层
    kind: overlay
    priority: 100
    queries: [{type: ImageQuery, template: common/network_error.png}]

# ---------- 流程图：做什么 ----------
# page 可以不写：不写 = 这一步不校验状态，流程直着走。
nodes:
  home:
    page: home/lobby                        # 写了 = 动前校验 + 重定位去向
    steps:
      - {type: ClickImageStep, template: jingji/entry.png}
  jingji:
    page: home/jingji
    priority: 10                            # 同状态多节点时谁是主节点
    steps: [{type: ClickImageStep, template: jingji/create_team.png}]
```

## 四个刻意的选择

1. **状态 id 由嵌套位置推导**（``home/lobby``）。改父节点的 key 会连带
   改掉整棵子树的 id，:meth:`Scenario.validate` 会立刻发现 ``nodes[].page``
   对不上 —— 早炸，而不是"跑起来什么都不做"。
2. **未知键一律报错**。静默忽略拼错的配置，表现是"这一步跑起来什么都没做"，
   要跑十分钟才撞得到一次。
3. **``queries`` / ``steps`` 的反序列化放在各自的层里**
   （``atomic.query`` / ``execution.step``），本模块只负责**拼装** ——
   这样状态层也能拿到 ``query_from_dict``，而状态层**不许** import 流程层。
4. **``pages`` 也能写**（``states`` 的旧名字）。同一个概念只该有一个名字，
   但旧配置不该因为改名就炸 —— 两个都收，日志里提示一次。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ..atomic.query import query_from_dict
from ..exceptions import ConfigError
from ..state.page import PageGroup, PageKind, PageLeaf, PageNode, PageTree
from ..types import Region
from .graph import Edge, EdgeKind, Graph, Node
from .scenario import EngineOptions, Scenario, UnknownPolicy

__all__ = [
    "load_scenario",
    "parse_graph",
    "parse_options",
    "parse_pages",
    "parse_scenario",
]

#: 顶层允许出现的键 = EngineOptions 的字段 + 这几个结构性键。
#: ``initial`` 属于流程图（起点是图的一部分），不属于运行参数。
_STRUCTURAL_KEYS = {"edges", "initial", "meta", "name", "nodes", "pages", "states"}

#: 页面/状态定义允许的字段。
#: 分类节点（`kind: group`）能写的键。**它没有识别相关的字段** ——
#: 那些是 `PageLeaf` 才有的，所以这里和 `_PAGE_KEYS` 分开列。
_GROUP_KEYS = frozenset({"priority", "roi", "name", "description", "meta"})

_PAGE_KEYS = {
    "confidence",
    "description",
    "exclude",
    "kind",
    "meta",
    "min_stable_frames",
    "name",
    "priority",
    "queries",
    "roi",
    "terminal",
    "timeout",
}

#: 节点定义允许的字段。
#:
#: **只剩这几个了** —— 节流旋钮（`cooldown` / `max_visits` / `timeout` /
#: `on_timeout`）和两段式钩子（`on_enter` / `on_exit`）都删了：
#: 节奏由 tick 间隔和状态识别负责，一个节点就是一件事。
#: `steps` 留在表里**只是为了给出那句清楚的报错**（见 `_add_node`）。
_NODE_KEYS = {
    "description",
    "meta",
    "page",
    "priority",
    "steps",
}

#: 边定义允许的字段。
_EDGE_KEYS = {
    "condition",
    "cooldown",
    "kind",
    "label",
    "max_times",
    "meta",
    "priority",
    "source",
    "target",
}


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

    :raises ConfigError: 基础字段类型不对。
    """
    if not isinstance(data, dict):
        raise ConfigError(f"脚本定义必须是映射(mapping)，收到: {type(data).__name__}")

    scenario = Scenario(
        name=str(data.get("name") or "scenario"),
        tree=parse_pages(_states_section(data)),
        graph=parse_graph(data),
        options=parse_options(data),
        meta=dict(data.get("meta") or {}),
    )
    _explain_page_references(scenario)
    return scenario


def _states_section(data: dict[str, Any]) -> Any:
    """取状态树那一节：``states`` 优先，兼容旧的 ``pages``。"""
    if "states" in data:
        return data.get("states")
    return data.get("pages")


def parse_pages(data: Any) -> PageTree:
    """解析嵌套的状态定义（``id`` 由嵌套位置推导成路径形式）。

    ``kind`` 缺省是**状态节点**；``kind: group`` 是纯分类节点，
    ``kind: overlay`` 是叠加层。

    递归过程要用 ``query_from_dict``（原子层），所以留在这里而不是
    ``PageTree.from_nested``：状态层不必知道"配置长什么样"，
    也就不用为了解析配置去 import 流程层。
    """
    tree = PageTree()
    if data is None:
        return tree
    if not isinstance(data, dict):
        raise ConfigError(f"states 必须是映射(mapping)，收到: {type(data).__name__}")

    for page_id, spec in data.items():
        _add_nested(tree, str(page_id), spec, parent=None)
    return tree


def _add_nested(tree: PageTree, page_id: str, spec: Any, *, parent: str | None) -> PageNode:
    """加一页（含 children）。**父先子后**，满足 :meth:`PageTree.add` 的前置条件。

    ## ``kind`` 在这里翻译成**类型**

    YAML 里写 ``kind: group`` / ``kind: overlay``，而类那边分成了
    :class:`~gamebot.state.page.PageGroup` 和
    :class:`~gamebot.state.page.PageLeaf`（见那两类的 docstring）。
    所以**配置格式没变**，变的是它落到哪个 Python 类型上 ——
    "分类节点不该有 queries"因此在写配置时也能被拦住（``PageGroup`` 没那个字段）。
    """
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise ConfigError(f"状态 {page_id!r} 的定义必须是映射(mapping)，收到: {spec!r}")

    payload = dict(spec)
    children = payload.pop("children", None)
    kind = payload.pop("kind", None)
    if isinstance(kind, str):
        kind = _coerce_enum(PageKind, kind, f"状态 {page_id!r} 的 kind")
    _reject_unknown(payload, _PAGE_KEYS, f"状态 {page_id!r}")
    if kind is PageKind.GROUP:
        # 分类节点只认下面这几个键 —— 它没有 queries / exclude / confidence /
        # terminal 这些识别相关的字段（那些是 PageLeaf 才有的）。
        # 这里早报一句人话，比等构造函数抛 "unexpected keyword argument" 好懂得多。
        extra = sorted(set(payload) - _GROUP_KEYS)
        if extra:
            raise ConfigError(
                f"状态 {page_id!r} 是分类节点（kind: group），不该有 {extra} —— "
                "它自己不参与匹配，只负责组织结构与 ROI 继承。"
                "要让它记录信息就别写 kind（那就是普通状态）。"
            )

    if payload.get("roi") is not None:
        payload["roi"] = _region_from_config(payload["roi"], f"状态 {page_id!r} 的 roi")
    for key in ("queries", "exclude"):
        raw = payload.get(key)
        if raw is None:
            continue
        if not isinstance(raw, (list, tuple)):
            raise ConfigError(f"状态 {page_id!r} 的 {key} 必须是列表")
        try:
            payload[key] = tuple(query_from_dict(item) for item in raw)
        except ValueError as exc:
            raise ConfigError(f"状态 {page_id!r} 的 {key} 解析失败: {exc}") from exc

    if kind is PageKind.GROUP:
        tree.add(PageGroup(id=page_id, **payload), parent)
    else:
        if kind is PageKind.OVERLAY:
            payload["overlay"] = True
        tree.add(PageLeaf(id=page_id, **payload), parent)

    if children is not None:
        if not isinstance(children, dict):
            raise ConfigError(f"状态 {page_id!r} 的 children 必须是映射(mapping)")
        for child_key, child_spec in children.items():
            name = str(child_key)
            if "/" in name:
                # 允许短 key（"lobby" 而不是全路径），但不许写路径：
                # 那会和"id 由嵌套位置推导"打架，出现两种真相。
                raise ConfigError(
                    f"子状态 {name!r} 的名字里不能带 '/' —— id 由嵌套位置推导"
                    "（父 id + '/' + 子 key）"
                )
            _add_nested(tree, f"{page_id}/{name}", child_spec, parent=page_id)
    return tree.require(page_id)


def parse_graph(data: dict[str, Any]) -> Graph:
    """解析 ``nodes`` / ``edges``。

    ``edges[].condition`` 要么是 ``{type: ..., ...}``（走 query_from_dict），
    要么是 ``{func: 模块路径}``（导入一个 Python 函数，逃生舱）。
    """
    raw_nodes = data.get("nodes") or {}
    raw_edges = data.get("edges") or []
    if not isinstance(raw_nodes, dict):
        raise ConfigError("nodes 必须是映射(mapping)：``节点名: {...}``")
    if not isinstance(raw_edges, (list, tuple)):
        raise ConfigError("edges 必须是列表")

    graph = Graph(initial=str(data.get("initial") or ""))

    for node_id, spec in raw_nodes.items():
        graph.add_node(_node_from_config(str(node_id), spec))

    for index, spec in enumerate(raw_edges):
        graph.add_edge(_edge_from_config(spec, index))

    if not graph.initial and graph.nodes:
        # 没写 initial 就用第一个加进去的节点（``Graph.add_node`` 的既有规则）。
        graph.initial = next(iter(graph.nodes))
    return graph


def _node_from_config(node_id: str, spec: Any) -> Node:
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise ConfigError(f"节点 {node_id!r} 的定义必须是映射(mapping)")
    payload = dict(spec)
    _reject_unknown(payload, _NODE_KEYS, f"节点 {node_id!r}")
    unsupported = [f for f in ("steps", "on_enter", "on_exit") if payload.get(f)]
    if unsupported:
        raise ConfigError(
            f"节点 {node_id!r} 写了 {unsupported} —— **YAML 里不支持写步骤**。"
            "步骤是普通函数（(ctx) -> ActionResult），只能写在 Python 里："
            "在功能目录的 steps/ 下定义，然后在 graph.py 的 Node(steps=[...]) 里引用。"
        )
    return Node(id=node_id, **payload)


def _edge_from_config(spec: Any, index: int) -> Edge:
    if not isinstance(spec, dict):
        raise ConfigError(f"第 {index} 条边必须是映射(mapping)")
    payload = dict(spec)
    _reject_unknown(payload, _EDGE_KEYS, f"第 {index} 条边")
    for field in ("source", "target"):
        if not payload.get(field):
            raise ConfigError(f"第 {index} 条边缺少 {field}")

    condition = payload.get("condition")
    if isinstance(condition, dict):
        if "func" in condition and "type" not in condition:
            payload["condition"] = _resolve_function(condition["func"], f"第 {index} 条边的 func")
        else:
            try:
                payload["condition"] = query_from_dict(condition)
            except ValueError as exc:
                raise ConfigError(f"第 {index} 条边的 condition 解析失败: {exc}") from exc
    if isinstance(payload.get("kind"), str):
        payload["kind"] = _coerce_enum(EdgeKind, payload["kind"], f"第 {index} 条边的 kind")
    payload.setdefault("label", "")
    payload.setdefault("meta", {})
    return Edge(**payload)


def parse_options(data: dict[str, Any]) -> EngineOptions:
    """解析顶层运行参数。

    只认已知字段，拼错的键直接报错 —— 静默忽略拼错的配置是这类 bug 的头号来源。
    """
    known = _known_option_keys()
    payload = {key: data[key] for key in known if key in data}
    unknown = sorted(key for key in data if key not in set(known) | _STRUCTURAL_KEYS)
    if unknown:
        raise ConfigError(
            f"脚本顶层有未知字段: {', '.join(unknown)}（可用: {sorted(known)}）"
        )

    if payload.get("on_unknown") is not None:
        payload["on_unknown"] = _coerce_enum(UnknownPolicy, payload["on_unknown"], "on_unknown")
    if payload.get("stop_pages") is not None:
        raw = payload["stop_pages"]
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            raise ConfigError("stop_pages 必须是列表或字符串")
        payload["stop_pages"] = tuple(str(p) for p in raw)
    return EngineOptions(**payload)


def _explain_page_references(scenario: Scenario) -> None:
    """节点写的 ``page`` 不在树里时给一句**更像人话**的提示。

    父节点的 key 一改，整棵子树的 id 就跟着变 —— 这正是 ``nodes[].page``
    最容易过期的地方。``Scenario.validate`` 会报"声明了不存在的状态"，
    但它不会说"它其实还在树里，只是变成了另一个路径"。
    """
    for node in scenario.graph.nodes.values():
        if not node.page or node.page in scenario.tree:
            continue
        tail = "/" + node.page.rsplit("/", 1)[-1]
        candidates = [p.id for p in scenario.tree.walk() if p.id.endswith(tail)]
        if candidates:
            raise ConfigError(
                f"节点 {node.id!r} 声明的状态 {node.page!r} 不在状态树里；"
                f"同名的状态还有: {', '.join(candidates)} —— 多半是某个父节点的 key 改过"
            )


def _region_from_config(value: Any, where: str) -> Region:
    """``roi`` 支持 ``[x,y,w,h]`` 和 ``{x,y,w,h}``。"""
    if isinstance(value, Region):
        return value
    if isinstance(value, dict):
        return Region.from_dict(value)
    if isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise ConfigError(f"{where} 需要 4 个数字 [x,y,w,h]，收到: {value!r}")
        return Region.from_tuple(tuple(int(v) for v in value))  # type: ignore[arg-type]
    raise ConfigError(f"{where} 的写法不认识: {value!r}（用 [x,y,w,h]）")


def _resolve_function(path: Any, where: str) -> Any:
    """逃生舱：``"包.模块.函数"`` -> 可调用对象。

    用来把**边条件**写成 Python 函数（``{func: games.xxx.my_condition}``）——
    查询表达不了的复杂逻辑走这条路。

    （**节点步骤不走这里**：步骤是普通函数，必须写在 Python 里，
    见上面 ``_add_node`` 对 ``steps`` 的报错。）
    """
    if not isinstance(path, str) or "." not in path:
        raise ConfigError(f"{where} 要写成 '包.模块.函数' 的形式，收到 {path!r}")
    module_path, _, attr = path.rpartition(".")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ConfigError(f"{where} 导入 {module_path!r} 失败: {exc}") from exc
    func = getattr(module, attr, None)
    if not callable(func):
        raise ConfigError(f"{where} 里 {attr!r} 不是可调用的（{module_path}）")
    return func


def _reject_unknown(payload: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ConfigError(f"{where} 有未知字段: {', '.join(unknown)}（可用: {sorted(allowed)}）")


def _coerce_enum(enum_cls: type, value: Any, where: str) -> Any:
    """把配置里的字符串转成枚举；大小写都容忍一点。"""
    if isinstance(value, enum_cls):
        return value
    text = str(value).strip()
    for candidate in (text, text.lower(), text.upper()):
        try:
            return enum_cls(candidate)
        except ValueError:
            continue
    choices = ", ".join(m.value for m in enum_cls)  # type: ignore[attr-defined]
    raise ConfigError(f"{where} 的值 {value!r} 不认识（可用: {choices}）")


def _known_option_keys() -> tuple[str, ...]:
    """``EngineOptions`` 的字段名（供 parse_options 做白名单）。"""
    from dataclasses import fields

    return tuple(f.name for f in fields(EngineOptions))
