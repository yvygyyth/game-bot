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
* **坐标基准**：``screen_size()`` / ``grab(region)`` 里的坐标，原点是
  「窗口客户区左上角」或「显示器左上角」。窗口截图时后端负责把源坐标
  叠加上窗口在屏幕上的偏移，上层永远只看到 0 起点。

依赖（都在 ``--extra windows`` 里）：
``mss``（基础依赖）、``pywin32``、``pydirectinput``。
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Any

from ...exceptions import BackendError, BackendUnavailable
from ...types import Point, Region
from ...utils.logging import get_logger
from .base import BackendBundle, WindowInfo

if TYPE_CHECKING:
    import numpy as np

log = get_logger("backends.windows")

__all__ = [
    "KEY_MAP",
    "WindowsInputBackend",
    "WindowsScreenBackend",
    "WindowsWindowBackend",
    "build_windows_backends",
    "enable_dpi_awareness",
    "normalize_key",
]

#: 统一键名 -> pyautogui / pydirectinput 的键名。
#: 业务脚本只应该用左边这些；要加自定义映射请改这里，别把平台键名写进脚本。
KEY_MAP: dict[str, str] = {
    # 编辑键
    "enter": "enter",
    "return": "enter",
    "esc": "escape",
    "escape": "escape",
    "space": "space",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    # 方向键
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    # 修饰键
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "win",
    "cmd": "win",
    # 小键盘 / 功能键
    "capslock": "capslock",
    "numlock": "numlock",
    "printscreen": "printscreen",
    "scrolllock": "scrolllock",
    "pause": "pause",
    # 鼠标
    "mouseleft": "left",
    "mouseright": "right",
    "mousemiddle": "middle",
}

# 单字符键（a-z / 0-9 / 符号）原样透传，这里只补几个习惯写法
for _digit in "0123456789":
    KEY_MAP[_digit] = _digit
for _letter in "abcdefghijklmnopqrstuvwxyz":
    KEY_MAP[_letter] = _letter
for _index in range(1, 25):
    KEY_MAP[f"f{_index}"] = f"f{_index}"


def normalize_key(key: str) -> str:
    """把统一键名转成后端键名。未登记的键名原样返回（可能是后端特有键）。"""
    return KEY_MAP.get(key.strip().lower(), key)


