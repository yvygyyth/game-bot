"""状态仓库 —— **跨运行**的记忆。

## 三种"存东西的地方"，按寿命分

================  ==================  ==================  ======================
                  谁写                这次跑完还在吗      住哪
================  ==================  ==================  ======================
**运行参数**      外面（表单/命令行）  与运行无关          ``ctx.param("...")``
**黑板**          步骤                ❌ 每次运行清空      ``ctx.blackboard``
**仓库**          步骤                ✅ 落盘，下次开还在  ``ctx.store(SPEC)``
================  ==================  ==================  ======================

判断只有一句：**"下次开还该记得吗？"** 记得 -> 仓库；不记得 -> 黑板。

## 为什么是"好几个仓库"，不是"一个更大的黑板"

背包、体力、累计局数…… 它们的寿命**不一样**：背包要一直在，"这一局点了几个按钮"
跑完就该忘。混在一个 dict 里，就只能靠人记住哪些 key 该清、哪些不该清 ——
而 ``ctx.reset()`` 只能一刀切。

拆成一个个**有名字**的仓库之后：

* 谁的数据在谁那儿（``bag`` / ``stamina`` / ``jingji.runs``），互相踩不到；
* 落盘也是一个仓库一个文件，坏一个不影响别的，删一个文件就是"忘掉这一件事"；
* 界面上可以按仓库分组显示，而不是一屏 ``battle.retry_count``。

## 声明在业务层，机制在框架层

一个仓库用 :func:`define_store` 声明，放在业务层的 ``store/`` **目录**里：

* ``games/<游戏>/store/`` —— 游戏级，多个脚本都能 import（背包、体力）；
* ``games/<游戏>/scripts/<功能>/store/`` —— 功能级，只有这个脚本用（累计局数）。

目录里**一个仓库一个文件**，文件名就是它记的东西（``bag.py`` / ``runs.py``），
``store/__init__.py`` 只做转发 —— 和 ``steps/`` 同一套组织方式。

``define_store`` 的第一个参数是仓库 id，**全局唯一**，也是落盘文件名：

* 游戏级：``id="bag"`` —— 落到 ``data/stores/<游戏>/bag.json``；
* 功能级：``id="jingji.runs"`` —— 前缀是功能名，落到 ``.../jingji.runs.json``。

前缀这一段是必需的：同一游戏的两个脚本都可能有 ``runs``，不隔开就会互相覆盖。
文件名与 id 的**最后一段**一致（``runs.py`` <-> ``"jingji.runs"``），
改名字时两边一起改。

## 刻意不做 schema 校验

仓库只负责"记住"，不负责"这个 key 该不该存在"。背包里的东西每周都在变，
逼着人先声明字段，等于把"改一行代码"变成"改声明 + 重启 + 迁移旧数据"。

所以字段名拼错不会报错（会多出一个 key）。这是**有意的取舍**：仓库的价值是
"下次开还在"，不是"帮我检查脚本"。要强约束的东西放运行参数（有表单校验）。

## 复合值：读出来是副本

``get`` 对 list / dict 返回**深拷贝**，``set`` 也存深拷贝。理由：如果返回的是活对象，
``items = bag.get("items"); items["x"] = 1`` 看起来"改成功了"，但仓库根本不知道 ——
这种**静默不生效**是最难查的一类问题，和这个项目"失败要说出来"的规矩相反。

要改复合值，用 :meth:`Store.patch` / :meth:`Store.append`，或者读出来改完再
``set`` 回去（两种都显式）。

## 落盘

* 每个仓库一个 JSON：``data/stores/<游戏>/<仓库 id>.json``；
* **原子写**（同目录临时文件 + ``os.replace``）：写一半断电不会留下半个 JSON；
* **坏文件不挡开跑**：解析失败就改名成 ``.corrupt-<时间戳>`` 留证据，再从默认值开始；
  "记忆丢了"能忍，"因为记忆坏了所以脚本跑不起来"不能忍；
* 写入时机在 :meth:`StoreManager.flush`（引擎每轮结束调一次），不是每次 ``set``
  都落盘 —— 一晚上几千次写盘换不来什么。

## 和事件的关系

仓库不 import 事件模块（状态层不该知道"事件"这个概念）。它的变化通过构造时传进来的
``on_change`` 回调报出去，由装配层（:mod:`gamebot.bootstrap`）翻译成 ``store_changed``
事件。这样"谁改了背包"能进事件流，而这一层依然只有一个依赖方向。
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..exceptions import ConfigError
from ..utils.logging import get_logger

log = get_logger("store")

__all__ = [
    "Store",
    "StoreChange",
    "StoreManager",
    "StoreSpec",
    "define_store",
]

#: 仓库 id：小写，点分命名空间（``"bag"`` / ``"jingji.runs"``）
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


def _json_safe(value: Any) -> bool:
    """能不能原样进 JSON。仓库里的东西必须能落盘，否则写盘那一刻才炸。"""
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def _copy(value: Any) -> Any:
    """深拷贝（只在容器上做，标量直接返回）。"""
    return copy.deepcopy(value) if isinstance(value, (list, dict)) else value


@dataclass(frozen=True, slots=True)
class StoreSpec:
    """一个仓库的**声明** —— 业务层写，框架照着它建实例。

    用 :func:`define_store` 构造，别直接 new（那个函数带了默认值和参数校验）。

    :param id: 仓库 id，全局唯一，同时是落盘文件名。功能级的写法是
        ``"<功能>.<名字>"``（如 ``"jingji.runs"``），与文件名最后一段一致。
    :param title: 给人看的名字（进界面、进日志）。
    :param defaults: 初始值。**不是 schema** —— 没列出的 key 照样能写。
    :param help: 一句话说明这个仓库记什么，进界面 tooltip。
    """

    id: str
    title: str
    defaults: Mapping[str, Any] = field(default_factory=dict)
    help: str = ""

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.id):
            raise ConfigError(
                f"仓库 id 要写成小写点分形式（如 'bag' / 'jingji.runs'），收到 {self.id!r}"
            )
        if not self.title.strip():
            raise ConfigError(f"仓库 {self.id!r}: title 不能为空")
        for key, value in self.defaults.items():
            if not isinstance(key, str) or not key.strip():
                raise ConfigError(
                    f"仓库 {self.id!r}: 默认值的 key 必须是非空字符串，收到 {key!r}"
                )
            if not _json_safe(value):
                raise ConfigError(
                    f"仓库 {self.id!r}: 字段 {key!r} 的默认值 {value!r} 不能存进 JSON"
                )

    def default_of(self, key: str) -> Any:
        return self.defaults.get(key)

    def __repr__(self) -> str:
        return f"StoreSpec({self.id!r}, {self.title!r}, {len(self.defaults)} 个默认字段)"


def define_store(
    store_id: str,
    *,
    title: str = "",
    defaults: Mapping[str, Any] | None = None,
    help: str = "",
) -> StoreSpec:
    """声明一个仓库。

    业务层这样用（``games/<游戏>/scripts/<功能>/store/rounds.py``）::

        from gamebot.state.store import define_store

        RUNS = define_store(
            "jingji.runs",
            title="累计局数",
            defaults={"done": 0, "last_finished_at": ""},
            help="跨运行累计；关掉界面再开也不会归零",
        )

    ``defaults`` 里的值决定"第一次开"的样子；没列出的 key 也能写
    （见模块 docstring 里"刻意不做 schema 校验"那一节）。

    :param store_id: 仓库 id，与文件名一致，同时决定落盘文件名。
    :param title: 界面/日志里的名字；留空就用 id。
    """
    return StoreSpec(
        id=store_id,
        title=title or store_id,
        defaults=dict(defaults or {}),
        help=help,
    )


@dataclass(frozen=True, slots=True)
class StoreChange:
    """一次写入。给事件流 / 界面用：**谁改了哪个仓库的哪个 key，从多少到多少**。"""

    store: str
    key: str
    old: Any
    new: Any

    def to_dict(self) -> dict[str, Any]:
        return {"store": self.store, "key": self.key, "old": self.old, "new": self.new}


class Store:
    """一个仓库的**运行期视图** —— 绑在某次运行的 :class:`StoreManager` 上。

    业务代码拿它的唯一方式::

        from ..store import RUNS

        ctx.store(RUNS).bump("done")

    数据本身在管理器里（一个仓库一份），这里只是"带名字的入口"。
    所有写操作都过管理器，所以脏标记和变更回调只有一处。
    """

    __slots__ = ("_manager", "_spec")

    def __init__(self, spec: StoreSpec, manager: StoreManager) -> None:
        self._spec = spec
        self._manager = manager

    @property
    def spec(self) -> StoreSpec:
        return self._spec

    @property
    def id(self) -> str:
        return self._spec.id

    @property
    def title(self) -> str:
        return self._spec.title

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def get(self, key: str, default: Any = None) -> Any:
        """读一个 key。没有时回落到声明里的默认值，再没有就返回 ``default``。

        list / dict 返回的是**副本** —— 就地改它不会生效（原因见模块 docstring）。
        """
        data = self._manager._data_of(self._spec)
        if key in data:
            return _copy(data[key])
        return _copy(self._spec.defaults.get(key, default))

    def keys(self) -> list[str]:
        """当前所有的 key（声明里的默认值也在内）。"""
        merged = {**self._spec.defaults, **self._manager._data_of(self._spec)}
        return list(merged)

    def as_dict(self) -> dict[str, Any]:
        """当前全部内容（副本）。界面和 describe 用。"""
        merged = {**self._spec.defaults, **self._manager._data_of(self._spec)}
        return {key: _copy(value) for key, value in merged.items()}

    def __contains__(self, key: object) -> bool:
        return key in self.keys()

    def __len__(self) -> int:
        return len(self.keys())

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def set(self, key: str, value: Any) -> None:
        """写一个 key。值必须能存进 JSON。"""
        self._manager._write(self._spec, key, value)

    def update(self, values: Mapping[str, Any] | None = None, /, **kwargs: Any) -> None:
        """一次写多个 key。"""
        merged: dict[str, Any] = dict(values or {})
        merged.update(kwargs)
        for key, value in merged.items():
            self.set(key, value)

    def bump(self, key: str, delta: int = 1, *, start: int = 0) -> int:
        """计数器自增，返回新值。累计局数、击杀数最常用。"""
        current = self.get(key)
        base = current if isinstance(current, int) and not isinstance(current, bool) else start
        value = base + delta
        self.set(key, value)
        return value

    def patch(self, key: str, values: Mapping[str, Any]) -> dict[str, Any]:
        """给一个 dict 字段合并几个键（就地改 ``get`` 的返回值不算数，用这个）。"""
        current = self.get(key)
        if not isinstance(current, dict):
            raise ConfigError(
                f"仓库 {self.id!r} 的 {key!r} 不是 dict（现在是 {type(current).__name__}），"
                f"不能用 patch"
            )
        merged = {**current, **values}
        self.set(key, merged)
        return merged

    def append(self, key: str, value: Any) -> list[Any]:
        """给一个 list 字段追加一项。"""
        current = self.get(key)
        if not isinstance(current, list):
            raise ConfigError(
                f"仓库 {self.id!r} 的 {key!r} 不是 list（现在是 {type(current).__name__}），"
                f"不能用 append"
            )
        items = [*current, value]
        self.set(key, items)
        return items

    def drop(self, key: str) -> None:
        """删掉一个 key（下次读会回落到默认值）。"""
        self._manager._drop(self._spec, key)

    def reset(self) -> None:
        """清回默认值。"""
        self._manager._reset(self._spec)

    def __repr__(self) -> str:
        return f"Store({self.id!r}, {len(self)} 个 key)"


class StoreManager:
    """一次运行里所有仓库的管理者 —— 负责加载、脏标记、落盘、变更通知。

    **每个运行一个**（挂在 ``RunContext`` 上）。同一个仓库在两次运行之间靠磁盘上的
    那个 JSON 传递，不是靠这个对象活着。

    :param root: 落盘根目录（框架会给 ``<仓库根>/data/stores``）。
        传 ``None`` 表示**只放内存**（测试用，不碰盘）。
    :param game: 游戏名，决定子目录（``data/stores/<游戏>/…``）。
    :param on_change: 每次写入后回调一次；装配层用它发 ``store_changed`` 事件。
    """

    def __init__(
        self,
        root: Path | str | None,
        *,
        game: str = "",
        on_change: Callable[[StoreChange], None] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else None
        self.game = game.strip()
        self.on_change = on_change
        self._stores: dict[str, Store] = {}
        self._data: dict[str, dict[str, Any]] = {}
        self._loaded: set[str] = set()
        self._dirty: set[str] = set()

    # ------------------------------------------------------------------ #
    # 取仓库
    # ------------------------------------------------------------------ #
    def store(self, spec: StoreSpec) -> Store:
        """按声明取仓库（没有就登记）。同一个 id 声明成两份不同内容 -> 报错。"""
        existing = self._stores.get(spec.id)
        if existing is not None:
            if existing.spec != spec:
                raise ConfigError(
                    f"仓库 id {spec.id!r} 被声明了两次且内容不同：\n"
                    f"  已有: {existing.spec!r}\n"
                    f"  新的: {spec!r}\n"
                    f"id 是落盘文件名，必须全局唯一 —— 给其中一个改名"
                )
            return existing
        view = Store(spec, self)
        self._stores[spec.id] = view
        return view

    def specs(self) -> list[StoreSpec]:
        return [s.spec for s in self._stores.values()]

    def views(self) -> list[Store]:
        return list(self._stores.values())

    @property
    def dirty(self) -> set[str]:
        return set(self._dirty)

    # ------------------------------------------------------------------ #
    # 数据（只有 Store 该调；下划线开头是"内部"的意思）
    # ------------------------------------------------------------------ #
    def _data_of(self, spec: StoreSpec) -> dict[str, Any]:
        self._ensure_loaded(spec)
        return self._data.setdefault(spec.id, {})

    def _write(self, spec: StoreSpec, key: str, value: Any) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ConfigError(f"仓库 {spec.id!r}: key 必须是非空字符串，收到 {key!r}")
        if not _json_safe(value):
            raise ConfigError(
                f"仓库 {spec.id!r}: 字段 {key!r} 的值 {value!r} 存不进 JSON"
                f"（仓库要落盘，只能放 JSON 支持的类型）"
            )
        data = self._data_of(spec)
        old = data.get(key, spec.defaults.get(key))
        stored = _copy(value)
        data[key] = stored
        self._dirty.add(spec.id)
        if self.on_change is not None:
            self.on_change(StoreChange(store=spec.id, key=key, old=_copy(old), new=_copy(stored)))

    def _drop(self, spec: StoreSpec, key: str) -> None:
        data = self._data_of(spec)
        if key not in data:
            return
        old = data.pop(key)
        self._dirty.add(spec.id)
        if self.on_change is not None:
            self.on_change(StoreChange(store=spec.id, key=key, old=_copy(old), new=None))

    def _reset(self, spec: StoreSpec) -> None:
        self._ensure_loaded(spec)
        self._data[spec.id] = {key: _copy(value) for key, value in spec.defaults.items()}
        self._dirty.add(spec.id)
        if self.on_change is not None:
            self.on_change(StoreChange(store=spec.id, key="*", old=None, new=self._data[spec.id]))

    # ------------------------------------------------------------------ #
    # 落盘
    # ------------------------------------------------------------------ #
    def path_of(self, spec: StoreSpec) -> Path | None:
        """这个仓库落在哪个文件。只放内存时返回 ``None``。"""
        if self.root is None:
            return None
        return self.root / (self.game or "default") / f"{spec.id}.json"

    def _ensure_loaded(self, spec: StoreSpec) -> None:
        if spec.id in self._loaded:
            return
        self._loaded.add(spec.id)
        # 先铺默认值，再让磁盘上的覆盖它
        self._data[spec.id] = {key: _copy(value) for key, value in spec.defaults.items()}
        path = self.path_of(spec)
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._quarantine(path, exc)
            return
        state = payload.get("state") if isinstance(payload, dict) else None
        if not isinstance(state, dict):
            self._quarantine(path, ValueError("文件里没有 state 字典"))
            return
        extra = [key for key in state if key not in spec.defaults]
        self._data[spec.id].update(dict(state))
        if extra:
            log.info(
                "仓库 %r 加载了 %d 个未声明的字段（保留，不删）: %s",
                spec.id,
                len(extra),
                ", ".join(sorted(extra)[:8]),
            )

    def _quarantine(self, path: Path, exc: BaseException) -> None:
        """坏文件改名留证据，然后当作空仓库继续 —— 记忆坏了不能挡住开跑。"""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
        try:
            os.replace(path, target)
        except OSError:  # pragma: no cover - 极端情况（权限/占用）
            log.error("仓库文件损坏且无法改名: %s (%s)", path, exc)
            return
        log.error("仓库文件损坏，已改名留证据: %s -> %s (%s)", path.name, target.name, exc)

    def flush(self) -> list[Path]:
        """把所有脏仓库写盘，返回写过的文件。"""
        written: list[Path] = []
        for store_id in sorted(self._dirty):
            view = self._stores.get(store_id)
            if view is None:  # pragma: no cover - 理论上不会发生
                continue
            path = self.path_of(view.spec)
            if path is None:
                # 只放内存：没有"待落盘"这回事，清掉标记免得 dirty 越攒越大。
                self._dirty.discard(store_id)
                continue
            payload = {
                "version": 1,
                "store": view.spec.id,
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "state": self._data.get(view.spec.id, {}),
            }
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(f".{path.name}.tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, path)
            except OSError as exc:
                # 写盘失败**不抛**：一晚上的进度不该因为磁盘满而让脚本崩掉。
                # 但要留痕，且保留脏标记（下次 flush 还会再试）。
                log.error("仓库 %r 写盘失败: %s", view.spec.id, exc)
                continue
            written.append(path)
            self._dirty.discard(store_id)
        return written

    def close(self) -> None:
        """收尾：落盘。可以重复调。"""
        self.flush()

    # ------------------------------------------------------------------ #
    def items(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for store in self._stores.values():
            yield store.id, store.as_dict()

    def __len__(self) -> int:
        return len(self._stores)

    def __repr__(self) -> str:
        return (
            f"StoreManager(game={self.game!r}, {len(self._stores)} 个仓库, "
            f"{len(self._dirty)} 个待落盘, root={self.root})"
        )
