"""进程完整性级别 —— 判断"我能不能给那个窗口发输入"。

## 为什么需要这个

Windows 的 **UIPI**（User Interface Privilege Isolation，用户界面特权隔离）
规定：**低完整性级别的进程不能给高完整性级别的窗口发输入。**

失效的样子特别有迷惑性：

* ``SetCursorPos`` 照常работает —— **鼠标指针会真的移到目标位置**；
* ``SendInput`` 返回**成功**、``GetLastError() == 0``；
* 但目标窗口**什么都收不到**，没有任何错误。

于是"点不中"看起来像坐标算错了、像游戏不认合成输入、像代码写错了 ——
而真正的原因在**权限级别**上，和脚本一个字的关系都没有。

键盘同理：装在低完整性进程里的键盘钩子收不到高完整性窗口的按键，
所以"界面一失焦快捷键就没反应"。

## 判据

只比一个数：本进程的完整性级别 vs 目标窗口所属进程的完整性级别。
**本级 < 目标级 就一定发不进去**（其余情况能不能进去还要看游戏自己，
但至少 UIPI 不是障碍）。

用 ``logs/tools/integrity_levels.py`` 可以直接列出机器上各进程的级别。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys

__all__ = ["IntegrityLevel", "check_integrity", "level_of_pid", "level_of_window"]

#: 完整性级别的数值（SID 最后一个子授权）。越大越"高"。
_LOW = 0x1000
_MEDIUM = 0x2000
_HIGH = 0x3000

_NAMES = {
    0x0000: "Untrusted",
    _LOW: "Low",
    _MEDIUM: "Medium",
    0x2100: "Medium+",
    _HIGH: "High",
    0x4000: "System",
}


class IntegrityLevel:
    """一个进程的完整性级别。

    :param value: SID 里的数值（``0x1000`` = Low，``0x2000`` = Medium）。
    :param name: 人看的名字。
    """

    __slots__ = ("name", "value")

    def __init__(self, value: int, name: str = "") -> None:
        self.value = value
        self.name = name or _NAMES.get(value, f"未知(0x{value:04X})")

    def __repr__(self) -> str:
        return f"IntegrityLevel({self.name})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, IntegrityLevel) and other.value == self.value

    def __hash__(self) -> int:
        return hash(self.value)


def level_of_pid(pid: int) -> IntegrityLevel | None:
    """读某个进程的完整性级别。读不到返回 ``None``（不抛异常）。

    **读不到不当成失败**：这个函数只用来给出更好的提示，它自己不该成为
    新的失败点。调用方拿到 ``None`` 就按"不知道"处理。
    """
    if sys.platform != "win32":  # pragma: no cover - 非 Windows 没有这个概念
        return None
    try:
        return _level_of_pid_win32(pid)
    except Exception:
        return None


def level_of_window(hwnd: int) -> IntegrityLevel | None:
    """读某个窗口所属进程的完整性级别。"""
    if sys.platform != "win32":  # pragma: no cover
        return None
    try:
        pid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
        if not pid.value:
            return None
        return level_of_pid(pid.value)
    except Exception:
        return None


def _level_of_pid_win32(pid: int) -> IntegrityLevel | None:
    """真正的实现。**ctypes 的参数/返回类型必须声明**。

    不声明会怎样（这个项目在热键那一段踩过同一类坑，而且是同一个原因）：
    ctypes 默认把没声明的参数当 32 位 ``int``，而 64 位上的指针/SID 句柄是
    8 字节 —— 轻则 ``OverflowError``，重则访问到错误的内存。
    """
    k32 = ctypes.windll.kernel32
    adv = ctypes.windll.advapi32

    adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    adv.OpenProcessToken.restype = wt.BOOL
    adv.GetTokenInformation.argtypes = [
        wt.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(wt.DWORD),
    ]
    adv.GetTokenInformation.restype = wt.BOOL
    adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
    adv.GetSidSubAuthority.restype = ctypes.POINTER(ctypes.c_ulong)
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = wt.HANDLE

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]

    class _TokenMandatoryLabel(ctypes.Structure):
        _fields_ = [("Label", _SidAndAttributes)]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008
    TOKEN_INTEGRITY_LEVEL = 25

    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        token = wt.HANDLE()
        if not adv.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            size = wt.DWORD(0)
            adv.GetTokenInformation(
                token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size)
            )
            if not size.value:
                return None
            buffer = ctypes.create_string_buffer(size.value)
            if not adv.GetTokenInformation(
                token, TOKEN_INTEGRITY_LEVEL, buffer, size.value, ctypes.byref(size)
            ):
                return None
            label = ctypes.cast(buffer, ctypes.POINTER(_TokenMandatoryLabel)).contents
            count = adv.GetSidSubAuthorityCount(label.Label.Sid)
            if not count or not count[0]:
                return None
            last = adv.GetSidSubAuthority(label.Label.Sid, count[0] - 1)
            if not last:
                return None
            return IntegrityLevel(int(last[0]))
        finally:
            k32.CloseHandle(token)
    finally:
        k32.CloseHandle(handle)


def check_integrity(window_title: str = "") -> str | None:
    """**能不能给这个窗口发输入？** 不能就返回一段给人看的说明，能就返回 ``None``。

    这是给启动路径和 ``games poke`` 用的一站式检查：

    * 非 Windows -> ``None``（这个平台上没有 UIPI 这回事）；
    * 没给窗口标题 / 找不到窗口 -> ``None``（没什么可判的）；
    * 级别读不出来 -> ``None``（**不猜**，别拿它当失败）；
    * 本级 >= 目标级 -> ``None``；
    * 本级 < 目标级 -> 一段说明：**这就是点击/按键没反应的原因**。

    为什么要返回"说明"而不是一个 bool：这件事的失败是**完全静默**的
    （鼠标都动了，就是没生效），所以光说"不行"没用 ——
    必须把"为什么"和"怎么办"一起给出来。
    """
    if sys.platform != "win32" or not window_title:
        return None
    try:
        import win32gui
    except Exception:  # pragma: no cover - 没装 pywin32 就不做这个检查
        return None
    try:
        hwnd = win32gui.FindWindow(None, window_title)
        if not hwnd:
            # 标题可能是子串匹配的，退一步用枚举
            matches = [
                h
                for h in _visible_windows()
                if window_title.lower() in (win32gui.GetWindowText(h) or "").lower()
            ]
            hwnd = matches[0] if matches else 0
    except Exception:
        return None
    if not hwnd:
        return None

    mine = level_of_pid(ctypes.windll.kernel32.GetCurrentProcessId())
    theirs = level_of_window(hwnd)
    if mine is None or theirs is None:
        return None
    if mine.value >= theirs.value:
        return None
    return (
        f"**权限不够，输入发不进游戏**：本进程完整性级别 = {mine.name}，"
        f"而「{window_title}」= {theirs.name}。\n"
        "  Windows 的 UIPI 规定低完整性进程不能给高完整性窗口发输入 ——\n"
        "  表现正是「鼠标会动、点击无效、失焦后快捷键也没反应」"
        "（SendInput 返回成功但被丢掉）。\n"
        "  怎么办：**从一个普通（非提权受限）的终端启动本程序**，"
        "例如直接在你的 cmd / PowerShell / Windows Terminal 里跑；\n"
        "  如果是从某个沙箱或受限宿主里启动的，它继承的完整性级别会一直带下来。"
    )


def _visible_windows() -> list[int]:
    import win32gui

    found: list[int] = []

    def callback(hwnd: int, _extra: object) -> bool:
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            found.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return found
