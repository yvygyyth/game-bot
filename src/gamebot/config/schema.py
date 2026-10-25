"""运行期小对象 —— 路径与后端种类。

业务脚本不再经过 ``AppConfig``：装配从 :class:`~gamebot.feature.FeatureSpec`
直接进 :func:`~gamebot.bootstrap.bootstrap_from_spec`。
这里只留装配还用得到的碎片。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = ["BackendKind", "RunPaths"]


class BackendKind(StrEnum):
    """截图 / 输入后端类型。"""

    WINDOWS = "windows"
    """PC 游戏 / PC 客户端：mss + pydirectinput。"""

    ANDROID = "android"
    """手游模拟器 / 真机：adb。"""

    FAKE = "fake"
    """内存假后端：测试和空跑。"""


@dataclass(frozen=True, slots=True)
class RunPaths:
    """一次运行用到的目录。相对路径一律相对 :attr:`root`。"""

    root: Path
    screenshots: Path
    journals: Path

    @classmethod
    def under(cls, root: Path) -> RunPaths:
        """仓库根下的默认日志布局。"""
        root = Path(root)
        return cls(
            root=root,
            screenshots=root / "logs" / "screenshots",
            journals=root / "logs" / "journals",
        )

    def resolve(self, path: Path | str) -> Path:
        """把相对路径拼到项目根上。"""
        candidate = Path(path)
        return candidate if candidate.is_absolute() else (self.root / candidate)

    def ensure(self) -> None:
        """创建运行期目录。启动时调一次。"""
        for directory in (self.screenshots, self.journals):
            self.resolve(directory).mkdir(parents=True, exist_ok=True)
