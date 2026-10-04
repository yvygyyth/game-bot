"""Windows 桌面后端：mss 截图 + pydirectinput / pyautogui 输入。

适用：PC 游戏（窗口化 / 无边框）、PC 客户端。

要点与坑：

* **DPI 感知必须最先设置**，且要在导入任何 GUI 库之前 —— 否则 125% 缩放下
  截出来的是"虚拟像素"，坐标全错。见 ``enable_dpi_awareness()``。
* 优先 ``pydirectinput``：它走 scan code，能被 DirectInput 游戏收到；
  ``pyautogui`` 发的是虚拟键码，一部分游戏（尤其是 Unity / 虚幻全屏）收不到。
  ``pydirectinput`` 只支持主键区 + 部分功能键，组合键受限，所以做成可切换。
* 窗口截图统一走 **屏幕坐标裁剪**（mss 直接抓窗口在屏幕上的矩形），
  而不是 ``PrintWindow`` —— 后者对硬件加速渲染的游戏经常抓到黑屏。
  代价：窗口被遮挡时会抓到遮挡物，因此运行时应保持游戏窗口置顶。
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Any

from ...exceptions import BackendUnavailable
from ...types import Point, Region
from ...utils.logging import get_logger
from .base import BackendBundle, WindowInfo

if TYPE_CHECKING:
    import numpy as np

log = get_logger("backends.windows")

__all__ = [
    "WindowsInputBackend",
    "WindowsScreenBackend",
    "WindowsWindowBackend",
    "build_windows_backends",
    "enable_dpi_awareness",
]


def enable_dpi_awareness() -> None:
    """声明进程 DPI 感知（Per-Monitor V2 优先）。

    必须在创建任何窗口 / 抓屏句柄之前调用。Windows 非 win32 平台上静默返回。
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            log.warning("DPI 感知设置失败，缩放比例非 100%% 时坐标可能偏移")


class WindowsWindowBackend:
    """基于 win32gui 的窗口发现。"""

    def list_windows(self, keyword: str = "") -> list[WindowInfo]:
        raise NotImplementedError("待实现：EnumWindows + GetWindowText + GetWindowRect")

    def find_window(self, title_pattern: str) -> WindowInfo | None:
        raise NotImplementedError("待实现：标题包含匹配，取第一个可见窗口")


class WindowsScreenBackend:
    """mss 截图后端。

    :param window_title: 非空时只抓该窗口客户区；为空则抓整个显示器。
    :param monitor_index: mss 的显示器序号，``1`` 是主屏。
    :param client_area_only: True 只抓客户区（不含标题栏 / 边框）。
    """

    name = "mss"

    def __init__(
        self,
        *,
        window_title: str = "",
        monitor_index: int = 1,
        client_area_only: bool = True,
    ) -> None:
        if sys.platform != "win32":
            raise BackendUnavailable("windows 后端只能在 Windows 上使用")
        enable_dpi_awareness()
        try:
            import mss  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise BackendUnavailable("缺少 mss，请执行: uv sync") from exc
        self.window_title = window_title
        self.monitor_index = monitor_index
        self.client_area_only = client_area_only
        self._sct: Any = None
        self._window: WindowsWindowBackend | None = None
        self._region: Region | None = None

    def screen_size(self) -> tuple[int, int]:
        raise NotImplementedError("待实现：读 mss monitors[monitor_index] 或窗口客户区尺寸")

    def grab(self, region: Region | None = None) -> np.ndarray:
        raise NotImplementedError(
            "待实现：region 为源分辨率坐标，需叠加窗口在屏幕上的偏移；返回 BGR 副本"
        )

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None


class WindowsInputBackend:
    """输入后端。

    :param engine: ``"direct"`` 用 pydirectinput（游戏兼容好），``"pyautogui"`` 用通用实现。
    """

    name = "windows-input"

    def __init__(self, *, engine: str = "direct") -> None:
        if sys.platform != "win32":
            raise BackendUnavailable("windows 后端只能在 Windows 上使用")
        self.engine = engine
        self._impl: Any = None

    def _load(self) -> Any:
        if self._impl is not None:
            return self._impl
        module = "pydirectinput" if self.engine == "direct" else "pyautogui"
        try:
            self._impl = __import__(module)
        except ImportError as exc:
            raise BackendUnavailable(
                f"缺少 {module}，请执行: uv sync --extra windows"
            ) from exc
        self._impl.FAILSAFE = False  # 防止鼠标撞到屏幕角落时抛异常打断脚本
        self._impl.PAUSE = 0
        return self._impl

    def move_to(self, point: Point, duration: float = 0.2) -> None:
        raise NotImplementedError("待实现：impl.moveTo(x, y, duration=duration)")

    def click(
        self,
        point: Point,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
    ) -> None:
        raise NotImplementedError("待实现：先 move_to 再 click，注意 clicks/interval 语义")

    def drag(
        self,
        start: Point,
        end: Point,
        *,
        duration: float = 0.5,
        button: str = "left",
    ) -> None:
        raise NotImplementedError(
            "待实现：mouseDown -> 分步 moveTo -> mouseUp（一步到位游戏常不认）"
        )

    def scroll(self, clicks: int, point: Point | None = None) -> None:
        raise NotImplementedError("待实现：先 moveTo(point) 再 scroll(clicks)")

    def type_text(self, text: str, *, interval: float = 0.05) -> None:
        raise NotImplementedError("待实现：注意中文需要走剪贴板粘贴，pyautogui 打不出中文")

    def press_key(self, key: str, *, presses: int = 1, interval: float = 0.1) -> None:
        raise NotImplementedError("待实现：按键名映射，见 docs 的 key map")

    def hotkey(self, keys: list[str]) -> None:
        raise NotImplementedError("待实现：pydirectinput 组合键支持有限，需要 fallback")

    def close(self) -> None:
        self._impl = None


def build_windows_backends(
    *,
    window_title: str = "",
    monitor_index: int = 1,
    client_area_only: bool = True,
    input_engine: str = "direct",
    **_ignored: Any,
) -> BackendBundle:
    """装配 Windows 三件套。"""
    return BackendBundle(
        screen=WindowsScreenBackend(
            window_title=window_title,
            monitor_index=monitor_index,
            client_area_only=client_area_only,
        ),
        input=WindowsInputBackend(engine=input_engine),
        window=WindowsWindowBackend(),
    )


def _sleep(seconds: float) -> None:  # pragma: no cover - 预留
    time.sleep(seconds)
