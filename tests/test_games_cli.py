"""业务层 CLI 的辅助函数测试。

`games run --param` 是本轮新加的入参通道 —— 它必须做**类型转换**，
否则步骤里拿到的是字符串，`range("5")` 直接炸，而报错点在步骤、
跟命令行看不出关系。
"""

from __future__ import annotations

import pytest

from games.__main__ import _coerce_param, _parse_params


class TestCoerceParam:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("5", 5),
            ("0", 0),
            ("-3", -3),
            ("1.5", 1.5),
            ("0.85", 0.85),
            ("true", True),
            ("True", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("no", False),
            ("off", False),
            ("battle", "battle"),
            ("1号队", "1号队"),
            ("", ""),
        ],
    )
    def test_conversions(self, raw, expected):
        assert _coerce_param(raw) == expected

    def test_number_like_string_stays_string(self):
        """``1号队`` 不该被当成数字 —— int/float 都会失败，原样返回。"""
        assert _coerce_param("1号队") == "1号队"

    def test_float_that_looks_like_版本号(self):
        """``2.0.1`` 两个都转不了，保持字符串。"""
        assert _coerce_param("2.0.1") == "2.0.1"


class TestParseParams:
    def test_empty(self):
        assert _parse_params([]) == ({}, [])

    def test_single(self):
        values, bad = _parse_params(["rounds=5"])
        assert values == {"rounds": 5}
        assert bad == []

    def test_multiple(self):
        values, bad = _parse_params(["rounds=5", "target=battle", "dry=true"])
        assert values == {"rounds": 5, "target": "battle", "dry": True}
        assert bad == []

    def test_dotted_names(self):
        """点分层级避免撞名。"""
        values, _ = _parse_params(["farm.rounds=3", "rounds=9"])
        assert values == {"farm.rounds": 3, "rounds": 9}

    def test_value_containing_equals(self):
        """值里再有 ``=`` 也算值（只按**第一个** ``=`` 切）。"""
        values, bad = _parse_params(["expr=a=b"])
        assert values == {"expr": "a=b"}
        assert bad == []

    def test_missing_equals_is_reported_not_swallowed(self):
        """写错的要**报出来**，不能静默丢掉 —— 静默丢掉会让人以为参数生效了。"""
        values, bad = _parse_params(["rounds"])
        assert values == {}
        assert bad == ["rounds"]

    def test_empty_name_is_reported(self):
        values, bad = _parse_params(["=5"])
        assert values == {}
        assert bad == ["=5"]

    def test_bad_ones_do_not_block_good_ones(self):
        values, bad = _parse_params(["rounds=5", "oops", "target=battle"])
        assert values == {"rounds": 5, "target": "battle"}
        assert bad == ["oops"]

    def test_whitespace_is_trimmed(self):
        values, _ = _parse_params(["  rounds = 5  "])
        assert values == {"rounds": 5}
