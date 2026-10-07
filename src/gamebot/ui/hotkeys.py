"""全局快捷键 —— 界面没焦点时也能按。

## 用 ``pynput`` 的监听钩子

这一段原来是 ``RegisterHotKey`` + ``QAbstractNativeEventFilter``（200 多行），
现在换成 ``pynput.keyboard.GlobalHotKeys``。**换的理由是同一个游戏上已经有一个
跑通的实现**：``vision_workflow``（``vision_bot/ui/services/hotkeys.py``）就这几行::

    from pynput import keyboard
    listener = keyboard.GlobalHotKeys({"<f9>": callback})
    listener.start()

两种机制的区别（这才是换的根本原因）：

============================  ==========================  ====================
                             ``RegisterHotKey``          **``pynput`` 钩子**
============================  ==========================  ====================
键被别的软件占了                 **注册失败，按不出来**       照样能监听
会不会吞键（游戏收不到）          **会吞**                    **不吞**
需要先有窗口 / 消息循环           需要                       不需要
"没生效"看得出来吗                要自己读 ``registered``     同左
============================  ==========================  ====================

前两条是决定性的：

* ``RegisterHotKey`` 对**已被占用的组合**返回 ``False``。裸键（``F5`` / ``F9`` /
  ``Esc``）被占非常常见（编辑器、输入法、截图工具、游戏本身），
  这台机器上就实测过 ``F5`` / ``F9`` / ``F12`` / ``Esc`` **全被占** ——
  于是"全局快捷键无效"，而代码看起来完全正确。
* 能注册上的那些**会把键吞掉**：注册 ``Esc`` 之后游戏自己也收不到 ``Esc``。
  对一个"操作游戏"的工具来说这是实打实的副作用。

``pynput`` 装的是低级键盘钩子：**不注册、不占用、不吞键**，只是旁听。
代价是要装一个依赖（``pynput``），以及钩子回调在**它自己的线程**上
（见下面"线程"那一段）。

## 线程：回调不在界面线程

``pynput`` 的监听器跑在自己的线程里，所以回调里**不能直接碰 Qt 控件**。
这里通过 ``triggered`` 信号把动作投回界面线程 —— ``QObject`` 的信号跨线程
发射时 Qt 默认走 ``QueuedConnection``，槽函数在接收者所属线程（主线程）执行。
这正是我们要的，而且不用自己写 ``QMetaObject.invokeMethod``。

## 键的写法

``pynput`` 用的是 ``"<f9>"``、``"<ctrl>+<alt>+<f5>"`` 这种带尖括号的写法，
而我们表里写的是 Qt 的 ``"F9"`` / ``"Ctrl+Alt+F5"``（见
:data:`gamebot.ui.shortcuts.SHORTCUTS`）。转换在 :func:`parse_hotkey` 里做，
**对外仍然只认 Qt 写法** —— 那张表是"一份定义、三处使用"的，不该为这个多学一种语法。

## 非 Windows 上

``pynput`` 在 Linux / macOS 上也能用，所以 :func:`is_supported` 的判断放宽了：
只要 ``pynput`` 导得进来就算支持。导不进来（没装）就返回 False，
界面退回普通快捷键 —— 全局快捷键是增强，不是前置条件。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

__all__ = ["GlobalHotkeys", "Hotkey", "HotkeyPlan", "is_supported", "parse_hotkey"]

#: Qt 写法里修饰键的名字 → ``pynput`` 的写法（带尖括号）。
#: 键名本身小写化就行（``F9`` -> ``<f9>``）。
_MOD_OF: dict[str, str] = {
    "CTRL": "<ctrl>",
    "CONTROL": "<ctrl>",
    "ALT": "<alt>",
    "SHIFT": "<shift>",
    "WIN": "<cmd>",
    "META": "<cmd>",
    "SUPER": "<cmd>",
}

#: 这两个在 ``pynput`` 里就是普通键名，不加尖括号。
_PLAIN_OF: dict[str, str] = {
    "ESC": "esc",
    "ESCAPE": "esc",
    "ENTER": "enter",
    "RETURN": "enter",
    "SPACE": "space",
    "TAB": "tab",
    "DEL": "delete",
    "DELETE": "delete",
}


def is_supported() -> bool:
    """能不能用全局快捷键（``pynput`` 导得进来就行）。"""
    try:
        import pynput  # noqa: F401
    except Exception:
        return False
    return True


@dataclass(frozen=True, slots=True)
class Hotkey:
    """一条已解析出来的全局快捷键。"""

    action: str
    """动作标识（和 :class:`~gamebot.ui.shortcuts.Keymap` 上同名方法对应）。"""

    keys: str
    """原始写法（``"F9"`` / ``"Ctrl+Alt+F5"``）—— **Qt 那套**，用于显示和报错。

    对外一律用这个写法：``SHORTCUTS`` 那张表、按钮 tooltip、帮助对话框
    显示的都是它。``pynput`` 的写法只在这个模块内部出现。
    """

    pynput_keys: str
    """给 ``pynput`` 的写法（``"<f9>"`` / ``"<ctrl>+<alt>+<f5>"``）。"""

    @property
    def display(self) -> str:
        return self.keys


def parse_hotkey(action: str, keys: str) -> Hotkey | None:
    """把 Qt 写法的 ``"Ctrl+Alt+F5"`` 解析成 :class:`Hotkey`。认不出来返回 ``None``。

    认不出来就跳过这一条（记 warning），而不是抛异常 —— 快捷键少一条不该让
    整个界面起不来。**但一定要出声**：跳过而不报的症状是"我明明写了却没生效"。

    ## 为什么不用 ``QKeySequence`` 解析

    上一版用 ``QKeySequence``，它有两个坑（都在真机上踩过）：

    * 不认的键名会**静默**给 ``Qt::Key_unknown``（``"PageUp"`` / ``"Win"``
      都不认，得写 ``"PgUp"`` / ``"Meta"``）；
    * PySide6 里 ``int(flag)`` 会 ``TypeError``，得走 ``.value``。

    而 ``pynput`` 要的本来就是"修饰键 + 主键"这种**很简单的语法**，
    自己按 ``+`` 拆开反而更直白、也更好报错（"这个修饰键我不认识"能说清是哪个）。
    """
    parts = [p.strip() for p in keys.split("+") if p.strip()]
    if not parts:
        log.warning("全局快捷键 %r 的写法是空的", action)
        return None

    *mods, main = parts
    pieces: list[str] = []
    for name in mods:
        piece = _MOD_OF.get(name.upper())
        if piece is None:
            log.warning(
                "全局快捷键 %r 里的修饰键 %r 不认识 —— 这条不会生效。"
                "认识的写法: Ctrl / Alt / Shift / Win",
                action,
                name,
            )
            return None
        pieces.append(piece)

    upper = main.upper()
    if upper in _PLAIN_OF:
        pieces.append(_PLAIN_OF[upper])
    elif len(upper) == 1 and upper.isalnum():
        # 单字符键（A-Z / 0-9）：pynput 直接收小写字母 / 数字
        pieces.append(upper.lower())
    elif upper.startswith("F") and upper[1:].isdigit() and 1 <= int(upper[1:]) <= 24:
        # 功能键必须带尖括号：pynput 的 "<f9>"
        pieces.append(f"<{upper.lower()}>")
    else:
        log.warning(
            "全局快捷键 %r 的主键 %r 不认识 —— 这条不会生效。"
            "认识的写法: F1-F24 / A-Z / 0-9 / Esc / Enter / Space / Tab / Delete",
            action,
            main,
        )
        return None

    return Hotkey(action=action, keys=keys, pynput_keys="+".join(pieces))


@dataclass(frozen=True, slots=True)
class HotkeyPlan:
    """一个动作的**候选键**，首选在前。

    ## 为什么还留着"候选"

    ``RegisterHotKey`` 的时代这是必需的（键被占就注册不上）。``pynput``
    **不需要**它 —— 钩子不占键，同一个键被几个软件监听都行。

    保留这个类型是为了**不改动** :mod:`gamebot.ui.shortcuts` 和帮助对话框：
    它们按"计划 -> 实际生效的键"这套读。现在候选里永远只有首选，
    但接口没变，将来真要退到备选也不用改上层。
    """

    action: str
    candidates: tuple[Hotkey, ...]

    @property
    def preferred(self) -> Hotkey:
        return self.candidates[0]


class GlobalHotkeys(QObject):
    """全局监听几条组合键，命中就发 :attr:`triggered`。

    :param plans: 每个动作一串候选（首选在前）。现在只会用首选。
    :param parent: Qt 父对象（信号回到它所属的线程）。
    """

    #: 命中了哪条快捷键（参数是 ``action``）。
    triggered = Signal(str)

    #: 一条候选键**解析失败**（参数是原始写法）。
    #:
    #: 注意语义和上一版不同：上一版是"注册失败（被别的软件占了）"，
    #: 现在是"写法不对"。``pynput`` 不会被占用问题挡住，所以这个信号
    #: 只会在配置写错时发 —— 那正是最该被看见的情况。
    failed = Signal(str)

    def __init__(self, plans: list[HotkeyPlan], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plans = list(plans)
        self._registered: list[Hotkey] = []
        self._failed: list[Hotkey] = []
        self._listener: Any = None
        #: ``pynput`` 的写法 -> 动作。回调只拿得到键串，靠它反查。
        self._by_pynput: dict[str, str] = {}

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
        """解析失败的那些写法。"""
        return list(self._failed)

    @property
    def running(self) -> bool:
        return self._listener is not None

    def start(self) -> bool:
        """开始监听。返回"监听器起来了吗"。

        **不抛异常**：装不上就返回 ``False``，界面退回普通快捷键。
        没有"必须在主线程调用"的限制了 —— ``pynput`` 自己起线程，
        而且回调走信号投回界面线程（见模块 docstring 的"线程"那段）。
        """
        if self._listener is not None or not self._plans:
            return False
        try:
            from pynput import keyboard
        except Exception as exc:
            log.warning("全局快捷键不可用（pynput 没装好）: %s", exc)
            return False

        combos: dict[str, Any] = {}
        self._by_pynput = {}
        for plan in self._plans:
            for candidate in plan.candidates:
                if candidate.pynput_keys in combos:
                    # 同一个键被两个动作抢：保留先声明的那个，并出声
                    log.warning(
                        "全局快捷键 %s 被多个动作占用，%s 用不上",
                        candidate.keys,
                        plan.action,
                    )
                    self._failed.append(candidate)
                    continue
                combos[candidate.pynput_keys] = (
                    lambda action=plan.action: self._fire(action)
                )
                self._by_pynput[candidate.pynput_keys] = plan.action
                self._registered.append(candidate)
                log.info("全局快捷键已监听: %s -> %s", candidate.keys, plan.action)
                break  # 每个动作只用首选

        if not combos:
            return False
        try:
            self._listener = keyboard.GlobalHotKeys(combos)
            self._listener.start()
        except Exception as exc:  # pragma: no cover - 钩子起不来（权限/平台）
            log.warning("全局快捷键监听器起不来: %s", exc)
            self._listener = None
            self._registered.clear()
            return False
        return True

    def stop(self) -> None:
        """停止监听。可重复调用。

        ``pynput`` 的钩子**没有占用任何键**，所以这里不需要"注销"那一步 ——
        停掉监听器就干净了（上一版必须把 ``(hwnd, id)`` 原样
        ``UnregisterHotKey``，否则那个键会一直被占着，退出后别的软件也用不了）。
        """
        listener, self._listener = self._listener, None
        self._registered.clear()
        self._by_pynput.clear()
        if listener is None:
            return
        try:
            listener.stop()
        except Exception as exc:  # pragma: no cover - 停不掉也不该让退出崩
            log.debug("停止全局快捷键监听器时出错（忽略）: %s", exc)

    # ------------------------------------------------------------------ #
    def _fire(self, action: str) -> None:
        """钩子线程里的回调 —— **只发信号，不碰控件**。

        ``QObject`` 信号跨线程发射时 Qt 默认用 ``QueuedConnection``，
        所以槽函数会在接收者所在线程（界面主线程）执行。
        在这里直接调界面代码会随机崩 —— 那是 Qt 里最经典的一类崩溃。
        """
        log.debug("[hotkey] 命中 -> %s", action)
        self.triggered.emit(action)
