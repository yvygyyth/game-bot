"""全局快捷键 —— 界面没焦点时也能按。

## 为什么需要它

界面用的是 ``QShortcut``，它的 context 是 ``WindowShortcut``：**焦点离开窗口
就失效**。而这个工具的实际用法是"游戏在前台、界面在后台"—— 于是在最需要
停止的时候（脚本开始乱点、游戏卡住了），``Esc`` 按不到。

## 为什么用**低级键盘钩子**，不用 ``RegisterHotKey``

``RegisterHotKey`` 更简单，但它**会把那个键吃掉**：注册期间系统不再把
``Esc`` 发给任何窗口。对一个"抢游戏输入的脚本工具"来说这是最糟的副作用 ——
你按下停止键，游戏自己也收不到那个键了。

低级键盘钩子（``WH_KEYBOARD_LL``）是**只观察不拦**：回调返回
``CallNextHookEx``，事件照常往游戏那边走。两边都收到，互不影响。

## 线程模型

钩子必须装在**有消息循环**的线程上，所以这里自己起一个线程跑 ``GetMessageW``。

回调跑在那个线程里，判定成功后通过 Qt 信号发出去 —— 跨线程信号是**队列投递**，
槽函数在界面线程执行，所以触发动作是安全的（和 ``EngineWorker`` 那套同一个规矩）。

## 回调必须极短

低级钩子挂在**整个系统的输入路径**上：回调慢一点，全系统的键盘都会卡。
所以这里只做"查表 + 发信号"，不干别的（不读配置、不写日志、不碰界面）。

## 非 Windows 上降级

装不上就 ``start()`` 返回 False，界面继续用普通快捷键 —— 全局快捷键是增强，
不是前置条件。``is_supported()`` 可以让界面说清"这个平台上没有"。
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

if sys.platform == "win32":
    import ctypes.wintypes as _wintypes
else:  # pragma: no cover - 非 Windows 上这个模块只用于"降级"，不装钩子
    _wintypes = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

__all__ = ["GlobalHotkeys", "Hotkey", "is_supported", "parse_hotkey"]

# ---------------------------------------------------------------- Win32 常量
_WH_KEYBOARD_LL = 13
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_WM_SYSKEYDOWN = 0x0104
_WM_SYSKEYUP = 0x0105
_WM_QUIT = 0x0012
_PM_NOREMOVE = 0x0000

_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12  # Alt
_VK_LWIN = 0x5B
_VK_RWIN = 0x5C

#: 修饰键的位（``Hotkey.mods`` 用）。刻意和 ``win32con.MOD_*`` 一致。
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

#: Qt 的键 → Windows 虚拟键码。
#:
#: ## 为什么这张表要从 Qt 枚举现搭，而不是手写常量
#:
#: 手写过一版，两个地方错了，而且**都不会报错、只是按不出来**：
#:
#: * 功能键的序号算错：``F5`` 落到了 ``0x22``（那是 PageUp 的键码），
#:   于是 F5 全局失效；
#: * Qt6 的修饰位记反了：``ControlModifier`` 是 ``0x04000000``、
#:   ``ShiftModifier`` 是 ``0x02000000``，我按 Qt5 的印象写成后者是 Ctrl，
#:   于是 ``Ctrl+1`` 被当成 ``Shift+1``。
#:
#: 所以键码从 ``Qt.Key`` 取、修饰位从 ``Qt.KeyboardModifier`` 取 ——
#: 少背一组数字，就少一处对不上的机会。
def _as_int(value: Any) -> int:
    """把 Qt 的枚举/flag 取成整数。

    **PySide6 里 ``int(SomeFlag.Foo)`` 会 TypeError** —— flag 对象不是数字，
    得走 ``.value``。这个坑在这个文件里踩了两次（修饰位、键码），所以收成一个
    函数：以后只可能对一次。
    """
    return int(getattr(value, "value", value))


def _build_vk_table() -> dict[int, int]:
    from PySide6.QtCore import Qt

    table: dict[int, int] = {}
    key = Qt.Key
    # A-Z：Qt 里 A-Z 就是 0x41-0x5A，和 Win32 一致
    for i in range(26):
        table[_as_int(key.Key_A) + i] = 0x41 + i
    # F1-F24：Qt 里连续，Win32 里也连续（0x70 起）
    for i in range(24):
        table[_as_int(key.Key_F1) + i] = 0x70 + i

    table.update(
        {
            _as_int(key.Key_Escape): 0x1B,
            _as_int(key.Key_Tab): 0x09,
            _as_int(key.Key_Backspace): 0x08,
            _as_int(key.Key_Return): 0x0D,
            _as_int(key.Key_Enter): 0x0D,
            _as_int(key.Key_CapsLock): 0x14,
            _as_int(key.Key_Shift): _VK_SHIFT,
            _as_int(key.Key_Control): _VK_CONTROL,
            _as_int(key.Key_Alt): _VK_MENU,
            _as_int(key.Key_Meta): _VK_LWIN,
            _as_int(key.Key_Print): 0x2C,
            _as_int(key.Key_ScrollLock): 0x91,
            _as_int(key.Key_Pause): 0x13,
            _as_int(key.Key_Insert): 0x2D,
            _as_int(key.Key_Delete): 0x2E,
            _as_int(key.Key_Home): 0x24,
            _as_int(key.Key_End): 0x23,
            _as_int(key.Key_PageUp): 0x21,
            _as_int(key.Key_PageDown): 0x22,
            _as_int(key.Key_Left): 0x25,
            _as_int(key.Key_Up): 0x26,
            _as_int(key.Key_Right): 0x27,
            _as_int(key.Key_Down): 0x28,
            _as_int(key.Key_Space): 0x20,
            _as_int(key.Key_NumLock): 0x90,
        }
    )
    # 数字 0-9：Qt 的 Key_0..Key_9 连着，值就是 0x30..0x39
    for i in range(10):
        table[_as_int(key.Key_0) + i] = 0x30 + i
    return table


_VK: dict[int, int] = _build_vk_table()


def _build_mod_bits() -> tuple[tuple[int, int], ...]:
    """Qt 的修饰位 → 我们的 ``MOD_*``。**从枚举取，不写死数字**。"""
    from PySide6.QtCore import Qt

    mod = Qt.KeyboardModifier
    return (
        (_as_int(mod.ControlModifier), MOD_CONTROL),
        (_as_int(mod.AltModifier), MOD_ALT),
        (_as_int(mod.ShiftModifier), MOD_SHIFT),
        (_as_int(mod.MetaModifier), MOD_WIN),
    )


_MOD_BITS: tuple[tuple[int, int], ...] = _build_mod_bits()


@dataclass(frozen=True, slots=True)
class Hotkey:
    """一条已解析出来的全局快捷键。"""

    action: str
    vk: int
    """Windows 虚拟键码（主键，不含修饰键）。"""

    mods: int
    """修饰键位掩码（``MOD_*``）。"""

    keys: str
    """原始写法（``"Ctrl+Alt+F12"``），只用于显示和报错。"""


def parse_hotkey(action: str, keys: str) -> Hotkey | None:
    """把 ``"Ctrl+Alt+F12"`` 解析成 :class:`Hotkey`。认不出来返回 ``None``。

    认不出来就跳过这一条，而不是抛异常 —— 快捷键少一条不该让整个界面起不来。
    **但一定要记 warning**：跳过而不出声的症状是"我明明写了却没生效"，
    没有日志就只能靠猜。

    ## 认不出来的两种情形（都实测过）

    * **键的写法 Qt 不认** —— ``QKeySequence`` 会**静默**返回
      ``Qt::Key_unknown``。踩过的例子：``"PageUp"`` / ``"PageDown"`` /
      ``"Win"``；Qt 认的是 ``"PgUp"`` / ``"PgDown"`` / ``"Meta"``。
      这种最难查，因为没有任何报错，只是那条键不见了；
    * 键在 Qt 里认、但不在下面那张虚拟键码表里。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence

    sequence = QKeySequence(keys)
    if sequence.count() != 1:
        log.warning("全局快捷键 %r 的写法解析不出单个组合: %r", action, keys)
        return None
    # 取第一条组合。**只能走下标，而 PySide6 的 stub 没给 `__getitem__`**，
    # 所以这一处必须 ignore —— 我试过绕开（改用 `toString()`），
    # 结果是**语义坏了**：Qt 不认的键名 `toString()` 返回空串，
    # 于是"键名拼错"和"解析不出组合"混成一类，测试立刻变红。
    # 与其为了类型干净牺牲正确性，不如在**唯一**需要它的地方 ignore 并写明理由。
    combo = sequence[0]  # type: ignore[index]
    key = _as_int(combo.key())
    if key == _as_int(Qt.Key.Key_unknown):
        # 这条要说清"是键名写错了"，而不是含糊的"解析不出来"
        log.warning(
            "全局快捷键 %r 的键名 %r 不是 Qt 认的写法（Qt 会静默给出 Key_unknown）—— "
            "这条不会生效。常见写法: PgUp / PgDown / Meta / Esc / Del",
            action,
            keys,
        )
        return None
    vk = _VK.get(key)
    if vk is None:
        log.warning("全局快捷键 %r 的主键 %r 不在虚拟键码表里，跳过", action, keys)
        return None

    mods = 0
    # 注意：``keyboardModifiers()`` 返回的是 Qt 的 flag 对象，**不能直接 int()**
    # （会 TypeError）。取 ``.value`` 才是整数位。
    raw = int(getattr(combo.keyboardModifiers(), "value", 0))
    for bit, mod in _MOD_BITS:
        if raw & bit:
            mods |= mod
    return Hotkey(action=action, vk=vk, mods=mods, keys=keys)


