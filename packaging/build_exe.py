"""PyInstaller 打包 —— 产出一个**双击就能用**的 exe。

## 为什么打包成 exe（而不是启动脚本）

之前试过一堆启动器（.bat / .ps1 / .vbs），每个都卡在同一个地方：
**要提权，而提权需要一个控制台子系统的程序当入口** ——
`powershell.exe` / `cmd.exe` 一运行就分配控制台窗口，于是双击会闪一个黑窗口。
（`-WindowStyle Hidden` 发得太晚，盖不住那一瞬。用 `logs/tools/check_subsystem.py`
可以直接看到哪些 exe 是"控制台"子系统。）

**exe 没有这个问题**，因为 PyInstaller 可以把两件事一起做进那个文件里：

* ``--windowed`` —— 生成 **GUI 子系统**的 exe（不分配控制台）；
* ``--uac-admin`` —— 往 exe 里嵌入一份 **UAC 清单**，请求提权。

于是：**双击 → 系统弹 UAC → 点"是" → 界面出来**。
没有黑窗口、没有中间脚本、没有 VBS。

这不是我发明的做法 —— 同机器的另一个项目（``vision_workflow``）就是这么打包的，
它的 ``scripts/build_exe.py`` 是这套参数的出处。

## 为什么 ``--onedir`` 而不是 ``--onefile``

``--onefile`` 每次启动都要把几百 MB 解压到临时目录，冷启动慢得多，而且
杀毒软件更容易误报。``--onedir`` 产出一个文件夹，exe 在里面，启动快。

## 用法

```powershell
uv run python packaging/build_exe.py            # 打包（几分钟）
uv run python packaging/build_exe.py --verify   # 打包后顺便自检
```

产物：``dist/gamebot/gamebot.exe``
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "packaging" / "entry.py"
DIST = ROOT / "dist"
APP_NAME = "gamebot"

#: 要一起打包的第三方包。**显式列出**，因为 PyInstaller 的自动分析对
#: 这几类经常漏：Qt 插件、pynput 的平台后端、cv2 的二进制。
COLLECT_ALL = ("PySide6", "pynput", "cv2")
#: 这些是"延迟 import"的，静态分析看不到，必须点名
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
#: 不打包的东西（省体积；它们只是被间接依赖到）
EXCLUDES = ("tkinter", "matplotlib", "pytest", "IPython", "PyQt5", "PyQt6")


def build(*, one_dir: bool, clean: bool) -> Path:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("✗ 没装 PyInstaller。先跑：uv add --group dev pyinstaller")
        raise SystemExit(1) from None

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        # ``--windowed``：GUI 子系统，**不分配控制台** —— 这是"没有黑窗口"的关键
        "--windowed",
        # ``--uac-admin``：把 UAC 清单嵌进 exe，双击自动请求提权
        # （游戏是提权运行的，不够级别时点击和快捷键会**静默失效**）
        "--uac-admin",
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
    ]
    cmd.append("--onedir" if one_dir else "--onefile")
    if clean:
        cmd.append("--clean")
    for package in COLLECT_ALL:
        cmd += ["--collect-all", package]
    for module in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", module]
    for module in EXCLUDES:
        cmd += ["--exclude-module", module]
    cmd.append(str(ENTRY))

    print("打包中…（第一次要几分钟）")
    print("  " + " ".join(cmd[:8]) + " …")
    subprocess.check_call(cmd, cwd=ROOT)
    exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    print(f"\n完成: {exe}")

    # 在项目根放一份**副本**，这样双击它时工作目录就是项目根。
    #
    # 入口脚本里有"往上找项目根再 chdir"的兜底，但**工作目录本来就对**
    # 要可靠得多：配置里的相对路径（config/、games/、logs/、模板）全部
    # 以工作目录为基准。放一份在根目录 = 双击就落在正确的位置。
    copy = ROOT / f"{APP_NAME}.exe"
    shutil.copy2(exe, copy)
    print(f"另外放了一份在项目根: {copy}（双击这个用）")
    return exe


def verify(exe: Path) -> int:
    """检查产物的三个关键属性 —— 全是"没做到就静默失效"的那类。"""
    import struct

    print()
    print("=== 自检 ===")
    data = exe.read_bytes()
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    subsystem = struct.unpack_from("<H", data, e_lfanew + 0x5C)[0]
    ok = True

    # ① GUI 子系统 = 不弹控制台
    if subsystem == 2:
        print("  ✓ 子系统 = GUI（双击不弹黑窗口）")
    else:
        print(f"  ✗ 子系统 = {subsystem}（不是 GUI）—— 双击会弹黑窗口")
        ok = False

    # ② 内嵌了 UAC 清单 = 双击自动提权
    if b"requestedExecutionLevel" in data:
        print("  ✓ 内嵌了 UAC 清单（双击会请求提权）")
    else:
        print("  ✗ 没有 UAC 清单 —— 不会提权，点击会静默失效")
        ok = False

    # ③ 大小别离谱
    size_mb = exe.stat().st_size / 1e6
    print(f"  · exe 本身 {size_mb:.1f} MB（依赖在旁边那个文件夹里）")

    print()
    print("  ✓ 可以双击了" if ok else "  ✗ 有问题，见上面")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 gamebot.exe")
    parser.add_argument("--onefile", action="store_true", help="打成单个文件（启动慢）")
    parser.add_argument("--no-clean", action="store_true", help="不清理 build 缓存")
    parser.add_argument("--verify", action="store_true", help="打包后自检产物")
    args = parser.parse_args()

    exe = build(one_dir=not args.onefile, clean=not args.no_clean)
    if args.verify:
        return verify(exe)

    print()
    print("双击它就能开界面（会弹 UAC，点「是」）。")
    print("想自检产物属性：uv run python packaging/build_exe.py --verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
