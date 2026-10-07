"""文档里写的命令必须**真的存在**。

## 为什么要测文档

安装/启动文档最容易烂掉的地方是**命令**：子命令改名了、参数删了、
`uv sync` 的组合变了 —— 文档不会报错，只会在别人照着做的时候失败。
而"照文档做不通"是最伤人的一类问题（读者会先怀疑自己）。

所以这里把 `docs/getting-started.md` 里出现的每条命令**提出来，
拿去和真实 CLI 的解析器对一遍**：

* 子命令存在吗？
* 它收的那些 ``--flag`` 真的收吗？

不执行命令（那要连游戏），只做**签名校验**。
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "getting-started.md"

#: 文档里会出现、但不是我们要校验的命令（shell 内建 / 第三方）
SKIP = {
    "winget", "cd", "Remove-Item", "uv", "pytest", "ruff", "mypy",
    "python", "pip", "echo", "uv run pytest", "uv run ruff", "uv run mypy",
}


def _doc() -> str:
    assert DOC.is_file(), f"文档不见了: {DOC}"
    return DOC.read_text(encoding="utf-8")


def _code_blocks(text: str) -> list[str]:
    """把 ``` 围起来的代码块内容取出来。"""
    return re.findall(r"```[a-z]*\n(.*?)```", text, re.S)


class TestDocExistsAndIsReadable:
    def test_the_doc_is_where_we_think(self):
        assert DOC.is_file()

    def test_it_covers_the_four_things_the_user_asked_for(self):
        """用户要的是"依赖安装、启动方式什么的"。四件事都得有。"""
        text = _doc()
        for topic in ("依赖", "启动", "命令", "出问题"):
            assert topic in text, f"文档里没有讲 {topic!r}"


def _subcommands(parser) -> set[str]:
    """解析器上注册了哪些子命令。

    不去跑 ``parse_args(["x", "--help"])`` —— 那会 ``SystemExit``，
    测试里要额外捕获，而且它测的是"help 能不能跑"而不是"子命令存在吗"。
    直接读 choices 更直白。
    """
    for action in parser._actions:
        if getattr(action, "choices", None) and action.dest == "command":
            return set(action.choices)
    return set()


def _documented_games_lines(text: str) -> list[str]:
    """文档里**作为命令出现**的 ``python -m games ...`` 行。

    ## 只认"以命令开头"的行

    正文里也会内联提到命令（"然后 `python -m games run ...`"、表格里
    `python -m games doctor <脚本>`），那些**不是**可执行的例子 ——
    第一版按"行里含 games "取，结果把 markdown 列表项也当成命令，
    报出"子命令是 `*`"这种噪音。**提取器太松，测试就成了噪音源。**

    ## 必须按行取，不能只断言"文档里含 doctor"

    试过：把 ``python -m games doctor`` 改成 ``diagnose``，只断言"含 doctor"
    的测试照样绿 —— 因为 ``dev.ps1`` 那一段里还有 ``doctor``。
    **测试的强度取决于它多具体。**
    """
    prefixes = ("uv run python -m games ", "python -m games ", "$ python -m games ")
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        line = line.split("#", 1)[0].strip()  # 去掉行尾注释
        if line.startswith(prefixes):
            out.append(line)
    return out


class TestDocumentedGamesCommandsAreValid:
    """**逐条**解析文档里的 ``python -m games ...`` 命令行。"""

    def test_there_are_some(self):
        lines = _documented_games_lines(_doc())
        assert len(lines) >= 4, f"只找到 {len(lines)} 条 games 命令，文档结构变了吗？"

    def test_every_games_line_parses(self):
        """每条都要被**真实解析器接受**。

        这比"文档里含某个词"强得多：它要求 ``games diagnose k`` 这种写法
        被 argparse 认可 —— 而它不会被认可（注册的名字是 ``doctor``）。
        """
        from games.__main__ import build_parser

        parser = build_parser()
        bad: list[str] = []
        for line in _documented_games_lines(_doc()):
            argv = line
            for prefix in ("uv run python -m games ", "python -m games ", "$ "):
                if argv.startswith(prefix):
                    argv = argv[len(prefix) :]
            # 占位符换成真值
            for placeholder, value in (("<脚本>", "k"), ("<x>", "1"), ("<y>", "2")):
                argv = argv.replace(placeholder, value)
            try:
                parser.parse_args(argv.split())
            except SystemExit:
                bad.append(line)
        assert not bad, "这些命令解析不过（子命令或参数写错了）:\n" + "\n".join(
            f"    {b}" for b in bad
        )

    def test_the_subcommands_appear_in_real_commands(self):
        """每个子命令都要出现在**某条命令行**里，而不只是正文提到。"""
        commands = " ".join(_documented_games_lines(_doc()))
        for sub in ("doctor", "check", "run", "describe", "list"):
            assert f"games {sub}" in commands, f"文档里没有一条 `games {sub}` 命令"

    def test_the_gamebot_subcommands_appear_in_real_commands(self):
        """文档里给出的 ``gamebot`` 命令必须真的是**命令行**，不是正文提及。

        这里**不要求把每个子命令都列出来** —— 文档有意只给日常用得上的三条
        （``info`` / ``windows`` / ``capture``），其余（``check`` / ``run`` /
        ``ui`` / ``grab``）在 `gamebot --help` 里看。要求"全列"会逼着文档
        堆命令，那是反效果。
        """
        commands = " ".join(
            line.strip()
            for line in _doc().splitlines()
            if "gamebot " in line and not line.strip().startswith(("#", "|"))
        )
        assert commands, "文档里一条 gamebot 命令都没有"
        for sub in ("ui", "info", "windows", "capture"):
            assert f"gamebot {sub}" in commands, f"文档里没有一条 `gamebot {sub}` 命令"

    def test_no_documented_subcommand_is_invented(self):
        """反过来：文档里的 ``games <词>`` 必须都是**已注册**的子命令。"""
        from games.__main__ import build_parser

        known = _subcommands(build_parser())
        for line in _documented_games_lines(_doc()):
            argv = line
            for prefix in ("uv run python -m games ", "python -m games ", "$ "):
                if argv.startswith(prefix):
                    argv = argv[len(prefix) :]
            parts = argv.split()
            first = parts[0] if parts else ""
            assert first in known, f"文档里写了没注册的子命令 {first!r}: {line}"


class TestDocumentedFlagsExist:
    """文档里举例用到的 ``--flag`` 必须真的被那个子命令接受。"""

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            # games run 的那些
            (["run", "k", "--dry-run"], {"dry_run": True}),
            (["run", "k", "--max-ticks", "5"], {"max_ticks": 5}),
            (["run", "k", "--param", "rounds=5"], {"param": ["rounds=5"]}),
            # doctor / poke / where 的
            (["describe", "k"], {"script": "k"}),
            (["check", "k"], {"script": "k"}),
        ],
    )
    def test_games_flags(self, argv, expected):
        from games.__main__ import build_parser

        args = build_parser().parse_args(argv)
        for key, want in expected.items():
            assert getattr(args, key) == want, f"{argv} -> {key}"

    @pytest.mark.parametrize(
        ("argv", "key"),
        [
            (["ui", "--snapshot", "x.png"], "snapshot"),
            (["ui", "--script", "k"], "script"),
            (["ui", "-c", "c.yaml"], "config"),
            (["capture", "-o", "a.png"], "out"),
            (["grab", "--region", "1,2,3,4"], "region"),
            (["info", "--json"], "json"),
            (["run", "--dry-run"], "dry_run"),
            (["run", "--window", "w"], "window"),
            (["run", "--no-journal"], "no_journal"),
        ],
    )
    def test_gamebot_flags(self, argv, key):
        from gamebot.__main__ import build_parser

        args = build_parser().parse_args(argv)
        assert getattr(args, key) is not None

    def test_the_documented_uv_sync_combo_is_the_one_we_need(self):
        """文档反复强调"两个 extra 要一起给"。

        这条钉的是：**那两个 extra 真的存在**（名字写错了的话，
        `uv sync --extra windows --extra ui` 会直接失败）。
        """
        import tomllib

        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        extras = data["project"]["optional-dependencies"]
        assert "windows" in extras
        assert "ui" in extras
        doc = _doc()
        assert "--extra windows --extra ui" in doc, "文档里那句组合命令不见了"


class TestScriptKeysMentionedAreReal:
    """文档里的脚本 key 要真的能查到 —— 写错了读者第一步就卡住。"""

    def test_the_jingji_key_exists(self):
        from games import get_script

        assert "mingjiangsha/jingji" in _doc()
        spec = get_script("mingjiangsha/jingji")
        assert spec.key == "mingjiangsha/jingji"
        assert spec.title


class TestUipiSectionIsPresent:
    """权限那一节是这份文档**最重要**的部分。

    整个排查过程说明：级别不够时一切都是静默失效的，
    而人（包括我）会先去怀疑坐标和模板。所以文档必须把这一节放在最前面，
    并且把三条典型症状写全。
    """

    def test_it_explains_why_admin_is_needed(self):
        text = _doc()
        assert "UIPI" in text
        assert "完整性级别" in text

    def test_it_lists_the_silent_failure_symptoms(self):
        text = _doc()
        # 三条症状：鼠标会动、点击不生效、失焦热键不灵
        assert "静态失效" in text or "静默失效" in text
        assert "点击" in text
        assert "快捷键" in text

    def test_it_says_tests_do_not_need_admin(self):
        """免得每次改点代码都去提权。"""
        text = _doc()
        assert "pytest" in text
        assert "不用" in text

    def test_the_startup_command_comes_first(self):
        """**启动命令必须在最前面** —— 用户原话：

        > "启动命令呢，我写其他项目都是启动命令运行的，exe都是打包后的产物"

        所以文档第一屏要能直接抄到那条命令，而不是先讲一大段权限。
        权限那节仍然要在（它是这次排查最重要的结论），但**在命令之后**。
        """
        text = _doc()
        startup = text.index("uv run python -m gamebot ui")
        admin = text.index("## 1.")
        assert startup < admin, "启动命令必须排在讲权限之前"
        # 前 1/4 里就该有那条命令（第一屏能抄到）
        assert startup < len(text) // 4, "启动命令太靠后了，第一屏看不到"

    def test_it_says_the_startup_command_needs_no_admin(self):
        """**一条普通命令就能跑** —— 这是用户明确要的。

        不能写成"必须先管理员"：改代码、跑测试、空跑都不需要提权，
        那样写会让人觉得每次启动都得过 UAC。
        """
        text = _doc()
        assert "普通权限就能跑" in text or "不用" in text
        assert "uv run python -m gamebot ui" in text

    def test_it_says_when_admin_is_actually_needed(self):
        """但"真点游戏"确实需要 —— 那张表要把两种情况分开。"""
        text = _doc()
        assert "真跑" in text
        assert "\\dev.ps1" in text

    def test_the_uipi_section_still_exists(self):
        """权限那节不能因为"命令优先"就被删掉 —— 它是静默失效的唯一解释。"""
        text = _doc()
        uipi = text.index("UIPI")
        assert "完整性级别" in text
        assert "静默失效" in text
        assert uipi > text.index("uv run python -m gamebot ui")

    def test_the_exe_is_marked_as_a_build_artifact(self):
        """exe 是**打包产物**，不是启动方式 —— 别再把它写成主路径。"""
        text = _doc()
        assert "打包产物" in text
        assert "packaging/build_exe.py" in text


class TestStaleMachineNumbersAreNotHardcoded:
    """框架代码/文档里不该把**本机实测坐标**当常量写下来。

    踩过：捕获区原点一度被写成 ``(1, 31)``（那是 UIPI 受限时的读数），
    而真实值是随窗口位置变的。写死的数字会让人以为是常量。
    """

    def test_backend_docstring_does_not_promise_a_fixed_origin(self):
        source = (ROOT / "src/gamebot/atomic/backends/windows.py").read_text(
            encoding="utf-8"
        )
        assert "本机实测是 ``(1, 31)``" not in source

    def test_schema_docstring_does_not_promise_a_fixed_origin(self):
        source = (ROOT / "src/gamebot/config/schema.py").read_text(encoding="utf-8")
        assert "+ (1, 31)" not in source

    def test_the_doc_points_at_doctor_for_self_check(self):
        """坐标/权限/模板这些"静默失效"的东西，一条 doctor 全查。"""
        assert "games doctor" in _doc()
