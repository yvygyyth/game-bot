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
  实际图像尺寸为准，否则坐标整体偏移。本实现只在没有 screencap 可用时才退回
  ``wm size``。
* 中文输入：``adb shell input text`` 不支持非 ASCII。这里直接给出明确错误，
  要打中文得先装 ADBKeyboard 之类的输入法再自己扩。
* 多设备必须显式指定 ``serial``，否则 adb 会报 "more than one device"。

坐标基准：设备分辨率，原点 = 屏幕左上角。没有窗口概念，所以
``BackendBundle.window`` 是 None。
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import TYPE_CHECKING, Any

from ...exceptions import BackendError, BackendUnavailable
from ...types import Point, Region
from ...utils.logging import get_logger
from .base import BackendBundle

if TYPE_CHECKING:
    import numpy as np

log = get_logger("backends.android")

__all__ = [
    "KEYCODES",
    "AdbClient",
    "AdbInputBackend",
    "AdbScreenBackend",
    "build_android_backends",
]

#: 统一键名 -> Android keyevent 码。业务脚本只用左边的名字。
KEYCODES: dict[str, int] = {
    "home": 3,
    "back": 4,
    "call": 5,
    "endcall": 6,
    "up": 19,
    "dpad_up": 19,
    "down": 20,
    "dpad_down": 20,
    "left": 21,
    "dpad_left": 21,
    "right": 22,
    "dpad_right": 22,
    "center": 23,
    "ok": 23,
    "volume_up": 24,
    "volume_down": 25,
    "power": 26,
    "camera": 27,
    "clear": 28,
    "menu": 82,
    "enter": 66,
    "backspace": 67,
    "del": 67,
    "delete": 67,
    "tab": 61,
    "space": 62,
    "escape": 111,
    "esc": 111,
    "pageup": 92,
    "pagedown": 93,
    "move_home": 122,
    "move_end": 123,
    "app_switch": 187,
}

for _digit in "0123456789":
    KEYCODES[_digit] = 7 + int(_digit)
for _index, _letter in enumerate("abcdefghijklmnopqrstuvwxyz"):
    KEYCODES[_letter] = 29 + _index


class AdbClient:
    """adb 命令薄封装。

    :param serial: 设备序列号；多设备时必填。
    :param adb_path: adb 可执行文件路径，默认从 PATH 找。
    :param timeout: 单条命令超时（秒）。screencap 慢，别给太小。
    """

    def __init__(self, serial: str = "", adb_path: str = "adb", timeout: float = 20.0) -> None:
        self.serial = serial
        self.adb_path = adb_path
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # 命令拼装与执行
    # ------------------------------------------------------------------ #
    def _base_args(self, *args: str) -> list[str]:
        prefix = [self.adb_path]
        if self.serial:
            prefix += ["-s", self.serial]
        return prefix + list(args)

    def run(self, *args: str, binary: bool = False) -> bytes | str:
        """跑一条 adb 命令。

        :raises BackendUnavailable: adb 可执行文件找不到。
        :raises BackendError: 超时或返回码非 0。
        """
        command = self._base_args(*args)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BackendUnavailable(
                f"找不到 adb 可执行文件: {self.adb_path!r}"
                "（装 platform-tools，或改 screen.adb_path）"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"adb 命令超时（{self.timeout}s）: {' '.join(command)}") from exc

        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", "replace").strip()
            raise BackendError(
                f"adb 命令失败（exit {completed.returncode}）: {' '.join(command)}"
                + (f"\n{stderr}" if stderr else "")
            )
        if binary:
            return completed.stdout
        return completed.stdout.decode("utf-8", "replace")

    def exec_out(self, *args: str) -> bytes:
        """``adb exec-out``：拿二进制（截图用）。不经过 pty，PNG 不会被 CRLF 破坏。"""
        result = self.run("exec-out", *args, binary=True)
        assert isinstance(result, bytes)
        return result

    def shell(self, *args: str) -> str:
        """``adb shell``：拿文本输出。"""
        result = self.run("shell", *args)
        assert isinstance(result, str)
        return result

    def devices(self) -> list[str]:
        """列出已连接设备序列号。"""
        output = self.run("devices")
        assert isinstance(output, str)
        serials: list[str] = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    def connect(self, address: str) -> bool:
        """连接网络设备，如 ``127.0.0.1:5555``（模拟器常用）。"""
        output = self.run("connect", address)
        assert isinstance(output, str)
        ok = "connected" in output and "cannot" not in output and "failed" not in output
        if ok and not self.serial:
            # 连上之后后续命令就该指定它，否则多设备时会报 more than one device
            self.serial = address
        return ok

    def ensure_available(self) -> None:
        """启动自检：adb 在不在、设备连没连。装配期调一次，别等跑到一半才发现。"""
        if shutil.which(self.adb_path) is None and not self.adb_path.lower().endswith(".exe"):
            raise BackendUnavailable(f"PATH 里找不到 {self.adb_path!r}")
        devices = self.devices()
        if not devices:
            raise BackendError("adb 没有检测到任何设备（模拟器要先启动 / 真机要开 USB 调试）")
        if self.serial and self.serial not in devices:
            raise BackendError(f"设备 {self.serial!r} 不在已连接列表里: {devices}")
        if not self.serial and len(devices) > 1:
            raise BackendError(f"连接了多个设备 {devices}，必须显式指定 screen.serial")


