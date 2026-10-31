"""文档里写的**启动方式**必须真的跑得通，而且不能出现已被删掉的命令。

## 为什么只测这一件事了

项目现在**只有一条命令**：启动界面。

```bash
uv run python -m gamebot
```

写脚本需要的其他动作都在界面里（选脚本即检查、「空跑」勾选框、识图日志）。
所以这份测试的职责变简单了：

1. 文档里那条启动命令**真的存在**（flags 能被真实 parser 接受）；
2. 文档里**不再出现**已删除的 `python -m games …`；
3. 权限（UIPI）那节还在 —— 它解释了"点了没反应"这种静默失效，
   和入口无关，永远需要。

「照文档做不通」是最伤人的一类问题（读者会先怀疑自己），所以这几条值得测。
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "getting-started.md"


def _doc() -> str:
    assert DOC.is_file(), f"文档不见了: {DOC}"
    return DOC.read_text(encoding="utf-8")


class TestDocExistsAndIsReadable:
    def test_the_doc_is_where_we_think(self):
        assert DOC.is_file()

    def test_it_covers_the_four_things_the_user_asked_for(self):
        """用户要的是"依赖安装、启动方式什么的"。四件事都得有。"""
        text = _doc()
        for topic in ("依赖", "启动", "命令", "出问题"):
            assert topic in text, f"文档里没有讲 {topic!r}"


class TestStartupCommandIsReal:
    def test_the_startup_command_is_in_the_first_screen(self):
        """第一屏就能抄到那条命令 —— 而不是先读一大段权限说明。"""
        text = _doc()
        startup = text.index("uv run python -m gamebot")
        assert startup < len(text) // 4, "启动命令太靠后了，第一屏看不到"
        assert startup < text.index("## 1."), "启动命令必须排在讲权限之前"

    @pytest.mark.parametrize(
        "argv",
        [
            [],
            ["--script", "mingjiangsha/jingji"],
            ["--snapshot", "out.png"],
        ],
    )
    def test_the_parser_accepts_it(self, argv):
        """``python -m gamebot …`` 里的每种写法都要被真实 parser 接受。"""
        from gamebot.__main__ import build_parser

        build_parser().parse_args(argv)

    def test_it_says_no_admin_is_needed_to_start(self):
        """改代码、跑测试、空跑都不用提权 —— 写成"必须管理员"会吓退人。"""
        text = _doc()
        assert "普通权限就能跑" in text or "不用" in text
        assert "uv run python -m gamebot" in text

    def test_it_says_when_admin_is_actually_needed(self):
        """但"真点游戏"确实需要 —— 那张表要把两种情况分开。"""
        text = _doc()
        assert "真跑" in text
        assert "\\dev.ps1" in text


class TestNoDeletedCommandsInTheDoc:
    """命令行入口删掉之后，文档不能还留着那些命令。"""

    def test_no_python_m_games_commands(self):
        text = _doc()
        assert "python -m games" not in text, (
            "文档里还有已被删除的 `python -m games …` 命令 —— "
            "那些动作现在都在界面里"
        )

    def test_no_gamebot_subcommands(self):
        """``gamebot windows / capture / grab`` 已经删了，只剩启动。"""
        text = _doc()
        for stale in ("gamebot windows", "gamebot capture", "gamebot grab", "gamebot ui"):
            assert stale not in text, f"文档里还有已删除的命令 {stale!r}"


class TestUipiSectionIsPresent:
    """权限那一节是这份文档**最重要**的部分。

    级别不够时一切都是静默失效的，而人（包括我）会先去怀疑坐标和模板。
    所以它必须在，并且三条典型症状写全。
    """

    def test_it_explains_why_admin_is_needed(self):
        text = _doc()
        assert "UIPI" in text
        assert "完整性级别" in text

    def test_it_lists_the_silent_failure_symptoms(self):
        text = _doc()
        assert "静态失效" in text or "静默失效" in text
        assert "点击" in text
        assert "快捷键" in text

    def test_it_says_tests_do_not_need_admin(self):
        text = _doc()
        assert "pytest" in text
        assert "不用" in text

    def test_the_exe_is_marked_as_a_build_artifact(self):
        """exe 是**打包产物**，不是启动方式。"""
        text = _doc()
        assert "打包产物" in text
        assert "packaging/build_exe.py" in text


class TestStaleMachineNumbersAreNotHardcoded:
    """框架代码/文档里不该把**本机实测坐标**当常量写下来。

    踩过：捕获区原点一度被写成 ``(1, 31)``（那是 UIPI 受限时的读数），
    而真实值是随窗口位置变的。写死的数字会让人以为是常量。
    """

    def test_backend_docstring_does_not_promise_a_fixed_origin(self):
        source = (ROOT / "src/gamebot/atomic/backends/windows.py").read_text(encoding="utf-8")
        assert "本机实测是 ``(1, 31)``" not in source

    def test_schema_docstring_does_not_promise_a_fixed_origin(self):
        source = (ROOT / "src/gamebot/config/schema.py").read_text(encoding="utf-8")
        assert "+ (1, 31)" not in source


class TestScriptKeysMentionedAreReal:
    """文档里的脚本 key 要真的能查到 —— 写错了读者第一步就卡住。"""

    def test_the_jingji_key_exists(self):
        from games import get_script

        assert "mingjiangsha/jingji" in _doc()
        spec = get_script("mingjiangsha/jingji")
        assert spec.key == "mingjiangsha/jingji"
        assert spec.title