def enable_dpi_awareness() -> None:
    """声明进程 DPI 感知（Per-Monitor V2 优先）。

    必须在创建任何窗口 / 抓屏句柄之前调用。非 win32 平台上静默返回。
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
    """基于 win32gui 的窗口发现与定位。"""

    def __init__(self, *, client_area_only: bool = True) -> None:
        self.client_area_only = client_area_only

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @staticmethod
    def _load() -> Any:
        try:
            import win32gui
        except ImportError as exc:  # pragma: no cover
            raise BackendUnavailable(
                "缺少 pywin32，请执行: uv sync --extra windows"
            ) from exc
        return win32gui

    def region_of(self, handle: int) -> Region:
        """取窗口区域。``client_area_only`` 时只算客户区（不含标题栏 / 边框）。"""
        win32gui = self._load()
        if self.client_area_only:
            _, _, width, height = win32gui.GetClientRect(handle)
            left, top = win32gui.ClientToScreen(handle, (0, 0))
        else:
            left, top, right, bottom = win32gui.GetWindowRect(handle)
            width, height = right - left, bottom - top
        return Region(int(left), int(top), int(width), int(height))

    # ------------------------------------------------------------------ #
    # 协议
    # ------------------------------------------------------------------ #
    def list_windows(self, keyword: str = "") -> list[WindowInfo]:
        """列出可见且未最小化的窗口。``keyword`` 非空时按标题子串过滤（不区分大小写）。"""
        win32gui = self._load()
        lowered = keyword.lower()
        found: list[WindowInfo] = []

        def callback(handle: int, _extra: Any) -> bool:
            if not win32gui.IsWindowVisible(handle):
                return True
            # 最小化时 GetWindowRect 会返回 -32000 之类的垃圾坐标，必须跳过
            if win32gui.IsIconic(handle):
                return True
            title = win32gui.GetWindowText(handle)
            if not title:
                return True
            if lowered and lowered not in title.lower():
                return True
            try:
                region = self.region_of(handle)
            except Exception:
                return True
            if region.is_empty:
                return True
            found.append(WindowInfo(handle, title, region))
            return True

        win32gui.EnumWindows(callback, None)
        return found

    def find_window(self, title_pattern: str) -> WindowInfo | None:
        """按标题关键字找窗口，取第一个（``EnumWindows`` 的顺序，通常是 Z 序）。"""
        matches = self.list_windows(title_pattern)
        return matches[0] if matches else None


class WindowsScreenBackend:
    """mss 截图后端。

    :param window_title: 非空时只抓该窗口；为空则抓整个显示器。
    :param monitor_index: mss 的显示器序号，``1`` 是主屏（抓窗口时忽略）。
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
        # DPI 感知必须早于任何抓屏句柄
        enable_dpi_awareness()
        try:
            import mss  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise BackendUnavailable("缺少 mss，请执行: uv sync") from exc

        self.window_title = window_title
        self.monitor_index = monitor_index
        self.client_area_only = client_area_only
        self._sct: Any = None
        self._window = WindowsWindowBackend(client_area_only=client_area_only)
        self._cached_region: Region | None = None
        self._cached_at = 0.0
        self._cache_ttl = 0.5

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _engine(self) -> Any:
        """懒建 mss 句柄并复用。每次 grab 都新建会明显变慢。"""
        if self._sct is None:
            import mss

            self._sct = mss.mss()
        return self._sct

    def _monitor_region(self) -> Region:
        monitor = self._engine().monitors[self.monitor_index]
        return Region(
            int(monitor["left"]),
            int(monitor["top"]),
            int(monitor["width"]),
            int(monitor["height"]),
        )

    def source_region(self) -> Region:
        """当前捕获区域在**屏幕坐标**下的位置。

        窗口模式下是客户区矩形（会随窗口移动而变化，所以带短 TTL 缓存）；
        全屏模式下是显示器矩形。
        """
        if not self.window_title:
            return self._monitor_region()

        now = time.monotonic()
        if self._cached_region is not None and now - self._cached_at < self._cache_ttl:
            return self._cached_region

        info = self._window.find_window(self.window_title)
        if info is None:
            raise BackendError(f"未找到标题包含 {self.window_title!r} 的窗口")
        self._cached_region = info.region
        self._cached_at = now
        return info.region

    def invalidate(self) -> None:
        """丢掉窗口区域的缓存（窗口刚被移动 / 缩放时调）。"""
        self._cached_region = None
        self._cached_at = 0.0

    # ------------------------------------------------------------------ #
    # 协议
    # ------------------------------------------------------------------ #
    def screen_size(self) -> tuple[int, int]:
        region = self.source_region()
        return (region.w, region.h)

    def grab(self, region: Region | None = None) -> np.ndarray:
        """抓一帧。

        :param region: **源坐标**（0 起点 = 捕获区左上角）。会叠加窗口/显示器的
            屏幕偏移后再交给 mss。
        :return: ``(H, W, 3)`` 的 BGR 数组，独立副本。
        """
        import numpy as np

        base = self.source_region()
        target = base if region is None else Region(
            base.x + region.x, base.y + region.y, region.w, region.h
        )
        if target.is_empty:
            raise BackendError(f"截图区域为空: {target.to_tuple()}")

        try:
            raw = self._engine().grab(target.to_mss())
        except Exception as exc:
            raise BackendError(f"抓屏失败 {target.to_tuple()}: {exc}") from exc

        # BGRA -> BGR，并强制一份连续内存的独立副本（mss 的缓冲区会被下一帧覆盖）
        return np.ascontiguousarray(np.asarray(raw)[:, :, :3])

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None

    def __repr__(self) -> str:
        target = self.window_title or f"monitor#{self.monitor_index}"
        return f"WindowsScreenBackend({target!r})"


