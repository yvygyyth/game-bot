"""Android 后端：adb 截图 + ``adb shell input`` 输入。

适用：手游（模拟器 / 真机）。

要点与坑：

* **screencap 很慢**。``adb exec-out screencap -p`` 在模拟器上通常 80~300ms，
  真机更久。所以：
  - 优先 ``exec-out``（少一次换行转换，二进制不会被 CRLF 污染）；
  - 长按 / 拖拽必须自己拆成 ``input swipe x1 y1 x2 y2 duration``，避免多次往返；
  - 帧率上限要显式设低（见 ``max_fps``），否则流程层空转会打满 USB/网络。
* **``input tap`` 有自己的几十毫秒延迟**，连点必须留间隔，否则丢事件。
* **分辨率**：``wm size`` 报的可能是 ``Override size``，要以 screencap 出来的
  实际图像尺寸为准，否则坐标整体偏移。
* 中文输入：``adb shell input text`` 不支持非 ASCII，需要走
  ``adb shell am broadcast`` + ADBKeyboard 之类的输入法，或剪贴板方案。
* 多设备必须显式指定 ``serial``，否则 adb 会报 "more than one device"。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...types import Point, Region
from ...utils.logging import get_logger
from .base import BackendBundle

if TYPE_CHECKING:
    import numpy as np

log = get_logger("backends.android")

__all__ = [
    "AdbClient",
    "AdbInputBackend",
    "AdbScreenBackend",
    "build_android_backends",
]


class AdbClient:
    """adb 命令薄封装。

    :param serial: 设备序列号；多设备时必填。
    :param adb_path: adb 可执行文件路径，默认从 PATH 找。
    """

    def __init__(self, serial: str = "", adb_path: str = "adb", timeout: float = 10.0) -> None:
        self.serial = serial
        self.adb_path = adb_path
        self.timeout = timeout

    def _base_args(self, *args: str) -> list[str]:
        raise NotImplementedError("待实现：拼 [adb, '-s', serial, *args]")

    def run(self, *args: str, binary: bool = False) -> bytes | str:
        raise NotImplementedError("待实现：subprocess.run + 超时 + 错误码检查")

    def exec_out(self, *args: str) -> bytes:
        """``adb exec-out``：拿二进制（截图用）。"""
        raise NotImplementedError("待实现")

    def shell(self, *args: str) -> str:
        """``adb shell``：拿文本输出。"""
        raise NotImplementedError("待实现")

    def devices(self) -> list[str]:
        """列出已连接设备序列号。"""
        raise NotImplementedError("待实现：解析 'adb devices' 输出")

    def connect(self, address: str) -> bool:
        """连接网络设备，如 ``127.0.0.1:5555``（模拟器常用）。"""
        raise NotImplementedError("待实现")


class AdbScreenBackend:
    """adb 截图后端。"""

    name = "adb"

    def __init__(self, client: AdbClient, *, max_fps: float = 5.0) -> None:
        self.client = client
        self.max_fps = max_fps
        self._size: tuple[int, int] | None = None

    def screen_size(self) -> tuple[int, int]:
        raise NotImplementedError("待实现：以 screencap 实际尺寸为准，首次抓到后缓存")

    def grab(self, region: Region | None = None) -> np.ndarray:
        raise NotImplementedError(
            "待实现：exec-out screencap -p -> cv2.imdecode -> 可选裁剪 -> BGR 副本"
        )

    def close(self) -> None:
        return None


class AdbInputBackend:
    """输入后端。坐标是 **设备分辨率**（即源分辨率）。"""

    name = "adb-input"

    def __init__(self, client: AdbClient, *, tap_delay: float = 0.05) -> None:
        self.client = client
        self.tap_delay = tap_delay

    def move_to(self, point: Point, duration: float = 0.2) -> None:
        # Android 没有"悬停"概念，move 是空操作。留着是为了满足协议一致性。
        return None

    def click(
        self,
        point: Point,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
    ) -> None:
        raise NotImplementedError("待实现：input tap x y，连点之间必须 sleep")

    def drag(
        self,
        start: Point,
        end: Point,
        *,
        duration: float = 0.5,
        button: str = "left",
    ) -> None:
        raise NotImplementedError("待实现：input swipe x1 y1 x2 y2 <ms>，毫秒取 duration*1000")

    def scroll(self, clicks: int, point: Point | None = None) -> None:
        raise NotImplementedError("待实现：用短 swipe 模拟滚动，方向与幅度需要按设备标定")

    def type_text(self, text: str, *, interval: float = 0.05) -> None:
        raise NotImplementedError("待实现：仅 ASCII；非 ASCII 需 ADBKeyboard :+1:")

    def press_key(self, key: str, *, presses: int = 1, interval: float = 0.1) -> None:
        raise NotImplementedError("待实现：keyevent 码表，见 docs 的 key map")

    def hotkey(self, keys: list[str]) -> None:
        raise NotImplementedError("Android 无组合键语义，待实现时直接抛/忽略")

    def close(self) -> None:
        return None


def build_android_backends(
    *,
    serial: str = "",
    adb_path: str = "adb",
    max_fps: float = 5.0,
    **_ignored: Any,
) -> BackendBundle:
    """装配 Android 两件套（无窗口概念，``window=None``）。"""
    client = AdbClient(serial=serial, adb_path=adb_path)
    return BackendBundle(
        screen=AdbScreenBackend(client, max_fps=max_fps),
        input=AdbInputBackend(client),
        window=None,
    )