class AdbScreenBackend:
    """adb 截图后端。

    :param max_fps: 帧率上限。**必须设**：不限制的话流程层空转会把
        adb 通道打满，反而让每次截图更慢。
    """

    name = "adb"

    def __init__(self, client: AdbClient, *, max_fps: float = 5.0) -> None:
        self.client = client
        self.max_fps = max_fps
        self._size: tuple[int, int] | None = None
        self._last_grab = 0.0

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _decode(self, payload: bytes) -> np.ndarray:
        import cv2
        import numpy as np

        if not payload:
            raise BackendError("screencap 返回空数据（设备可能已断开）")
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise BackendError(
                "screencap 结果无法解码。常见原因：用了 `shell screencap` 导致 "
                "PNG 被 CRLF 破坏 —— 应该走 `exec-out`。"
            )
        return image

    def _throttle(self) -> None:
        if self.max_fps <= 0:
            return
        minimum = 1.0 / self.max_fps
        wait = minimum - (time.monotonic() - self._last_grab)
        if wait > 0:
            time.sleep(wait)

    def _capture(self) -> np.ndarray:
        self._throttle()
        image = self._decode(self.client.exec_out("screencap", "-p"))
        self._last_grab = time.monotonic()
        return image

    # ------------------------------------------------------------------ #
    # 协议
    # ------------------------------------------------------------------ #
    def screen_size(self) -> tuple[int, int]:
        """以 screencap 实际尺寸为准，首次抓到后缓存。

        ``wm size`` 会同时报 Physical / Override 两个值，解析容易翻车，
        所以只在 screencap 不可用时才退回它。
        """
        if self._size is None:
            try:
                image = self._capture()
                self._size = (int(image.shape[1]), int(image.shape[0]))
            except BackendError:
                self._size = self._size_from_wm()
        return self._size

    def _size_from_wm(self) -> tuple[int, int]:
        output = self.client.shell("wm", "size")
        size: tuple[int, int] | None = None
        for line in output.splitlines():
            if "size:" not in line:
                continue
            token = line.split("size:")[-1].strip()  # Override 通常在后一行，取最后一个
            if "x" in token:
                width, _, height = token.partition("x")
                if width.strip().isdigit() and height.strip().isdigit():
                    size = (int(width), int(height))
        if size is None:
            raise BackendError(f"无法确定设备分辨率，wm size 输出: {output!r}")
        return size

    def grab(self, region: Region | None = None) -> np.ndarray:
        """抓一帧。

        :param region: 设备分辨率坐标；None = 整屏。
        :return: BGR 数组（独立副本）。
        """
        import numpy as np

        image = self._capture()
        if self._size is None:
            self._size = (int(image.shape[1]), int(image.shape[0]))
        if region is None:
            return np.ascontiguousarray(image)
        return np.ascontiguousarray(image[region.y : region.bottom, region.x : region.right])

    def close(self) -> None:
        return None

    def __repr__(self) -> str:
        return f"AdbScreenBackend(serial={self.client.serial!r}, max_fps={self.max_fps})"


