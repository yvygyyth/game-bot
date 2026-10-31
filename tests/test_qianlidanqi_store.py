"""千里单骑 · 局内 store（纯函数/数据）测试。

不测画面：选槽/选类别完全由优先表 + 已拿记录决定，这里直接把表喂进去。
"""

from __future__ import annotations

from types import SimpleNamespace

from gamebot.state.blackboard import Blackboard
from games.mingjiangsha.scripts.qianlidanqi.store import (
    PRIORITY,
    BattleState,
    GeneralPriority,
    RewardKind,
    get_run_state,
    is_in_priority,
    parse_copper_text,
    parse_general_name,
    pick_reward_kind,
    pick_reward_slot,
    reset_run_state,
    resolve_general_priority,
)


class TestParseCopper:
    def test_plain_and_grouped(self) -> None:
        assert parse_copper_text("824") == 824
        assert parse_copper_text("1,234") == 1234
        assert parse_copper_text(" 96 ") == 96

    def test_ocr_confusions(self) -> None:
        assert parse_copper_text("O8") == 8
        assert parse_copper_text("1O8") == 108
        assert parse_copper_text("l2") == 12

    def test_garbage_is_none(self) -> None:
        assert parse_copper_text("") is None
        assert parse_copper_text("abc") is None


class TestParseGeneralName:
    def test_strips_gift_suffix(self) -> None:
        assert parse_general_name("吕布赠礼") == "吕布"
        assert parse_general_name("王异贈禮") == "王异"

    def test_empty(self) -> None:
        assert parse_general_name("") == ""
        assert parse_general_name("(空)") == ""
        assert parse_general_name("吕布") == "吕布"


class TestPriorityTable:
    def test_known_general(self) -> None:
        assert is_in_priority("吕布") is True
        assert resolve_general_priority("甘宁") == GeneralPriority(
            "甘宁", (RewardKind.TOKEN, RewardKind.BUFF)
        )

    def test_unknown_general_uses_default(self) -> None:
        entry = resolve_general_priority("张三")
        assert entry.name == "张三"
        assert entry.key_rewards  # 非空

    def test_table_order_is_stable(self) -> None:
        names = [entry.name for entry in PRIORITY]
        assert names[0] == "王异"
        assert len(names) == len(set(names))


class TestPickRewardSlot:
    def test_prefers_priority_table_order(self) -> None:
        state = BattleState()
        # 王异在表里排在吕布前面
        assert pick_reward_slot(["吕布赠礼", "王异赠礼"], state) == 1

    def test_skips_general_whose_key_rewards_are_done(self) -> None:
        state = BattleState()
        state.mark_general_reward("王异", RewardKind.TOKEN)
        # 王异已拿完 -> 轮到吕布
        assert pick_reward_slot(["吕布赠礼", "王异赠礼"], state) == 0

    def test_still_picks_general_with_one_of_two_rewards_left(self) -> None:
        state = BattleState()
        state.mark_general_reward("甘宁", RewardKind.TOKEN)
        # 甘宁要信物+驰援；只拿了信物，仍应选甘宁
        assert pick_reward_slot(["吕布赠礼", "甘宁赠礼"], state) == 1

    def test_all_unknown_falls_back_to_leftmost(self) -> None:
        state = BattleState()
        assert pick_reward_slot(["张三赠礼", "李四赠礼"], state) == 0

    def test_empty_titles(self) -> None:
        assert pick_reward_slot([], BattleState()) == 0


class TestPickRewardKind:
    def test_prefers_key_reward_then_remaining(self) -> None:
        entry = resolve_general_priority("甘宁")  # 信物 + 驰援
        state = BattleState()
        assert pick_reward_kind({RewardKind.TOKEN, RewardKind.BUFF}, entry, state) == (
            RewardKind.TOKEN
        )
        state.mark_general_reward("甘宁", RewardKind.TOKEN)
        assert pick_reward_kind({RewardKind.TOKEN, RewardKind.BUFF}, entry, state) == (
            RewardKind.BUFF
        )

    def test_unknown_general_uses_fallback_order(self) -> None:
        entry = resolve_general_priority("张三")
        # 默认序 BUFF > HELP > CARD > JOINT > TOKEN
        assert pick_reward_kind({RewardKind.HELP, RewardKind.CARD}, entry, BattleState()) == (
            RewardKind.HELP
        )

    def test_empty_available(self) -> None:
        assert pick_reward_kind(set(), None, BattleState()) is None


class TestRunState:
    def test_get_creates_and_reuses(self) -> None:
        ctx = SimpleNamespace(blackboard=Blackboard())
        first = get_run_state(ctx)
        second = get_run_state(ctx)
        assert first is second
        assert first.copper_coins == 0

    def test_reset_replaces(self) -> None:
        ctx = SimpleNamespace(blackboard=Blackboard())
        state = get_run_state(ctx)
        state.copper_coins = 42
        fresh = reset_run_state(ctx)
        assert fresh is not state
        assert fresh.copper_coins == 0
        assert get_run_state(ctx) is fresh

    def test_mark_reward_per_general(self) -> None:
        state = BattleState()
        state.mark_general_reward("吕布", RewardKind.TOKEN)
        assert state.has_general_reward("吕布", RewardKind.TOKEN) is True
        assert state.has_general_reward("吕布", RewardKind.BUFF) is False
        assert state.has_reward(RewardKind.TOKEN) is True
        assert state.has_reward(RewardKind.BUFF) is False
