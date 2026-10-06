"""全局快捷键 —— 界面没焦点时也能按。

## 用 `RegisterHotKey` + Qt 自己的事件循环

Windows 上全局热键有两条路，**先用的是低级键盘钩子，它不工作**，所以换成这条：

| | 低级钩子 ``WH_KEYBOARD_LL`` | **``RegisterHotKey``（现在用这个）** |
|---|---|---|
| 原理 | 系统**跨线程回调我的 Python 函数** | 系统往**一个线程的队列**投 ``WM_HOTKEY`` |
| 失败表现 | 句柄有效、``GetLastError=0``，但回调一次都不被调用 | 注册失败**返回 False**，带错误码 |
| 代价 | 不吞键 | **吞键**：注册的键不再发给别的窗口 |

钩子那条路的失败是**静默**的（所有"装上了"的迹象都对，就是不回调），
在真机上耗了几轮都没定位到 —— 而这个开发环境**拦键盘注入**
（``SendInput`` 返回成功但钩子收不到），所以"真按键"在这里根本测不了。
换到 ``RegisterHotKey`` 之后，**成没成功是能直接看出来的**。

## 为什么不要自己的线程

第一版换过来时，我起了一个后台线程建**消息专用窗口**、自己泵 ``GetMessageW``。
结果：测试全过，但**进程在退出时 access violation**。

原因是那个方案要自己管 Win32 生命周期，而这里有三个坑，每个都能让进程崩：

* ``CreateWindowExW`` 注册的窗口类、窗口过程回调**必须活得比窗口久**
  （Python 对象被 GC 掉，系统就调到一个已释放的函数指针）；
* ``DestroyWindow`` / ``UnregisterHotKey`` **必须在建窗口的那个线程**上调用；
* Qt 已经在主线程泵消息，我再去另一个线程建窗口、泵消息，两套循环互相干扰。

而 **Qt 本来就有"把原生消息交给 Python 看"的官方入口**：
:class:`QAbstractNativeEventFilter`。用它之后：

* **不需要线程** —— 注册和收消息都在主线程;
* **不需要建窗口、不需要注册窗口类** —— 直接挂在 Qt 已有的窗口上;
* **不需要跨线程发信号** —— 本来就在界面线程。

少掉的每一件事都是一个原来会崩的地方。

## 代价：注册的键会被吞掉

注册 ``Esc`` 之后**游戏自己也收不到 ``Esc``**。取舍是：

* Windows **没有**"既全局监听又不占键"的官方 API；
* 所以只注册**真正需要全局的三条**（开始 / 停止 / 帮助），
  其余留在窗口内（``QShortcut``），不占系统的键；
* ``stop`` 给两个键（``Esc`` + ``F9``）：``Esc`` 顺手，``F9`` 几乎没人抢。

## 非 Windows 上降级

``start()`` 返回 False，界面继续用普通快捷键 —— 全局快捷键是增强，不是前置条件。
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

if sys.platform == "win32":
    import ctypes.wintypes as _wintypes
else:  # pragma: no cover - 非 Windows 上这个模块只用于"降级"
    _wintypes = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

__all__ = ["GlobalHotkeys", "Hotkey", "HotkeyPlan", "is_supported", "parse_hotkey"]

# ---------------------------------------------------------------- Win32 常量
_WM_HOTKEY = 0x0312
#: 按住不放时不要重复触发（否则"停止"会被连发，日志刷屏）
_MOD_NOREPEAT = 0x4000

#: 修饰键位。和 ``win32con.MOD_*`` 一致。
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008


def _as_int(value: Any) -> int:
    """把 Qt 的枚举/flag 取成整数。

    **PySide6 里 ``int(SomeFlag.Foo)`` 会 TypeError** —— flag 对象不是数字，
    得走 ``.value``。这个坑在这个文件里踩了两次（修饰位、键码），
    所以收成一个函数：以后只可能对一次。
    """
    return int(getattr(value, "value", value))


def _build_vk_table() -> dict[int, int]:
    """Qt 的键 → Windows 虚拟键码。

    ## 为什么从 Qt 枚举现搭，而不是手写常量

    手写过一版，两个地方错了，而且**都不报错、只是按不出来**：

    * 功能键的序号算错：``F5`` 落到了 ``0x22``（那是 PageUp 的键码）；
    * Qt6 的修饰位记反了：``ControlModifier`` 是 ``0x04000000``、
      ``ShiftModifier`` 是 ``0x02000000``，我按 Qt5 的印象写反了。

    所以键码从 ``Qt.Key`` 取、修饰位从 ``Qt.KeyboardModifier`` 取 ——
    让 Qt 自己去保证数值对。
    """
    from PySide6.QtCore import Qt

    table: dict[int, int] = {}
    key = Qt.Key
    # A-Z：Qt 里就是 0x41-0x5A，和 Win32 一致
    for i in range(26):
        table[_as_int(key.Key_A) + i] = 0x41 + i
    # F1-F24：两边都连续（Win32 从 0x70 起）
    for i in range(24):
        table[_as_int(key.Key_F1) + i] = 0x70 + i
    # 数字 0-9：Qt 的 Key_0..Key_9 就是 0x30..0x39
    for i in range(10):
        table[_as_int(key.Key_0) + i] = 0x30 + i

    table.update(
        {
            _as_int(key.Key_Escape): 0x1B,
            _as_int(key.Key_Tab): 0x09,
            _as_int(key.Key_Backspace): 0x08,
            _as_int(key.Key_Return): 0x0D,
            _as_int(key.Key_Enter): 0x0D,
            _as_int(key.Key_Space): 0x20,
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
        }
    )
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
    """原始写法（``"Ctrl+Alt+F12"``），用于显示和报错。"""

    @property
    def display(self) -> str:
        parts = []
        if self.mods & MOD_CONTROL:
            parts.append("Ctrl")
        if self.mods & MOD_ALT:
            parts.append("Alt")
        if self.mods & MOD_SHIFT:
            parts.append("Shift")
        if self.mods & MOD_WIN:
            parts.append("Win")
        parts.append(self.keys.split("+")[-1])
        return "+".join(parts)


def parse_hotkey(action: str, keys: str) -> Hotkey | None:
    """把 ``"Ctrl+Alt+F12"`` 解析成 :class:`Hotkey`。认不出来返回 ``None``。

    认不出来就跳过这一条，而不是抛异常 —— 快捷键少一条不该让整个界面起不来。
    **但一定要记 warning**：跳过而不出声的症状是"我明明写了却没生效"。

    ## 认不出来的两种情形（都实测过）

    * **键的写法 Qt 不认** —— ``QKeySequence`` 会**静默**返回
      ``Qt::Key_unknown``。踩过的例子：``"PageUp"`` / ``"PageDown"`` /
      ``"Win"``；Qt 认的是 ``"PgUp"`` / ``"PgDown"`` / ``"Meta"``；
    * 键在 Qt 里认、但不在虚拟键码表里。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence

    sequence = QKeySequence(keys)
    if sequence.count() != 1:
        log.warning("全局快捷键 %r 的写法解析不出单个组合: %r", action, keys)
        return None
    # 取第一条组合。**只能走下标，而 PySide6 的 stub 没给 `__getitem__`**，
    # 所以这一处必须 ignore —— 试过改用 `toString()`，结果**语义坏了**：
    # Qt 不认的键名 `toString()` 返回空串，"键名拼错"和"解析不出组合"混成一类。
    combo = sequence[0]  # type: ignore[index]
    key = _as_int(combo.key())
    if key == _as_int(Qt.Key.Key_unknown):
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
    # 注意：``keyboardModifiers()`` 返回的是 Qt 的 flag 对象，**不能直接 int()**。
    raw = _as_int(combo.keyboardModifiers())
    for bit, mod in _MOD_BITS:
        if raw & bit:
            mods |= mod
    return Hotkey(action=action, vk=vk, mods=mods, keys=keys)