class AdbInputBackend:
    """输入后端。坐标是**设备分辨率**（即源分辨率）。"""

    name = "adb-input"

    def __init__(
        self,
        client: AdbClient,
        *,
        tap_delay: float = 0.05,
        scroll_span: float = 0.6,
        screen_size: Any = None,
    ) -> None:
        self.client = client
        self.tap_delay = tap_delay
        #: 模拟滚动时滑过的距离占屏幕高度的比例
        self.scroll_span = scroll_span
        self._screen_size = screen_size
        self._size: tuple[int, int] | None = None

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _viewport(self) -> tuple[int, int]:
        """取屏幕尺寸（供 scroll 计算滑动距离）。"""
        if self._size is not None:
            return self._size
        if callable(self._screen_size):
            self._size = self._screen_size()
        elif self._screen_size is not None:
            self._size = self._screen_size
        else:
            self._size = self._size_from_wm()
        return self._size

    def _size_from_wm(self) -> tuple[int, int]:
        output = self.client.shell("wm", "size")
        size: tuple[int, int] | None = None
        for line in output.splitlines():
            if "size:" not in line:
                continue
            token = line.split("size:")[-1].strip()
            if "x" in token:
                width, _, height = token.partition("x")
                if width.strip().isdigit() and height.strip().isdigit():
                    size = (int(width), int(height))
        if size is None:
            raise BackendError(f"无法确定设备分辨率，wm size 输出: {output!r}")
        return size

    @staticmethod
    def _escape_text(text: str) -> str:
        """``input text`` 的参数转义。

        空格要用 ``%s``；shell 元字符要转义，否则会被设备侧 shell 解释掉。
        """
        escaped = text.replace("\\", "\\\\")
        for char in "()<>|;&*~^\"'`$":
            escaped = escaped.replace(char, "\\" + char)
        return escaped.replace(" ", "%s")

    # ------------------------------------------------------------------ #
    # 协议
    # ------------------------------------------------------------------ #
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
        #: 只有左键有点击语义；右键 / 中键在触屏上没有对应物
        if button not in ("left", "primary"):
            raise BackendError(f"Android 只有左键点击，收到 button={button!r}")
        for index in range(max(1, clicks)):
            if index:
                time.sleep(interval)
            self.client.shell("input", "tap", str(point.x), str(point.y))
            time.sleep(self.tap_delay)

    def drag(
        self,
        start: Point,
        end: Point,
        *,
        duration: float = 0.5,
        button: str = "left",
    ) -> None:
        milliseconds = max(1, int(duration * 1000))
        self.client.shell(
            "input",
            "swipe",
            str(start.x),
            str(start.y),
            str(end.x),
            str(end.y),
            str(milliseconds),
        )
        time.sleep(self.tap_delay)

    def scroll(self, clicks: int, point: Point | None = None) -> None:
        """用短 swipe 模拟滚动。

        :param clicks: 正数向上滚（内容往下走），负数向下滚。
            一次 "click" 约等于 ``scroll_span`` 倍的屏幕高度。
        :param point: 滚动中心；None 时用屏幕中心。
        """
        if clicks == 0:
            return
        width, height = self._viewport()
        center_x = point.x if point is not None else width // 2
        center_y = point.y if point is not None else height // 2
        span = int(height * self.scroll_span * abs(clicks))
        span = max(20, min(span, max(20, height // 2)))
        # 手指从上往下滑 = 内容向上滚（看到下面的内容），和滚轮方向相反
        direction = -1 if clicks > 0 else 1
        start_y = center_y - direction * span // 2
        end_y = center_y + direction * span // 2
        # 必须落在屏幕内（留边），否则这条 swipe 会被系统直接忽略
        start_y = max(1, min(height - 2, start_y))
        end_y = max(1, min(height - 2, end_y))
        self.client.shell(
            "input", "swipe", str(center_x), str(start_y), str(center_x), str(end_y), "300"
        )

    def type_text(self, text: str, *, interval: float = 0.05) -> None:
        if not text:
            return
        if not text.isascii():
            raise BackendError(
                "adb `input text` 不支持非 ASCII。要输中文需要先装 ADBKeyboard 之类的"
                "输入法并改用 am broadcast 方案。"
            )
        # 一次性发整串；input text 自己会逐字符处理，interval 只用来控制多段之间的间隔
        self.client.shell("input", "text", self._escape_text(text))
        time.sleep(max(interval, 0.0))

    def press_key(self, key: str, *, presses: int = 1, interval: float = 0.1) -> None:
        code = KEYCODES.get(key.strip().lower())
        if code is None:
            raise BackendError(f"未登记的键名: {key!r}（见 backends/android.py 的 KEYCODES）")
        for index in range(max(1, presses)):
            if index:
                time.sleep(interval)
            self.client.shell("input", "keyevent", str(code))

    def hotkey(self, keys: list[str]) -> None:
        raise BackendError("Android 没有组合键语义，请用 press_key 逐个按")

    def close(self) -> None:
        return None

    def __repr__(self) -> str:
        return f"AdbInputBackend(serial={self.client.serial!r})"


def build_android_backends(
    *,
    serial: str = "",
    adb_path: str = "adb",
    max_fps: float = 5.0,
    timeout: float = 20.0,
    **_ignored: Any,
) -> BackendBundle:
    """装配 Android 两件套（无窗口概念，``window=None``）。"""
    client = AdbClient(serial=serial, adb_path=adb_path, timeout=timeout)
    screen = AdbScreenBackend(client, max_fps=max_fps)
    # 输入后端复用屏幕后端的尺寸探测，避免两边各查一次 wm size
    return BackendBundle(
        screen=screen,
        input=AdbInputBackend(client, screen_size=screen.screen_size),
        window=None,
    )
