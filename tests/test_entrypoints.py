"""开发/使用入口：``dev.ps1``、打包好的 ``gamebot.exe``、``games doctor``。

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
        （这个坑在已经删掉的 ``启动界面.ps1`` 里踩过，别再踩。）
        """
        assert ".ArgumentList" not in _code_lines("dev.ps1"), (
            "dev.ps1 的**代码**里用了只存在于 PowerShell 7 的 ArgumentList"
        )


class TestGuiLauncher:
    """打包成 exe —— **双击一个文件就能开，没有黑窗口**。

    ## 为什么最后选了 exe

    试过 `.bat` / `.ps1` / `.vbs` 三种启动器，都卡在同一件事上：**要提权，
    而提权需要控制台子系统的程序当入口**（`powershell.exe` / `cmd.exe`），
    那种程序一运行就分配控制台窗口 —— 双击必闪黑窗口。
    `-WindowStyle Hidden` 发得太晚，盖不住那一瞬。

    exe 一次解决两件事（PyInstaller 参数）：

    * ``--windowed`` → **GUI 子系统**（不分配控制台）；
    * ``--uac-admin`` → 嵌入 **UAC 清单**（双击自动请求提权）。

    **和 Qt 无关** —— Qt 是纯 GUI 库，用 GUI 子系统的程序启动就没有控制台。

    （这个做法来自同机器的 ``vision_workflow`` 项目，它的
    ``scripts/build_exe.py`` 是这套参数的出处。）
    """

    def test_the_build_script_exists(self):
        assert (ROOT / "packaging" / "build_exe.py").is_file()
        assert (ROOT / "packaging" / "entry.py").is_file()

    def test_it_builds_a_gui_subsystem_exe(self):
        """``--windowed`` 是"没有黑窗口"的全部原因，不能删。"""
        source = _source("packaging/build_exe.py")
        assert '"--windowed"' in source or "'--windowed'" in source

    def test_it_embeds_a_uac_manifest(self):
        """``--uac-admin`` 是"双击自动提权"的全部原因，不能删。

        游戏是提权运行的；级别不够时点击和快捷键**静默失效**。
        """
        source = _source("packaging/build_exe.py")
        assert "--uac-admin" in source

    def test_it_collects_the_packages_pyinstaller_misses(self):
        """Qt 插件 / pynput 平台后端 / cv2 二进制 —— 自动分析经常漏。"""
        source = _source("packaging/build_exe.py")
        for package in ("PySide6", "pynput", "cv2"):
            assert package in source, f"没有 collect-all {package}"

    def test_it_declares_the_delayed_imports(self):
        """这几个是延迟 import 的，静态分析看不到，必须 --hidden-import。"""
        source = _source("packaging/build_exe.py")
        for module in ("pynput.keyboard._win32", "win32gui", "pydirectinput"):
            assert module in source, f"没有 hidden-import {module}"

    def test_the_entry_anchors_the_working_directory(self):
        """**双击 exe 时工作目录是 exe 所在目录**，而配置里的路径
        （``config/``、``games/``、``logs/``、模板）全部相对项目根 ——
        不锚定的话会报"配置文件不存在"。

        实测过：从 ``%TEMP%`` 启动入口脚本，日志照样写进项目根的
        ``logs/ui.log``、快照也生成在项目根。
        """
        source = _source("packaging/entry.py")
        assert "chdir" in source
        assert "pyproject.toml" in source, "找项目根要看标志文件"

    def test_the_entry_defaults_to_the_ui(self):
        """双击不带参数 = 开界面。"""
        source = _source("packaging/entry.py")
        assert 'or ["ui"]' in source

    def test_it_does_not_use_powershell_or_cmd_launchers(self):
        """**不许再引入控制台子系统的启动器。**

        它们一定会闪黑窗口，而且我们已经有了不需要它们的方案。
        """
        for name in ("启动界面.ps1", "启动界面.vbs", "启动界面.bat", "启动界面.cmd"):
            assert not (ROOT / name).exists(), (
                f"{name} 又出现了 —— 控制台子系统的启动器会闪黑窗口，别用它"
            )

    def test_ui_writes_its_own_log_file(self):
        """GUI 子系统没有控制台，日志必须写文件 —— 否则出问题什么都看不到。"""
        source = _source("src/gamebot/__main__.py")
        assert "ui.log" in source
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
    """``dev.ps1`` 会在 **Windows PowerShell 5.1** 下跑。

    5.1 的 .NET 是 Framework，比 PowerShell 7 少一批 API。
    用错不会有明确报错，往往是"静默不生效" —— 所以在这里拦。

    （界面那条链现在是 exe 了，不再经过 PowerShell。）
    """

    def test_no_ps7_only_cmdlets(self):
        code = _code_lines("dev.ps1")
        # ``$PSCommandPath`` 在 5.1 有；这几个是 7 才稳的
        for banned in ("$PSNativeCommandUseErrorActionPreference", "ForEach-Object -Parallel"):
            assert banned not in code, "dev.ps1 的代码里用了 PowerShell 7 专属的写法"

    def test_files_are_utf8_with_bom_awareness(self):
        """``dev.ps1`` 里全是中文，**必须能按 UTF-8 解析**（不然双击就是一堆乱码）。

        编码在 Windows 上还有别的坑（``.bat`` 的 GBK/chcp）—— 那次踩过：
        用 UTF-8 存的 `.bat` 里中文乱码，还把命令行解析错了，报
        "'xxx' is not recognized as an internal or external command"。
        所以启动器一律用 ``.ps1`` 或 exe，不用 ``.bat``。
        """
        for name in ("dev.ps1",):
            data = (ROOT / name).read_bytes()
            data.decode("utf-8")  # 抛异常就是编码坏了

    def test_no_batch_launchers(self):
        """别再引入 ``.bat`` —— 编码坑 + 控制台子系统，两个问题都躲不开。"""
        assert not list(ROOT.glob("*.bat")), "出现了 .bat 启动器"
        assert not list(ROOT.glob("*.cmd")), "出现了 .cmd 启动器"