class WindowsInputBackend:
    """输入后端。

    :param engine: ``"direct"`` 用 pydirectinput（游戏兼容好），
        ``"pyautogui"`` 用通用实现（组合键、中文输入更省事）。
    :param key_hold: 组合键/拖拽时每个键按下的保持时间（秒）。
        给 0 时部分游戏会漏收按键。
    :param offset_provider: 返回**捕获区在屏幕上的原点**的可调用对象
        （通常是 ``WindowsScreenBackend.source_region``）。见下面"坐标系"。
    :param coordinate_space: ``"source"``（默认）或 ``"screen"`` —— 本后端收到的
        点属于哪一套坐标。``"screen"`` 时先减掉捕获区原点再走同一条路。
        见下面"两套坐标"。

    ## 坐标系（这里曾经有个真 bug）

    本后端收到的点**是源坐标**（0 起点 = 捕获区左上角），而
    ``SetCursorPos``/``SendInput`` 要的是**绝对屏幕坐标**。所以必须加上
    捕获区原点。``WindowsScreenBackend.grab()`` 一直做着这件事
    （``base.x + region.x``），但输入这条路当初漏了 —— 结果是每一次真实点击
    都偏一个窗口位置（这台机器上是左偏 21、上偏 49）。

    为什么漏了这么久没被发现：整张卡片这种大目标，偏几十像素**照样点在卡上**，
    看起来完全正常。只有小目标、或者靠近边缘的目标才会明显点空。
    而输入这条链路一直只用 ``FakeInputBackend`` 验证过 —— 假后端不关心屏幕坐标，
    所以永远测不出来。教训：**假后端能验证逻辑，验证不了坐标系。**

    偏移在**每次调用时**现取，不在构造时算死：窗口会被拖动、脚本跑着跑着
    用户可能挪一下窗口，算死就会悄悄错位。

    ## 两套坐标，只差原点在哪

    | ``coordinate_space`` | 0 起点 | 谁产出的 |
    |---|---|---|
    | ``"source"``（默认） | 捕获区（客户区）左上角 | ``Frame`` / ``find_image`` / 模板 / roi |
    | ``"screen"`` | **显示器**左上角 | 桌面级取点工具，人手量出来的 |

    两者只差一个常量：捕获区在屏幕上的原点（本机实测是 ``(1, 31)``）。

        source (1365, 585) + (1, 31) = screen (1366, 616)

    ``"screen"`` 时这里**先减掉那个原点**，之后就完全走 source 那条路 ——
    所以换算只有**一层**，动作层、步骤、模板都不用知道这个开关存在。
    ``"source"`` 时这一层是恒等，一个减法都不做。
    """

    name = "windows-input"

    def __init__(
        self,
        *,
        engine: str = "direct",
        key_hold: float = 0.02,
        move_settle: float = 0.08,
        move_glide: float = 0.12,
        glide_steps: int = 8,
        offset_provider: Any = None,
        coordinate_space: str = "source",
    ) -> None:
        if sys.platform != "win32":
            raise BackendUnavailable("windows 后端只能在 Windows 上使用")
        if coordinate_space not in ("source", "screen"):
            raise BackendError(
                f"coordinate_space 只能是 'source' 或 'screen'，收到 {coordinate_space!r}"
            )
        self.engine = engine
        self.key_hold = key_hold
        self.coordinate_space = coordinate_space
        #: 移到点上之后、按下之前等多久。**不是保险，是必需品** —— 见 :meth:`click`。
        #: 0 关掉（调脚本时想复现"点了没反应"可以用）。
        self.move_settle = move_settle
        #: 滑到目标点的总时长和步数（见 :meth:`_glide`）。
        #: ``move_glide=0`` 或 ``glide_steps=1`` 退化成瞬移 —— 复现问题用的。
        self.move_glide = move_glide
        self.glide_steps = glide_steps
        self._impl: Any = None
        self._offset_provider = offset_provider

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _offset(self) -> tuple[int, int]:
        """捕获区原点（绝对屏幕坐标）。取不到就当 (0,0) —— 抓整屏时就是它。

        取不到时**不能抛异常**：宁可点偏也不能让"窗口刚被关掉"变成脚本崩溃。
        """
        provider = self._offset_provider
        if provider is None:
            return (0, 0)
        try:
            region = provider()
            return (int(region.x), int(region.y))
        except Exception:
            return (0, 0)

    def _absolute(self, point: Point) -> tuple[int, int]:
        """本后端收到的点 -> 绝对屏幕坐标。**所有涉及坐标的调用都过这一道。**

        两层，但只有一个开关：

        1. ``coordinate_space == "screen"`` 时，先减掉捕获区原点 ——
           把"屏幕坐标"拉回"捕获区相对坐标"。``"source"`` 时这一步是恒等。
        2. 再加回捕获区原点，得到绝对屏幕坐标。

        所以 ``"screen"`` 是 ``+原 点 - 原点``（净效果 = 原样使用），
        ``"source"`` 是 ``+原点``。两步都在同一个函数里，
        不会有"哪一层忘了换算"的机会。
        """
        dx, dy = self._offset()
        if self.coordinate_space == "screen":
            # 屏幕坐标 -> 捕获区相对坐标
            point = Point(point.x - dx, point.y - dy)
        return point.x + dx, point.y + dy

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
        self._impl.FAILSAFE = False  # 鼠标撞到屏幕角落不该抛异常打断脚本
        self._impl.PAUSE = 0
        log.debug("Windows 输入引擎: %s", module)
        return self._impl

    def _set_clipboard(self, text: str) -> None:
        """把文本塞进剪贴板（中文输入的唯一靠谱办法）。"""
        try:
            import win32clipboard
            import win32con
        except ImportError as exc:  # pragma: no cover
            raise BackendUnavailable(
                "输入非 ASCII 文本需要剪贴板支持，请执行: uv sync --extra windows"
            ) from exc

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()

    # ------------------------------------------------------------------ #
    # 协议
    # ------------------------------------------------------------------ #
    def move_to(self, point: Point, duration: float = 0.2) -> None:
        x, y = self._absolute(point)
        self._load().moveTo(x, y, duration=duration)

    def _glide(self, impl: Any, x: int, y: int, *, steps: int, duration: float) -> None:
        """把鼠标**分多步**移到 ``(x, y)``，中间发出真实的移动事件。

        ## 为什么不直接用 ``impl.moveTo(x, y, duration=...)``

        试过了，它不行：``pydirectinput.moveTo`` 带 duration 时走的是
        ``moveRel(x - currentX, y - currentY, relative=True)`` ——
        **一次 SendInput 发完整个位移**，不是插值。游戏那一帧收到的还是
        "从 A 跳到 B"（甚至只有相对位移量），中间没有经过任何位置。

        而这个方法每步都调 ``moveTo``（绝对坐标），所以每步都是一次真实的
        移动事件 —— 游戏的指针轨迹是连续的。

        ## 为什么需要连续轨迹

        有些游戏（尤其是带 3D 场景/自由视角的）自己维护鼠标位置，
        只认"连续移动"的轨迹；直接跳过去那一跳它可能当成视角回正而丢掉。
        对这类游戏，"瞬移 + 点"和"滑过去 + 点"是**两种不同的结果**。

        步数和总时长都夹住了：太短没效果（事件太少），太长是白等
        （每步还带一次 SendInput）。

        **这段原来是 ``drag()`` 里的内联代码**，抽出来给 :meth:`click` 共用 ——
        两处各写一遍迟早不一致，而它们要解决的是同一个问题。
        """
        current = self._cursor_or_none()
        if current is None or steps <= 1 or duration <= 0:
            impl.moveTo(x, y, duration=0)
            return
        sx, sy = current
        # 距离太近就不插值了：一步到位的事件量已经够，还省时间
        if abs(x - sx) + abs(y - sy) < 4:
            impl.moveTo(x, y, duration=0)
            return
        for step in range(1, steps + 1):
            ratio = step / steps
            impl.moveTo(round(sx + (x - sx) * ratio), round(sy + (y - sy) * ratio), duration=0)
            if step < steps:
                time.sleep(duration / steps)

    @staticmethod
    def _cursor_or_none() -> tuple[int, int] | None:
        """鼠标现在在哪。读不到就返回 None（不想因为读指针失败而点不出去）。"""
        try:
            import win32api

            return win32api.GetCursorPos()
        except Exception:
            return None

    def click(
        self,
        point: Point,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
    ) -> None:
        """**滑过去** -> 停一下 -> 按下抬起。

        ## 两个"多做的一步"，都是踩出来的

        **① 滑过去，不是瞬移。** 用 :meth:`_glide` 分多步移动，让游戏收到一条
        连续轨迹。原来 ``moveTo(duration=0)`` 是一跳到位，有些游戏会把它当成
        "视角回正"而丢掉这一次指针变化。

        **② 滑到之后停一下再按。** 原来移动完**立刻**点，零间隔。
        游戏的位置跟踪在它自己的帧里做，按压消息会带着**移动前的位置**到达 ——
        于是这一下被当成"在别处点了一下"丢掉。

        ## 这个 bug 为什么难查

        从外面看每一步都对：动作层返回成功、``GetCursorPos`` 也确实是目标点、
        日志里识别也命中了。**唯一能看出问题的地方是游戏自己没反应。**

        实测症状：鼠标到了正确位置，但界面不跳转（``enter_jingji`` 在 journal 里
        连续几十次 ``success``，流程就是不走）。

        :param interval: 多击之间的间隔。
        """
        impl = self._load()
        x, y = self._absolute(point)
        self._glide(impl, x, y, steps=self.glide_steps, duration=self.move_glide)

        # 等游戏把"鼠标到这儿了"处理进去。默认 0.08s ≈ 5 帧（60fps），
        # 够它跑完一次位置更新；再长就只是白等。
        if self.move_settle > 0:
            time.sleep(self.move_settle)

        if clicks <= 1:
            # 单击也显式拆成 down/up（不用 impl.click）：一是能控住按住时长
            # ——部分游戏把过短的按下当抖动丢掉；二是和多击那条路径同一套动作，
            # 少一条只在单击时才走的分支。
            impl.mouseDown(button=button)
            time.sleep(self.key_hold)
            impl.mouseUp(button=button)
            return

        # 多次点击自己拆开：不同后端对 clicks/interval 的处理不一致，
        # 显式 mouseDown/mouseUp + sleep 最可控（双击尤其明显）。
        for index in range(clicks):
            if index:
                time.sleep(interval)
            impl.mouseDown(button=button)
            time.sleep(self.key_hold)
            impl.mouseUp(button=button)

    def drag(
        self,
        start: Point,
        end: Point,
        *,
        duration: float = 0.5,
        button: str = "left",
    ) -> None:
        impl = self._load()
        sx, sy = self._absolute(start)
        ex, ey = self._absolute(end)
        impl.moveTo(sx, sy, duration=0)
        impl.mouseDown(button=button)
        try:
            # 起点先停一下：部分游戏需要"按住"稳定后才认拖拽
            time.sleep(max(self.key_hold, 0.05))
            steps = max(2, min(60, int(duration / 0.02) or 2))
            for step in range(1, steps + 1):
                ratio = step / steps
                impl.moveTo(
                    round(sx + (ex - sx) * ratio),
                    round(sy + (ey - sy) * ratio),
                    duration=0,
                )
                time.sleep(duration / steps)
        finally:
            # 无论中途出什么错都要松开，否则会把整个桌面拖住
            impl.mouseUp(button=button)

    def scroll(self, clicks: int, point: Point | None = None) -> None:
        impl = self._load()
        if point is not None:
            x, y = self._absolute(point)
            impl.moveTo(x, y, duration=0)
        impl.scroll(clicks)

    def type_text(self, text: str, *, interval: float = 0.05) -> None:
        if not text:
            return
        impl = self._load()
        if text.isascii():
            impl.write(text, interval=interval)
            return
        # 非 ASCII（中文等）：剪贴板 + Ctrl+V
        self._set_clipboard(text)
        time.sleep(0.05)  # 等剪贴板真的生效
        self.hotkey(["ctrl", "v"])
        time.sleep(max(interval, 0.05))

    def press_key(self, key: str, *, presses: int = 1, interval: float = 0.1) -> None:
        impl = self._load()
        backend_key = normalize_key(key)
        for index in range(max(1, presses)):
            if index:
                time.sleep(interval)
            impl.press(backend_key)

    def hotkey(self, keys: list[str]) -> None:
        if not keys:
            return
        impl = self._load()
        backend_keys = [normalize_key(key) for key in keys]
        if len(backend_keys) == 1:
            impl.press(backend_keys[0])
            return
        pressed: list[str] = []
        try:
            for key in backend_keys:
                impl.keyDown(key)
                pressed.append(key)
                time.sleep(self.key_hold)
        finally:
            # 倒序松开；出了异常也必须松，不然会留下"卡住的 Ctrl"
            for key in reversed(pressed):
                try:
                    impl.keyUp(key)
                except Exception:
                    log.warning("释放按键失败: %s", key)

    def close(self) -> None:
        self._impl = None


