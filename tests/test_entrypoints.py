"""开发/使用入口：``dev.ps1``、``启动界面.ps1``、``games doctor``。

## 为什么值得有测试

这一层是"环境和权限"的入口，而这类问题的**失败是静默的**：

* 权限级别不够时，程序退出码 0、识别命中、动作返回 `success`，
  **只有游戏没反应** —— 和"坐标算错了"长得一模一样；
* 启动器里用错一个 API（比如 Windows PowerShell 5.1 上不存在的
  ``ArgumentList``）会**把参数全丢掉**：进程起来了、什么都没做、立刻退出。

已经踩过的坑都在下面钉着，免得改回去。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _code_lines(relative: str) -> str:
    """只取**代码行**，去掉注释和块注释。

    为什么需要：这两个脚本的注释里**解释了那些坑的名字**
    （"5.1 上没有 ``ArgumentList``"、"不要用 ``RedirectStandardOutput``"）——
    直接搜全文会把说明文字当成违规。而且那种"注释里提了就报错"的检查
    会逼着人删掉解释，反而更糟。
    """
    out: list[str] = []
    in_block = False
    for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if in_block:
            if "#>" in stripped:
                in_block = False
            continue
        if stripped.startswith("<#"):
            if "#>" not in stripped:
                in_block = True
            continue
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


class TestDoctorCommandIsWired:
    """``games doctor`` —— 跑真机脚本前的环境自检。"""

    def test_the_module_exists(self):
        assert (ROOT / "games" / "doctor.py").is_file()

    def test_it_is_registered_in_the_cli(self):
        source = _source("games/__main__.py")
        assert "register_doctor" in source, "子命令没挂上"
        assert '"doctor": cmd_doctor' in source, "处理器没注册"

    def test_the_parser_accepts_the_script_key(self):
        """``doctor <脚本>`` —— 和 check / describe 一样收一个脚本 key。"""
        from games.__main__ import build_parser

        args = build_parser().parse_args(["doctor", "mingjiangsha/jingji"])
        assert args.command == "doctor"
        assert args.script == "mingjiangsha/jingji"

    def test_it_checks_the_things_that_fail_silently(self):
        """它必须覆盖那几件"静默失效"的事 —— 否则等于没查。"""
        source = _source("games/doctor.py")
        for needed in (
            "check_integrity",       # 权限级别（UIPI）
            "GetForegroundWindow",   # 窗口在不在前台
            "template_roots",        # 模板读不读得到
            "capture",               # 抓屏通不通
        ):
            assert needed in source, f"doctor 没有检查 {needed}"

    def test_it_returns_non_zero_when_there_are_problems(self):
        """有问题要**非零退出** —— 否则 CI / 脚本里看不出来。"""
        source = _source("games/doctor.py")
        assert "return 1" in source
        assert "return 0" in source


class TestDevLauncher:
    """``dev.ps1`` —— 开发终端（自动提权 + 装好环境）。"""

    def test_it_exists(self):
        assert (ROOT / "dev.ps1").is_file()

    def test_it_checks_the_integrity_level(self):
        source = _source("dev.ps1")
        assert "Get-IntegrityLevel" in source
        assert "RunAs" in source, "级别不够时要能自动提权"

    def test_it_puts_the_venv_on_the_path(self):
        """不靠 ``uv``、也不靠 ``activate`` 脚本 —— 直接加 PATH 最稳。"""
        source = _source("dev.ps1")
        assert r".venv\Scripts" in source
        assert "VIRTUAL_ENV" in source

    def test_it_maps_nonzero_to_one(self):
        """退出码归一成 1。

        原样传 ``-1`` 出去时，有些调用方只看低字节会当成成功。
        "非零 = 失败"这个约定必须是可靠的。
        """
        source = _source("dev.ps1")
        assert "exit 1" in source
        assert "exit 0" in source

    def test_it_points_at_doctor(self):
        """开发终端里要提示"跑真机前先 doctor"。"""
        source = _source("dev.ps1")
        assert "doctor" in source

    def test_it_does_not_use_the_ps7_only_api(self):
        """``ArgumentList`` 在 Windows PowerShell 5.1 上不存在。

        用了它会抛 "You cannot call a method on a null-valued expression"，
        **参数全部丢掉** —— 进程起来了、什么都没做、立刻退出。
        这个坑在 ``启动界面.ps1`` 里踩过，别在 ``dev.ps1`` 里再踩。
        """
        for name in ("dev.ps1", "启动界面.ps1"):
            assert ".ArgumentList" not in _code_lines(name), (
                f"{name} 的**代码**里用了只存在于 PowerShell 7 的 ArgumentList"
            )


class TestGuiLauncher:
    """``启动界面.ps1`` —— 双击一次就开，无控制台窗口，自动提权。"""

    def test_it_exists(self):
        assert (ROOT / "启动界面.ps1").is_file()

    def test_it_uses_pythonw_not_python(self):
        """``python.exe`` 是控制台程序 —— 双击会先弹一个黑窗口。

        ``pythonw.exe`` 是同一个解释器的无控制台版本。
        """
        source = _source("启动界面.ps1")
        assert "pythonw.exe" in source

    def test_it_requests_elevation(self):
        """游戏是提权运行的，不够就必须提权 —— 而且失败是静默的，
        不能指望用户自己记得去右键。"""
        source = _source("启动界面.ps1")
        assert "Get-IntegrityLevel" in source
        assert "RunAs" in source

    def test_it_does_not_redirect_output(self):
        """**不要在这里做输出重定向。**

        ``Start-Process -RedirectStandardOutput`` 和 ``.NET Process.Start``
        配 ``RedirectStandard*`` 都会**等到子进程退出**才返回 ——
        对 GUI 就是永远不返回（实测卡 300 秒 / 45 秒），
        留下一个看不见但永不退出的脚本进程。

        日志改成应用自己写文件（``pythonw -m gamebot ui`` 写 ``logs/ui.log``）。
        """
        code = _code_lines("启动界面.ps1")
        assert "RedirectStandardOutput" not in code
        assert "RedirectStandardError" not in code

    def test_ui_writes_its_own_log_file(self):
        """上面那条的前提：界面自己写日志文件。"""
        source = _source("src/gamebot/__main__.py")
        assert "logs/ui.log" in source or "ui.log" in source
        assert "log_file" in source


class TestIntegrityModuleIsUsed:
    """权限判据要接在**用户一定会看到**的地方。"""

    def test_bootstrap_warns_at_assembly_time(self):
        source = _source("src/gamebot/bootstrap.py")
        assert "check_integrity" in source

    def test_cli_reports_it(self):
        source = _source("games/poke.py")
        assert "check_integrity" in source

    def test_gui_shows_it_in_the_log_panel(self):
        source = _source("src/gamebot/ui/window.py")
        assert "_warn_about_integrity" in source

    def test_the_module_parses_cleanly(self):
        """顺手确认没有语法问题（这个模块用 ctypes，容易写错）。"""
        tree = ast.parse(_source("src/gamebot/utils/integrity.py"))
        names = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        assert {"check_integrity", "level_of_pid", "level_of_window"} <= names


class TestWindowsPowerShellCompatibility:
    """这两个脚本会在 **Windows PowerShell 5.1** 下跑（双击/快捷方式）。

    5.1 的 .NET 是 Framework，比 PowerShell 7 少一批 API。
    用错不会有明确报错，往往是"静默不生效" —— 所以在这里拦。
    """

    @pytest.mark.parametrize("name", ["dev.ps1", "启动界面.ps1"])
    def test_no_ps7_only_cmdlets(self, name: str):
        code = _code_lines(name)
        # ``$PSCommandPath`` 在 5.1 有；这几个是 7 才稳的
        for banned in ("$PSNativeCommandUseErrorActionPreference", "ForEach-Object -Parallel"):
            assert banned not in code, f"{name} 的代码里用了 PowerShell 7 专属的写法"

    @pytest.mark.parametrize("name", ["dev.ps1", "启动界面.ps1"])
    def test_files_are_utf8_with_bom_awareness(self, name: str):
        """脚本里全是中文，**必须能按 UTF-8 解析**（不然双击就是一堆乱码）。

        这里只验证文件本身是合法 UTF-8 —— 编码在 Windows 上还有别的坑
        （``.bat`` 的 GBK/chcp），所以那两个启动器刻意用 ``.ps1`` 而不是 ``.bat``。
        """
        data = (ROOT / name).read_bytes()
        data.decode("utf-8")  # 抛异常就是编码坏了