def is_supported() -> bool:
    """这个平台上能不能用全局快捷键。"""
    return sys.platform == "win32"


def matches(hotkey: Hotkey, vk: int, held: int) -> bool:
    """回调里的判定：按下的主键和修饰键状态对不对。

    **要单独成一个函数**（不写在回调里）：低级钩子的回调没法在测试里调，
    而"判定对不对"恰恰是最该测的部分 —— 判错的症状是"按了没反应"或者
    "没按也触发"。修饰键必须**恰好**匹配，多按一个不算中，
    否则 ``Ctrl+Alt+X`` 会在按 ``Ctrl+X`` 时也触发。
    """
    return vk == hotkey.vk and held == hotkey.mods


class GlobalHotkeys(QObject):
    """在后台线程里观察键盘，命中就发 :attr:`triggered`。"""

    #: 命中了哪条快捷键（参数是 ``action``）。跨线程队列投递到界面线程。
    triggered = Signal(str)

    def __init__(self, hotkeys: list[Hotkey], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkeys = list(hotkeys)
        self._thread: threading.Thread | None = None
        self._hook: Any = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._ok = False
        #: 当前按住的修饰键（回调里维护）。**每条快捷键各自记一份状态**没必要，
        #: 修饰键是全局的物理状态。
        self._held = 0
        #: 回调一共收到多少次按键（只用于排查钩子有没有被调用）
        self._seen = 0
        self._proc: Any = None

    # ------------------------------------------------------------------ #
    @property
    def hotkeys(self) -> list[Hotkey]:
        return list(self._hotkeys)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        """装钩子并起消息循环线程。返回"装上了没"。

        **不抛异常**：装不上就返回 False，界面退回普通快捷键。
        这条路失败的原因（权限、非 Windows、别的钩子程序）都不该让界面起不来。
        """
        if not is_supported() or not self._hotkeys:
            return False
        if self.running:
            return True

        self._ready.clear()
        self._ok = False
        self._thread = threading.Thread(target=self._run, name="gamebot-hotkeys", daemon=True)
        self._thread.start()
        # 等它把钩子装上（超时也算失败，别把界面卡住）
        self._ready.wait(timeout=2.0)
        if not self._ok:
            log.warning("全局快捷键没装上，界面内快捷键仍然可用")
        return self._ok

    def stop(self) -> None:
        """卸钩子、结束消息循环。可重复调用。"""
        if self._thread_id:
            # 往那个线程的消息队列里塞一个 WM_QUIT，GetMessageW 就会返回 0
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0

    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        """钩子线程主体：**建消息队列** → 装钩子 → 消息循环 → 卸钩子。

        ## 顺序在这里是决定性的（踩过，而且极难查）

        低级钩子要把键盘事件投递到**装钩子那个线程的消息队列**。而一个线程的
        消息队列是**第一次碰消息 API 时才创建**的。原来的顺序是"先
        ``SetWindowsHookExW``、进循环时才第一次 ``GetMessageW``" ——
        也就是**队列还不存在就装了钩子**。

        后果正是最难查的那种：``SetWindowsHookExW`` 返回**有效句柄**、
        ``GetLastError`` 是 0、"装上了"看起来一切正常，但回调**一次都不会被调用**
        （外部表现就是"失焦后快捷键无效"）。

        所以先 ``PeekMessageW`` 一次把队列建出来，再装钩子。
        """
        try:
            self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

            # 1) 先把本线程的消息队列建出来（PeekMessage 的副作用）。
            #    用 PM_NOREMOVE，不取走任何消息，只为触发队列创建。
            msg = _wintypes.MSG()
            ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_NOREMOVE)

            # 2) 现在装钩子 —— 事件有地方投递了
            self._proc = _HOOKPROC(self._callback)
            self._hook = ctypes.windll.user32.SetWindowsHookExW(
                _WH_KEYBOARD_LL, self._proc, None, 0
            )
            if not self._hook:
                log.warning("SetWindowsHookExW 失败: %s", ctypes.get_last_error())
                return
            self._ok = True
            self._ready.set()

            # 3) 消息循环
            while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        except Exception:  # pragma: no cover - 取决于平台
            log.exception("全局快捷键线程出错")
        finally:
            self._ready.set()
            if self._hook:
                ctypes.windll.user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        """低级键盘钩子的回调。**必须极短** —— 它挂在整个系统的输入路径上。

        ## 为什么这里有一句 debug 日志

        "全局快捷键不生效"最难查的地方是**分不清两种情况**：钩子根本没被调用，
        还是调用了但没匹配上。两者的修法完全不同，而外部看都是"按了没反应"。

        所以这里在**收到任意按键**时留一条 debug 日志（默认级别不打印，
        要查的时候开 DEBUG 就行）。代价是每次按键多一次 `isEnabledFor` 判断 ——
        在钩子回调里可以接受（它不做字符串格式化，日志级别不够就直接返回）。
        """
        try:
            if code >= 0:
                info = ctypes.cast(
                    lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)
                ).contents
                vk = int(info.vkCode)
                if wparam in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                    self._seen += 1
                    if log.isEnabledFor(logging.DEBUG):
                        log.debug(
                            "[hotkey] 钩子收到按键 vk=0x%02X held=%d（累计 %d 次）",
                            vk,
                            self._held,
                            self._seen,
                        )
                    self._note_modifier(vk, down=True)
                    # 修饰键自己按下时不算触发
                    if vk not in (_VK_SHIFT, _VK_CONTROL, _VK_MENU, _VK_LWIN, _VK_RWIN):
                        for hotkey in self._hotkeys:
                            if matches(hotkey, vk, self._held):
                                log.debug("[hotkey] 命中 %s -> 发信号", hotkey.action)
                                # 队列投递到界面线程；这里只发信号，不干活
                                self.triggered.emit(hotkey.action)
                                break
                elif wparam in (_WM_KEYUP, _WM_SYSKEYUP):
                    self._note_modifier(vk, down=False)
        except Exception:  # pragma: no cover - 回调里绝不能抛
            pass
        return ctypes.windll.user32.CallNextHookEx(None, code, wparam, lparam)

    def _note_modifier(self, vk: int, *, down: bool) -> None:
        bit = {
            _VK_SHIFT: MOD_SHIFT,
            _VK_CONTROL: MOD_CONTROL,
            _VK_MENU: MOD_ALT,
            _VK_LWIN: MOD_WIN,
            _VK_RWIN: MOD_WIN,
        }.get(vk)
        if bit is None:
            return
        if down:
            self._held |= bit
        else:
            self._held &= ~bit