def build_windows_backends(
    *,
    window_title: str = "",
    monitor_index: int = 1,
    client_area_only: bool = True,
    input_engine: str = "direct",
    coordinate_space: str = "source",
    move_settle: float = 0.08,
    move_glide: float = 0.12,
    glide_steps: int = 8,
    **_ignored: Any,
) -> BackendBundle:
    """装配 Windows 三件套。

    注意这里把 ``screen.source_region`` 交给了输入后端 —— **输入必须加和截图
    同样的原点偏移**，否则每次点击都偏一个窗口位置（见
    :class:`WindowsInputBackend` 的坐标系说明）。两者用同一个来源，
    从构造上保证它们不可能不一致。

    ``coordinate_space`` 一路传到输入后端：``"screen"`` 时它会先减掉这个
    同一个原点，于是"人手量的屏幕坐标"和"模板用的捕获区坐标"能对上。
    """
    screen = WindowsScreenBackend(
        window_title=window_title,
        monitor_index=monitor_index,
        client_area_only=client_area_only,
    )
    return BackendBundle(
        screen=screen,
        input=WindowsInputBackend(
            engine=input_engine,
            offset_provider=screen.source_region,
            coordinate_space=coordinate_space,
            move_settle=move_settle,
            move_glide=move_glide,
            glide_steps=glide_steps,
        ),
        window=WindowsWindowBackend(client_area_only=client_area_only),
    )
