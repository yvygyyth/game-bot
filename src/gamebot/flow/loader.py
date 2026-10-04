"""把 YAML 流程配置解析成 ``FlowDefinition``。

配置文件长什么样，见 ``config/flows/example_flow.yaml``。设计目标是
"**改流程不用改 Python**"：

* 状态识别条件 -> ``states[].queries``
* 每个状态做什么 -> ``states[].steps``（步骤用 ``type`` 字段区分）
* 状态怎么走 -> ``transitions``
* 运行参数 -> 顶层字段

步骤 / 查询的反序列化都走注册表（``QUERY_TYPES`` / ``STEP_TYPES``），
新增一种步骤只要注册一下，不用改这个文件。

未实现部分见各方法 docstring。``parse_definition`` 目前只做"骨架 + 校验"，
真正的字段映射待写。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..exceptions import ConfigError, FlowError
from ..state.definition import StateDefinition
from .definition import FlowDefinition, UnknownPolicy
from .node import FlowNode
from .transition import Transition, TransitionKind

__all__ = ["load_flow", "parse_definition", "parse_node", "parse_state", "parse_transition"]


def load_flow(path: str | Path) -> FlowDefinition:
    """从 YAML 文件加载流程定义。

    :raises ConfigError: 文件不存在 / YAML 语法错误 / 顶层不是 mapping。
    :raises FlowError: 定义本身自相矛盾（由 ``FlowDefinition.validate`` 抛出）。
    """
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"流程文件不存在: {file}")
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("缺少 PyYAML，请执行: uv sync") from exc

    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"流程文件 YAML 解析失败: {file} — {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"流程文件顶层必须是映射(mapping): {file}")

    definition = parse_definition(data)
    definition.validate()
    return definition


def parse_definition(data: dict[str, Any]) -> FlowDefinition:
    """把字典解析成 ``FlowDefinition``。

    期望结构::

        name: my_flow
        initial: main_menu
        tick_interval: 0.2
        max_runtime: 3600
        on_unknown: wait          # wait | reload_tick | recovery | stop
        recovery_state: main_menu
        unknown_grace: 1.5
        stop_states: [game_closed]
        states:
          main_menu:
            queries: [...]
            exclude: [...]
            priority: 10
            min_stable_frames: 2
            timeout: 60
            description: 主界面
            steps: [...]          # 可选，等价于 nodes.main_menu.steps
        transitions:
          - from: [main_menu]
            to: battle
            priority: 10
            guard: {...}
            cooldown: 0.5
            max_times: 3
            label: 进入战斗
    """
    raise NotImplementedError(
        "待实现: 顶层字段 -> states/nodes/transitions 分别调 "
        "parse_state / parse_node / parse_transition"
    )


def parse_state(data: dict[str, Any], state_id: str) -> StateDefinition:
    """解析单个状态定义。``queries`` / ``exclude`` 里的字典走 ``query_from_dict``。"""
    raise NotImplementedError("待实现")


def parse_node(data: dict[str, Any], state_id: str) -> FlowNode:
    """解析节点（``steps`` / ``on_enter`` / ``on_exit`` 走 ``STEP_TYPES`` 注册表）。"""
    raise NotImplementedError("待实现")


def parse_transition(data: dict[str, Any], index: int) -> Transition:
    """解析一条转移。``from`` 是关键字，映射到 ``sources``。"""
    raise NotImplementedError(
        "待实现: 'from' -> sources, 'to' -> target, kind 字符串 -> TransitionKind"
    )


# --------------------------------------------------------------------------- #
# 注册表 —— 新增查询 / 步骤类型时在这里登记
# --------------------------------------------------------------------------- #
def query_types() -> dict[str, type]:
    """可用的 Query 类型名 -> 类。"""
    from ..atomic.query import query_registry

    return query_registry()


def step_types() -> dict[str, type]:
    """可用的 Step 类型名 -> 类。"""
    from ..execution.step import step_registry

    return step_registry()


_ = (FlowError, TransitionKind, UnknownPolicy)
