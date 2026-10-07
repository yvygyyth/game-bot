"""打包成 exe。**没有参数，直接跑就行。**

    uv run python packaging/build_exe.py

跑完会给你一个 ``gamebot.exe``（在项目根），双击它就能开界面。

## 为什么是 exe

之前试过 ``.bat`` / ``.ps1`` / ``.vbs`` 三种启动器，都卡在同一件事上：
**要提权，而提权需要一个控制台子系统的程序当入口**（``powershell.exe`` /
``cmd.exe``）—— 那种程序一运行就分配控制台窗口，双击必闪黑窗口。

exe 一次解决两件事：

* ``--windowed`` → **GUI 子系统**（不分配控制台）；
* ``--uac-admin`` → 嵌入 **UAC 清单**（双击自动请求提权）。

所以双击 → 弹 UAC → 点"是" → 界面出来，没有黑窗口、没有中间脚本。
（这套参数来自同机器的 ``vision_workflow`` 项目。）

## 什么时候要重新打包

* **改了 ``src/gamebot/`` 或 ``games/`` 里的代码** → 要重跑本脚本；
* **改了模板 / 脚本定义 / 日志** → **不用** —— 它们不在 exe 里，
  留在项目目录里，改完立刻生效。
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "packaging" / "entry.py"
DIST = ROOT / "dist"
APP_NAME = "gamebot"

#: 显式全量收这些包 —— PyInstaller 的自动分析经常漏 Qt 插件、
#: pynput 的平台后端、cv2 的二进制。
COLLECT_ALL = ("PySide6", "pynput", "cv2")

#: 这些是**延迟 import** 的，静态分析看不到，必须点名。
HIDDEN_IMPORTS = (
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "win32gui",
    "win32api",
    "win32con",
    "win32clipboard",
    "pydirectinput",
    "mss",
)

#: 不打包（省体积，它们只是被间接依赖到）
EXCLUDES = ("tkinter", "matplotlib", "pytest", "IPython", "PyQt5", "PyQt6")


def build() -> Path:
    if not _has_pyinstaller():
        print("✗ 没装 PyInstaller。先跑一次：")
        print("      uv sync")
        raise SystemExit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",  # GUI 子系统：不分配控制台（"没有黑窗口"的关键）
        "--uac-admin",  # 嵌入 UAC 清单：双击自动请求提权
        "--name",
        APP_NAME,
        "--paths",
        str(ROOT / "src"),
        "--distpath",
        str(DIST),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
        "--onedir",  # 比 --onefile 启动快得多（不用每次解压几百 MB）
    ]
    for package in COLLECT_ALL:
        cmd += ["--collect-all", package]
    for module in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", module]
    for module in EXCLUDES:
        cmd += ["--exclude-module", module]
    cmd.append(str(ENTRY))

    print("打包中…（第一次要几分钟，之后快一些）")
    subprocess.check_call(cmd, cwd=ROOT)

    built = DIST / APP_NAME / f"{APP_NAME}.exe"
    # 在项目根放一份副本：双击那份时**工作目录正好是项目根**，
    # 配置里的相对路径（config/、games/、logs/、模板）就都对得上。
    at_root = ROOT / f"{APP_NAME}.exe"
    shutil.copy2(built, at_root)
    return at_root


def _has_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        return False
    return True


def _faults(exe: Path) -> list[str]:
    """产物有没有那两件"没做到就静默失效"的属性。

    它们失败时的表现**看起来完全正常**：程序照跑，只是双击闪一下黑窗口、
    或者点击没反应 —— 都不会报错。所以必须程序化地查。
    """
    data = exe.read_bytes()
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    subsystem = struct.unpack_from("<H", data, e_lfanew + 0x5C)[0]
    faults: list[str] = []
    if subsystem != 2:
        faults.append(
            f"不是 GUI 子系统（Subsystem={subsystem}）—— 双击会闪黑窗口。"
            "打包脚本里的 --windowed 丢了？"
        )
    if b"requestedExecutionLevel" not in data:
        faults.append(
            "没有 UAC 清单 —— 双击不会提权，而权限不够时点击会**静默失效**。"
            "打包脚本里的 --uac-admin 丢了？"
        )
    return faults


def main() -> int:
    exe = build()
    faults = _faults(exe)

    print()
    print("=" * 62)
    print(f"  {exe}")
    print("=" * 62)
    print()
    if faults:
        print("  ✗ 产物有问题：")
        for fault in faults:
            print(f"      - {fault}")
        return 1
    print("  ✓ 双击它就能开界面（会弹 UAC，点「是」）")
    print()
    print("  改了 src/gamebot 或 games 里的代码才需要重跑本脚本；")
    print("  改模板 / 脚本定义不用 —— 它们不在 exe 里。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