if sys.platform == "win32":

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", _wintypes.DWORD),
            ("scanCode", _wintypes.DWORD),
            ("flags", _wintypes.DWORD),
            ("time", _wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(_wintypes.ULONG)),
        ]

    _HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_int, _wintypes.WPARAM, _wintypes.LPARAM
    )

    def _declare_win32() -> None:
        """给要用的 Win32 函数声明参数类型。

        ## 不声明会怎样（踩过，而且极难查）

        ctypes 默认把没声明的参数当 **32 位 ``int``**。而 ``LPARAM`` /
        ``WPARAM`` 在 64 位 Windows 上是 **8 字节**，钩子回调收到的 ``lparam``
        是个 64 位指针 —— 于是 ``CallNextHookEx(h, code, wparam, lparam)``
        在最后一步抛 ``OverflowError: int too long to convert``。

        那个异常被回调的兜底 ``except`` 吞掉，表现是**钩子一个键都收不到**，
        而"装钩子成功""线程在跑"全都是正常的 —— 没有任何线索指向类型声明。

        实测抓到它的方式：直接调 ``service._callback(...)`` 传一个伪造的
        ``KBDLLHOOKSTRUCT`` 指针，异常就出来了。（真按键在这个环境验不了，
        因为输入注入被拦。）
        """
        u = ctypes.windll.user32
        u.CallNextHookEx.argtypes = [
            _wintypes.HHOOK,
            ctypes.c_int,
            _wintypes.WPARAM,
            _wintypes.LPARAM,
        ]
        u.CallNextHookEx.restype = ctypes.c_ssize_t
        u.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            _HOOKPROC,
            ctypes.c_void_p,
            _wintypes.DWORD,
        ]
        u.SetWindowsHookExW.restype = _wintypes.HHOOK
        u.UnhookWindowsHookEx.argtypes = [_wintypes.HHOOK]
        u.UnhookWindowsHookEx.restype = _wintypes.BOOL
        u.GetMessageW.argtypes = [
            ctypes.POINTER(_wintypes.MSG),
            _wintypes.HWND,
            _wintypes.UINT,
            _wintypes.UINT,
        ]
        u.GetMessageW.restype = ctypes.c_int
        u.PeekMessageW.argtypes = [
            ctypes.POINTER(_wintypes.MSG),
            _wintypes.HWND,
            _wintypes.UINT,
            _wintypes.UINT,
            _wintypes.UINT,
        ]
        u.PeekMessageW.restype = _wintypes.BOOL

    _declare_win32()

else:  # pragma: no cover - 非 Windows 不会走到装钩子那条路
    _KBDLLHOOKSTRUCT = None  # type: ignore[assignment,misc]
    _HOOKPROC = None  # type: ignore[assignment,misc]
