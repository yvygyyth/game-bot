"""打包成 exe 的入口 —— PyInstaller 从这里开始。

## 为什么单独一个文件

PyInstaller 要一个**脚本**当入口，而这个脚本要在 ``src`` 不在 ``sys.path``
的情况下也能跑（打包时还没装）。

## 为什么要锚定项目根（`chdir`）

配置里的路径（``config/app.yaml``、``games/``、``logs/``、模板）都是
**相对项目根**的 —— 见 :class:`gamebot.config.schema.PathsConfig`。
而**双击 exe 时当前工作目录是 exe 所在目录**，不是项目根：

* 源码运行时没问题（你总在项目目录里敲命令）；
* 双击 ``dist\\gamebot\\gamebot.exe`` 时工作目录是 ``dist\\gamebot\\`` ——
  于是找不到 ``config/``，出来一个"配置文件不存在"。

所以启动时先找出项目根并 ``chdir`` 过去。找不到就**不动**（宁可报原本的错，
也不要瞎猜一个目录）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: 项目根的标志：这几个同时在，基本可以确定
_MARKERS = ("pyproject.toml", "config", "games")


def _find_project_root(start: Path) -> Path | None:
    """从 ``start`` 往上找带标志文件的那一层。找不到返回 ``None``。"""
    current = start.resolve()
    for _ in range(6):  # 往上最多找 6 层，够覆盖 dist/gamebot/ 这种
        if all((current / marker).exists() for marker in _MARKERS):
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def _anchor_working_directory() -> None:
    """把工作目录挪到项目根（找不到就不动）。"""
    candidates = [Path.cwd()]
    if getattr(sys, "frozen", False):
        # 打包后：exe 所在目录（--onedir 时依赖都在它旁边）
        candidates.insert(0, Path(sys.executable).parent)
    else:
        candidates.insert(0, Path(__file__).resolve().parents[1])
    for candidate in candidates:
        root = _find_project_root(candidate)
        if root is not None:
            if Path.cwd() != root:
                os.chdir(root)
            return


_anchor_working_directory()

# 源码目录（打包时和源码运行时都要能找到 gamebot）。
# 打包后 gamebot 在 sys.path 里（PyInstaller 收进去了），这一步是给源码运行用的。
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gamebot.__main__ import main  # noqa: E402

if __name__ == "__main__":
    # 不带参数 = 开界面（双击 exe 的默认行为）
    raise SystemExit(main(sys.argv[1:] or ["ui"]))