def is_supported() -> bool:
    """这个平台上能不能用全局快捷键。"""
    return sys.platform == "win32"


@dataclass(frozen=True, slots=True)
class HotkeyPlan:
    """一个动作的**候选键**，首选在前。

    ``RegisterHotKey`` 对已被占用的组合返回 False，所以"首选不行就用备选"
    是唯一的办法 —— 而备选必须**预先声明**（而不是运行时瞎凑一个组合：
    那样帮助里显示的键和实际生效的键就对不上了）。
    """

    action: str
    candidates: tuple[Hotkey, ...]

    @property
    def preferred(self) -> Hotkey:
        return self.candidates[0]


if sys.platform == "win32":

    def _declare_win32() -> None:
        """声明参数与返回类型。

        **不声明会怎样**（踩过，而且极难查）：ctypes 默认把没声明的参数当 32 位
        ``int``，而指针/句柄在 64 位上是 8 字节 —— 轻则 ``OverflowError``，
        重则**访问到错误的内存**（实测让进程直接 access violation）。
        """
        u = ctypes.windll.user32
        u.RegisterHotKey.argtypes = [
            _wintypes.HWND,
            ctypes.c_int,
            _wintypes.UINT,
            _wintypes.UINT,
        ]
        u.RegisterHotKey.restype = _wintypes.BOOL
        u.UnregisterHotKey.argtypes = [_wintypes.HWND, ctypes.c_int]
        u.UnregisterHotKey.restype = _wintypes.BOOL

    _declare_win32()


