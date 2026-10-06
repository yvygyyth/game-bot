"""快捷键表 —— **一份定义，三处使用**。

## 为什么要单独一个文件

快捷键最容易出的问题不是"没绑上"，而是**说的和做的不一致**：
tooltip 里写着 F5，代码里绑的却是 F6；帮助里写着 Esc 停止，实际绑在 F7。
过两周连作者自己都记不清哪个对。

所以这里只留一张表，然后由它派生：

1. 真正绑定的 ``QShortcut``；
2. 按钮 tooltip 后面自动附上的 ``（F5）``；
3. ``F1`` 帮助对话框里那份清单。

三处都从同一份数据长出来，就没法对不上。

## 为什么不写进菜单栏

菜单栏会多占一行高度，而这是个"长时间盯着看"的工具，屏幕高度给日志和
带框的图更值。所以用 ``F1`` 弹一个帮助框代替菜单里的"快捷键"项。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtGui import QKeySequence, QShortcut

from .hotkeys import GlobalHotkeys, is_supported, parse_hotkey

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

__all__ = ["SHORTCUTS", "Keymap", "Shortcut"]


@dataclass(frozen=True, slots=True)
class Shortcut:
    """一条快捷键。"""

    action: str
    """动作标识（和 :class:`Keymap` 上同名方法的 ``action`` 参数对应）。"""

    keys: str
    """Qt 的键序列写法，如 ``"F5"`` / ``"Ctrl+1"``。"""

    label: str
    """给人看的说明。"""

    button: str = ""
    """对应哪个按钮（用来把 ``（F5）`` 追加到它的 tooltip 上）。空 = 没有按钮。"""

    global_hotkey: bool = False
    """界面没焦点时也要能按吗（走 :mod:`gamebot.ui.hotkeys`）。

    **只给操作运行状态的那几个开**（开始 / 停止 / 帮助）—— 它们是"游戏在前台、
    界面在后台"时要按的。切页那几条（``Ctrl+1/2/3``）只在看界面时按，
    占了全局没有意义，还会白白和别的软件抢这几个键。

    全局快捷键有个**必须知道的代价**：那条键从此在整个系统里都归本工具管。
    对 ``Esc`` 没问题（游戏照常收到，低级钩子只观察不拦）；但 ``F5`` 是很多
    编辑器／IDE 的"运行/调试"，全局之后你按它就会把脚本跑起来。
    真被占了就把这里的 ``global_hotkey`` 关掉，界面内照样能按。
    """

    alias: bool = False
    """这是**同一个动作的另一个键**（别名），不是新动作。

    为什么要区分：:class:`Shortcut` 是"一个键 → 一个动作"的绑定，而
    ``action`` 在表里默认是唯一的（有测试钉着）。别名会让它出现两次 ——
    那不是重复定义，是**同一动作的第二个键**，所以用这个字段显式标出来。

    实际用途：``stop`` 同时给 ``Esc`` 和 ``F9``。``Esc`` 太常被别的软件占用，
    而全局钩子在 Windows 上是**链式**的（先装的先拿到，吞掉的后面的就收不到）；
    给一个几乎没人抢的 ``F9`` 既能救急，也是个诊断手段 ——
    ``F9`` 有效而 ``Esc`` 无效，就说明是 ``Esc`` 被抢了，而不是钩子没装上。
    """

    @property
    def hint(self) -> str:
        return f"（{self.keys}）"


#: 全部快捷键。**改这里就够了** —— 绑定、tooltip、帮助都是它派生的。
#:
#: 选键的几个考虑：
#:
#: * ``F5`` 开始 / ``Esc`` 停止 —— 沿用 IDE 和播放器的直觉，闭眼能按；
#: * ``Esc`` 只在**运行中**才有反应（``QShortcut`` 跟着按钮的 enabled 走），
#:   所以平时按它不会莫名其妙触发什么，也不和下拉框的"关掉弹窗"打架；
#: * ``Ctrl+1/2/3`` 切左边三页；``F1`` 出帮助。
#:
#: ``global_hotkey=True`` 的只有开始 / 停止 / 帮助 —— 这三条要"游戏在前台、
#: 本界面在后台"时也能按。理由和代价见 :attr:`Shortcut.global_hotkey`。
#:
#: ## 停止为什么有两个键
#:
#: ``Esc`` 是直觉上最好按的，但**它太常被别的软件占用**（编辑器、输入法、
#: 各种悬浮工具都会挂全局 ``Esc``）。全局快捷键在 Windows 上是**链式**的：
#: 先装的先拿到事件，而"先拿到"的那个如果吞掉它（``RegisterHotKey`` 就吞），
#: 后面的就收不到了。
#:
#: 所以停止给两个键：``Esc``（顺手）+ ``F9``（几乎没人抢）。
#: **这也是一个诊断手段**：如果 ``F9`` 全局有效而 ``Esc`` 无效，
#: 那问题就是"``Esc`` 被别的软件抢了"，而不是本工具的钩子没装上。
SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("run", "F5", "开始运行", button="start", global_hotkey=True),
    Shortcut("stop", "Esc", "停止（毫秒级）", button="stop", global_hotkey=True),
    Shortcut("stop", "F9", "停止（毫秒级）", button="stop", global_hotkey=True, alias=True),
    Shortcut("detect", "F7", "重新检测可见软件窗口", button="detect"),
    Shortcut("page_diagram", "Ctrl+1", "切到「状态 / 流程」"),
    Shortcut("page_recognition", "Ctrl+2", "切到「识图日志」"),
    Shortcut("page_check", "Ctrl+3", "切到「检查输出」"),
    Shortcut("help", "F1", "显示这份快捷键说明", global_hotkey=True),
)


class Keymap:
    """按 :data:`SHORTCUTS` 把动作绑到键上，并给 UI 提供提示文字。

    ``bindings`` 里给的每个动作都要有对应的可调用对象；缺了的会被跳过
    （而不是抛异常）—— 快捷键少一个不影响界面能用。
    """

    def __init__(self, parent: QWidget, bindings: dict[str, object]) -> None:
        self.parent = parent
        self._shortcuts: list[QShortcut] = []
        self._bindings = bindings
        #: 全局快捷键服务（界面没焦点时也能按）。装不上就是 None，界面照常用。
        self._global: GlobalHotkeys | None = None
        #: 哪几条真的挂上了全局。给帮助对话框显示用。
        self._global_ok: set[str] = set()

        for spec in SHORTCUTS:
            target = bindings.get(spec.action)
            if target is None or not callable(target):
                continue
            shortcut = QShortcut(QKeySequence(spec.keys), parent)
            # 不设 context：``QShortcut`` 默认就是 ``WindowShortcut`` ——
            # 焦点在哪个控件上都能按到（"窗口级快捷键"的常规行为）。
            # 一个有用的副作用：焦点在下拉框里、弹窗开着时，Esc 会先被
            # 下拉框自己吃掉（关弹窗），不会误触"停止"。
            shortcut.activated.connect(target)
            self._shortcuts.append(shortcut)

        self._start_global()

    # ------------------------------------------------------------------ #
    # 全局快捷键
    # ------------------------------------------------------------------ #
    def _start_global(self) -> None:
        """把标了 ``global_hotkey`` 的几条挂到系统级。

        **界面内那份照挂**（上面那个循环）—— 全局和窗口内是两套并行：
        全局负责"没焦点时也能按"，窗口内那份在界面有焦点时照旧生效。
        两边同时收到同一次按键是可能的（钩子不吞键），所以动作必须**幂等**：
        ``stop`` 重复调没事，``run`` 在跑的时候直接 return。这不是巧合，
        是这两条动作本来就该有的性质。
        """
        wanted = [spec for spec in SHORTCUTS if spec.global_hotkey]
        if not wanted:
            return
        parsed = []
        for spec in wanted:
            target = self._bindings.get(spec.action)
            if target is None or not callable(target):
                continue
            hotkey = parse_hotkey(spec.action, spec.keys)
            if hotkey is not None:
                parsed.append(hotkey)

        service = GlobalHotkeys(parsed, parent=self.parent)
        service.triggered.connect(self._on_global)
        if service.start():
            self._global = service
            self._global_ok = {h.action for h in parsed}
        else:
            log.info(
                "全局快捷键没启用（%s）—— 界面内快捷键不受影响",
                "非 Windows" if not is_supported() else "装钩子失败",
            )

    @Slot(str)
    def _on_global(self, action: str) -> None:
        """全局钩子命中。**槽函数在界面线程执行**（跨线程信号是队列投递）。"""
        target = self._bindings.get(action)
        if callable(target):
            target()

    def stop(self) -> None:
        """卸掉全局钩子。关窗时调 —— 钩子不卸掉，进程会被它拽着不退出。"""
        if self._global is not None:
            self._global.stop()
            self._global = None

    @property
    def globals_active(self) -> set[str]:
        """哪几条动作真的挂上了系统级快捷键（空集合 = 这个平台上没有）。"""
        return set(self._global_ok)

    def __len__(self) -> int:
        return len(self._shortcuts)

    def hint_for(self, action: str) -> str:
        """某个动作的 ``（F5）`` 后缀；没有就返回空串。"""
        spec = _find(action)
        return spec.hint if spec else ""

    def help_lines(self) -> list[str]:
        """给帮助对话框用的清单（不带按钮对应关系，只有键和说明）。

        ``global_hotkey`` 的那几条标一个 ``*``，并在末尾解释 —— 否则用户
        按不出来时不知道该怀疑"焦点不在界面"还是"这条本来就没挂全局"。
        """
        lines = []
        for spec in SHORTCUTS:
            mark = "*" if spec.action in self._global_ok else " "
            lines.append(f" {mark}{spec.keys:<12} {spec.label}")
        if self._global_ok:
            lines.append("")
            lines.append("  * = 界面没焦点时也能按（系统级，游戏在前台照样生效）")
        elif any(spec.global_hotkey for spec in SHORTCUTS):
            lines.append("")
            lines.append("  这个平台上没有系统级快捷键，所有键都要求界面有焦点")
        return lines

    def add_tooltips(self, buttons: dict[str, object]) -> None:
        """把 ``（F5）`` 追加到按钮的 tooltip 上。

        **自动追加而不是手写**：手写的话，改了键位就会忘了改 tooltip，
        然后界面上写着一个按不出来的键 —— 比没有提示更让人困惑。
        """
        for spec in SHORTCUTS:
            if not spec.button:
                continue
            button = buttons.get(spec.button)
            if button is None:
                continue
            setter = getattr(button, "setToolTip", None)
            getter = getattr(button, "toolTip", None)
            if setter is None or getter is None:
                continue
            existing = getter() or ""
            if spec.hint in existing:  # 别在重复调用时越加越长
                continue
            setter(f"{existing} {spec.hint}".strip())


def _find(action: str) -> Shortcut | None:
    for spec in SHORTCUTS:
        if spec.action == action:
            return spec
    return None
