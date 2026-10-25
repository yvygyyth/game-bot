"""状态仓库 —— **跨运行**的记忆。

这个文件钉住几件"对业务层承诺过的事"：

* 默认值 / ``set`` / ``bump`` / ``patch`` / ``append`` 的语义；
* 读出来的复合值是**副本**（就地改不生效，必须 ``set`` 回去）；
* 一个仓库一个文件、原子写、坏文件不挡开跑、未知 key 不丢；
* 同一个 id 声明成两份不同内容 -> 装配期报错；
* 寿命：``ctx.reset()`` **不清**仓库，``close()`` 落盘。

最后一条是这个仓库存在的全部理由 —— 前三条只是它的使用方式。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gamebot.bootstrap import build_store_manager
from gamebot.config.schema import RunPaths
from gamebot.context import RunContext
from gamebot.exceptions import ConfigError
from gamebot.state.store import StoreChange, StoreManager, define_store

BAG = define_store("bag", title="背包", defaults={"soul": 0, "items": {}})
RUNS = define_store("jingji.runs", title="累计局数", defaults={"done": 0})


def _bump_runs(ctx):
    """一步：把累计局数 +1（用来验证"跑一遍就记住"）。"""
    from gamebot.types import ActionResult

    ctx.store(RUNS).bump("done")
    return ActionResult.success()


class TestDefineStore:
    def test_title_defaults_to_id(self) -> None:
        assert define_store("bag").title == "bag"

    @pytest.mark.parametrize("bad", ["Bag", "1bag", "bag-1", "", "bag..x"])
    def test_bad_id_is_rejected(self, bad: str) -> None:
        with pytest.raises(ConfigError):
            define_store(bad)

    def test_empty_title_is_rejected(self) -> None:
        with pytest.raises(ConfigError):
            define_store("bag", title="   ")

    def test_non_json_default_is_rejected_at_definition(self) -> None:
        """默认值要能落盘 —— 在**声明那一行**就报，而不是第一次 flush 才炸。"""
        with pytest.raises(ConfigError):
            define_store("bag", defaults={"weird": object()})

    def test_spec_is_frozen(self) -> None:
        """声明是**数据**，不该在运行期被人改掉。"""
        from dataclasses import FrozenInstanceError

        spec = define_store("bag")
        with pytest.raises(FrozenInstanceError):
            spec.id = "other"  # type: ignore[misc]


class TestStoreSemantics:
    @pytest.fixture
    def store(self):
        return StoreManager(None).store(BAG)

    def test_defaults_are_visible_before_any_write(self, store) -> None:
        assert store.get("soul") == 0
        assert store.get("items") == {}
        assert store.get("missing") is None
        assert store.get("missing", "兜底") == "兜底"

    def test_set_then_get(self, store) -> None:
        store.set("soul", 12)
        assert store.get("soul") == 12

    def test_update_writes_several_keys(self, store) -> None:
        store.update({"soul": 1, "gold": 2})
        assert (store.get("soul"), store.get("gold")) == (1, 2)

    def test_bump_returns_new_value(self, store) -> None:
        assert store.bump("done") == 1
        assert store.bump("done", 2) == 3

    def test_bump_on_non_int_starts_from_start(self, store) -> None:
        store.set("weird", "不是数字")
        assert store.bump("weird") == 1

    def test_patch_merges_dict(self, store) -> None:
        store.patch("items", {"soul": 1})
        store.patch("items", {"gold": 2})
        assert store.get("items") == {"soul": 1, "gold": 2}

    def test_patch_on_non_dict_raises(self, store) -> None:
        with pytest.raises(ConfigError):
            store.patch("soul", {"x": 1})

    def test_append_on_list(self, store) -> None:
        store.set("log", [])
        store.append("log", "a")
        assert store.get("log") == ["a"]

    def test_append_on_non_list_raises(self, store) -> None:
        with pytest.raises(ConfigError):
            store.append("soul", 1)

    def test_get_returns_a_copy_of_containers(self, store) -> None:
        """就地改 ``get`` 的返回值**不该**生效 —— 否则是静默丢数据。"""
        store.patch("items", {"soul": 1})
        snapshot = store.get("items")
        snapshot["soul"] = 999
        assert store.get("items") == {"soul": 1}

    def test_set_stores_a_copy(self, store) -> None:
        payload = {"soul": 1}
        store.set("items", payload)
        payload["soul"] = 999
        assert store.get("items") == {"soul": 1}

    def test_drop_falls_back_to_default(self, store) -> None:
        store.set("soul", 5)
        store.drop("soul")
        assert store.get("soul") == 0

    def test_reset(self, store) -> None:
        store.set("soul", 5)
        store.reset()
        assert store.get("soul") == 0

    def test_unserializable_value_is_rejected(self, store) -> None:
        """仓库要落盘，所以非 JSON 值在 ``set`` 那一刻就报，而不是写盘时。"""
        with pytest.raises(ConfigError):
            store.set("soul", object())

    def test_as_dict_merges_defaults_and_writes(self, store) -> None:
        store.set("soul", 3)
        assert store.as_dict() == {"soul": 3, "items": {}}

    def test_len_and_contains(self, store) -> None:
        assert "soul" in store
        assert len(store) == 2


class TestPersistence:
    @pytest.fixture
    def root(self, tmp_path) -> Path:
        return tmp_path / "stores"

    def test_writes_one_file_per_store(self, root) -> None:
        manager = StoreManager(root, game="mingjiangsha")
        manager.store(BAG).set("soul", 7)
        written = manager.flush()

        assert written == [root / "mingjiangsha" / "bag.json"]
        payload = json.loads(written[0].read_text(encoding="utf-8"))
        assert payload["state"]["soul"] == 7
        assert payload["store"] == "bag"

    def test_a_new_manager_reads_it_back(self, root) -> None:
        first = StoreManager(root, game="mingjiangsha")
        first.store(RUNS).bump("done", 3)
        first.close()

        second = StoreManager(root, game="mingjiangsha")
        assert second.store(RUNS).get("done") == 3

    def test_flush_is_idempotent(self, root) -> None:
        manager = StoreManager(root, game="g")
        manager.store(BAG).set("soul", 1)
        assert len(manager.flush()) == 1
        assert manager.flush() == []

    def test_memory_only_manager_writes_nothing(self, tmp_path) -> None:
        manager = StoreManager(None, game="g")
        manager.store(BAG).set("soul", 1)
        assert manager.flush() == []
        assert not list(tmp_path.iterdir())

    def test_no_temp_file_is_left_behind(self, root) -> None:
        """原子写：临时文件必须已经 ``os.replace`` 掉。"""
        manager = StoreManager(root, game="g")
        manager.store(BAG).set("soul", 1)
        manager.flush()
        leftovers = [p.name for p in (root / "g").iterdir() if p.name.startswith(".")]
        assert leftovers == []

    def test_unknown_keys_survive_a_round_trip(self, root) -> None:
        """老版本写过、新版本没声明的 key 不能静默丢掉 —— 那是别人的数据。"""
        path = root / "g" / "bag.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"version": 1, "store": "bag", "state": {"soul": 5, "legacy": "x"}}),
            encoding="utf-8",
        )
        manager = StoreManager(root, game="g")
        store = manager.store(BAG)
        assert store.get("soul") == 5
        assert store.get("legacy") == "x"

        store.set("soul", 6)
        manager.flush()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["state"]["legacy"] == "x"

    def test_corrupt_file_is_quarantined_not_fatal(self, root) -> None:
        """记忆坏了不能挡住开跑：改名留证据，然后从默认值开始。"""
        path = root / "g" / "bag.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ 这不是 JSON", encoding="utf-8")

        manager = StoreManager(root, game="g")
        assert manager.store(BAG).get("soul") == 0
        assert not path.exists(), "坏文件应该被改名"
        quarantined = list(path.parent.glob("bag.corrupt-*.json"))
        assert len(quarantined) == 1
        assert "这不是 JSON" in quarantined[0].read_text(encoding="utf-8")

    def test_missing_state_key_is_also_quarantined(self, root) -> None:
        path = root / "g" / "bag.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"version": 1}), encoding="utf-8")
        manager = StoreManager(root, game="g")
        assert manager.store(BAG).get("soul") == 0
        assert list(path.parent.glob("bag.corrupt-*.json"))

    def test_same_id_with_different_content_is_rejected(self, root) -> None:
        other = define_store("bag", title="另一个背包", defaults={"gold": 0})
        manager = StoreManager(root, game="g")
        manager.store(BAG)
        with pytest.raises(ConfigError, match="bag"):
            manager.store(other)

    def test_same_id_with_same_content_is_reused(self, root) -> None:
        """两份一模一样的声明（拷贝来的）不算冲突。"""
        twin = define_store("bag", title="背包", defaults={"soul": 0, "items": {}})
        manager = StoreManager(root, game="g")
        assert manager.store(BAG) is manager.store(twin)

    def test_change_callback_reports_old_and_new(self) -> None:
        seen: list[StoreChange] = []
        manager = StoreManager(None, game="g", on_change=seen.append)
        store = manager.store(BAG)
        store.set("soul", 3)
        store.bump("soul")

        assert [c.key for c in seen] == ["soul", "soul"]
        assert (seen[0].old, seen[0].new) == (0, 3)
        assert (seen[1].old, seen[1].new) == (3, 4)
        assert seen[0].store == "bag"

    def test_build_store_manager_forwards_callback(self, tmp_path) -> None:
        """装配层传进来的回调真的接到了管理器上（``store_changed`` 事件靠它）。"""
        seen: list[StoreChange] = []
        paths = RunPaths.under(tmp_path)
        manager = build_store_manager(paths, game="g", on_change=seen.append)
        manager.store(BAG).set("soul", 1)
        assert seen and seen[0].new == 1


class TestLifetime:
    """仓库活过运行 —— 和黑板的分界线。"""

    def test_reset_does_not_clear_stores(self, tmp_path) -> None:
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession

        from .conftest import FakeMatcher, FakeReader

        paths = RunPaths.under(tmp_path)
        session = BaseSession(
            build_fake_backends(size=(320, 200)), matcher=FakeMatcher(), reader=FakeReader()
        )
        ctx = RunContext(session, name="mingjiangsha/jingji", paths=paths)
        ctx.store(RUNS).set("done", 9)

        ctx.reset()  # 引擎每轮开跑都调它

        assert ctx.store(RUNS).get("done") == 9
        assert ctx.blackboard.as_dict() == {}
        ctx.close()

    def test_close_flushes_to_disk(self, tmp_path) -> None:
        from gamebot.atomic.backends.fake import build_fake_backends
        from gamebot.atomic.session import BaseSession

        from .conftest import FakeMatcher, FakeReader

        paths = RunPaths.under(tmp_path)
        session = BaseSession(
            build_fake_backends(size=(320, 200)), matcher=FakeMatcher(), reader=FakeReader()
        )
        ctx = RunContext(session, name="mingjiangsha/jingji", paths=paths)
        ctx.store(RUNS).set("done", 2)
        ctx.close()

        path = tmp_path / "data" / "stores" / "mingjiangsha" / "jingji.runs.json"
        assert path.is_file()
        assert json.loads(path.read_text(encoding="utf-8"))["state"]["done"] == 2

    def test_two_runs_keep_counting(self, ctx) -> None:
        """引擎跑两遍：``run()`` 每次都 ``reset()``，但仓库不该被清。

        这是这个仓库存在的**全部理由**。早先用的是黑板，跑第二遍就归零 ——
        表现是"点停止再点开始，累计局数从 0 重新数"。
        """
        from gamebot.atomic.query import ImageQuery
        from gamebot.execution.executor import Executor
        from gamebot.flow import NodeBindings
        from gamebot.flow.engine import FlowEngine
        from gamebot.flow.graph import Graph, Node
        from gamebot.flow.scenario import Scenario
        from gamebot.state.page import Page, PageTree

        tree = PageTree()
        tree.add(Page("home", queries=(ImageQuery("a.png"),)))
        graph = Graph(initial="home")
        graph.add_node(Node("home", steps=[_bump_runs]))
        scenario = Scenario(
            name="store",
            tree=tree,
            graph=graph,
            bindings=NodeBindings.of([("home", "home")]),
        )
        scenario.options.tick_interval = 0.001
        scenario.options.max_ticks = 1
        scenario.validate()

        ctx.executor = Executor(ctx)
        engine = FlowEngine(scenario, ctx)
        engine.run()
        engine.run()

        assert ctx.store(RUNS).get("done") == 2

        path = ctx.stores.path_of(RUNS)
        assert path is not None
        ctx.close()
        assert json.loads(path.read_text(encoding="utf-8"))["state"]["done"] == 2