class _HotkeyFilter(QAbstractNativeEventFilter):
    """把 ``WM_HOTKEY`` 从 Qt 的事件循环里捞出来。

    Qt 在主线程泵消息，``WM_HOTKEY`` 会先经过它 —— 这个过滤器就是官方给的
    "原生消息交给 Python 看"的入口。用它就不必自己建窗口、自己泵消息。
    """

    def __init__(self, service: GlobalHotkeys) -> None:
        super().__init__()
        self._service = service

    def nativeEventFilter(self, event_type: Any, message: Any) -> Any:
        if event_type == b"windows_generic_MSG":
            try:
                msg = _wintypes.MSG.from_address(int(message))
            except Exception:  # pragma: no cover - 消息形状不对就放行
                return False, 0
            if msg.message == _WM_HOTKEY:
                self._service._on_hotkey(int(msg.wParam))
        # (False, 0) = 不拦截，继续交给 Qt 正常处理
        return False, 0


class GlobalHotkeys(QObject):
    """注册全局热键，命中就发 :attr:`triggered`。

    ## 每个动作可以带**备选键**

    ``RegisterHotKey`` 对**已经被别的软件占用的组合**返回 False，而裸键
    （``F5`` / ``Esc``）被占很常见 —— 实测某台机器上 ``F5`` / ``F9`` / ``F12`` /
    ``Esc`` **全都被占**，``Ctrl+Alt+*`` 全可用。

    所以这里收的是"每个动作一串候选"（首选在前），逐个试到成功为止。
    注册不上一声不响是**最糟**的失败方式 —— 外部表现和"代码写错了"一模一样。
    现在实际生效的键可以从 :attr:`registered` 读出来，界面会显示它。
    """

    #: 命中了哪条快捷键（参数是 ``action``）。本来就在界面线程，直接投递。
    triggered = Signal(str)

    #: 一条候选键注册失败（参数是原始写法）。界面可以据此说明"这个键被占了"。
    failed = Signal(str)

    def __init__(self, plans: list[HotkeyPlan], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plans = list(plans)
        self._registered: list[Hotkey] = []
        self._failed: list[Hotkey] = []
        self._filter: _HotkeyFilter | None = None
        #: 注册用的窗口句柄（0 = 退回绑线程）。注销时必须用它，见 stop()。
        self._hwnd = 0
        #: `WM_HOTKEY` 的 id → 动作。**不能靠下标算**（见 _on_hotkey）。
        self._id_to_action: dict[int, str] = {}

    # ------------------------------------------------------------------ #
    @property
    def plans(self) -> list[HotkeyPlan]:
        return list(self._plans)

    @property
    def registered(self) -> list[Hotkey]:
        """**实际生效**的那些键（每个动作最多一个）。界面用它显示真实按键。"""
        return list(self._registered)

    @property
    def failed_keys(self) -> list[Hotkey]:
        """试过但被占的那些。"""
        return list(self._failed)

    @property
    def running(self) -> bool:
        """注册还没撤掉吗。"""
        return bool(self._registered)

    def start(self) -> bool:
        """注册并挂上原生事件过滤器。返回"至少注册上一条了吗"。

        **不抛异常**：注册不上就返回 False，界面退回普通快捷键。

        **必须在 Qt 主线程调用** —— 要拿 `QApplication` 装事件过滤器。

        ## 热键绑在**线程**上，不绑窗口

        ``RegisterHotKey`` 的 ``hwnd`` 传 ``NULL`` 时，``WM_HOTKEY`` 投到
        **调用线程的消息队列**。这就够了，而且更好：

        * 不需要先有一个 Qt 窗口（原来要 ``winId()``，界面还没建好就注册不上；
          更糟的是注册在**某个窗口**上、消息进那个队列，而 Qt 未必把它交给过滤器）；
        * 线程就是主线程，而 Qt 一直在泵它 —— 不用自己建窗口、自己起线程。

        （第一版换过来时我起了后台线程建消息窗口自己泵，结果进程退出时
        access violation。原因写在模块开头的 docstring 里。）
        """
        if not is_supported() or not self._plans or self._registered:
            return False
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:  # pragma: no cover - 没有 QApplication 就没什么可挂
            log.warning("没有 QApplication，全局快捷键装不上")
            return False

        u = ctypes.windll.user32
        # 优先绑一个**真实窗口**的 HWND：投给窗口的消息，Qt 一定会转交给
        # 原生事件过滤器。拿不到窗口（界面还没建好）才退回绑线程 ——
        # 那条路消息进线程队列，能不能到过滤器取决于 Qt 的实现细节，
        # 所以它是兜底，不是首选。
        hwnd = self._pick_hwnd(app)
        self._hwnd = hwnd
        log.debug("全局快捷键注册到 %s", f"窗口 {hwnd}" if hwnd else "主线程消息队列（兜底）")

        # **id 的分配和"哪个动作"的对应关系必须记住。**
        # 一个动作可能有多个候选键，但只有第一个注册成功的那个会拿到一个 id。
        # 所以这里是"边注册边发 id、边记下 id → action"，而不是"下标就是 id"。
        self._id_to_action = {}
        next_id = 1
        for plan in self._plans:
            for candidate in plan.candidates:
                ok = u.RegisterHotKey(
                    hwnd, next_id, candidate.mods | _MOD_NOREPEAT, candidate.vk
                )
                if ok:
                    self._id_to_action[next_id] = plan.action
                    next_id += 1
                    self._registered.append(candidate)
                    log.info(
                        "全局快捷键已注册: %s -> %s",
                        candidate.keys,
                        plan.action,
                    )
                    break
                self._failed.append(candidate)
                log.warning(
                    "全局快捷键 %s 注册失败（已被别的软件占用，试下一个候选）",
                    candidate.keys,
                )
                self.failed.emit(candidate.keys)
            else:
                log.warning(
                    "动作 %s 的所有候选键都注册不上 —— 它没有全局快捷键了",
                    plan.action,
                )

        if not self._registered:
            return False
        self._filter = _HotkeyFilter(self)
        app.installNativeEventFilter(self._filter)
        return True

    def stop(self) -> None:
        """注销、摘掉过滤器。可重复调用。"""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if self._filter is not None and app is not None:
            app.removeNativeEventFilter(self._filter)
        self._filter = None
        # **注销时 (hwnd, id) 必须和注册时那对完全一致**，否则注销不掉，
        # 键会一直被占着（表现：退出后那个键在别的软件里也不响应）。
        for hotkey_id in self._id_to_action:
            ctypes.windll.user32.UnregisterHotKey(self._hwnd, hotkey_id)
        self._id_to_action.clear()
        self._hwnd = 0
        self._registered.clear()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _pick_hwnd(app: Any) -> int:
        """找一个属于主线程的窗口句柄；一个都没有就返回 0（退回绑线程）。

        ``winId()`` 会**强制把窗口实现出来**（native window），所以这一步本身
        也保证了后面 ``RegisterHotKey`` 拿到的是有效句柄。
        """
        widget = app.activeWindow() or next(iter(app.topLevelWidgets()), None)
        if widget is None:
            return 0
        try:
            return int(widget.winId())
        except Exception:  # pragma: no cover - 窗口还没实现出来
            return 0

    def _on_hotkey(self, hotkey_id: int) -> None:
        """``WM_HOTKEY`` 的 id → 哪个动作。

        **不能用下标算。** 一个动作可能有多个候选键，只有注册成功的那个拿到
        了 id —— 所以 id 和动作的对应关系是注册时记下来的
        （``_id_to_action``）。用下标算的话，一旦某个首选键被占、退到备选，
        按备选就会触发**别的动作**（比"没反应"更糟）。
        """
        action = self._id_to_action.get(hotkey_id)
        if action is not None:
            log.debug("[hotkey] WM_HOTKEY id=%s -> %s", hotkey_id, action)
            self.triggered.emit(action)
