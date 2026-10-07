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

from .hotkeys import GlobalHotkeys, HotkeyPlan, is_supported, parse_hotkey

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
    挂全局没有意义。

    ## 现在**不占键、也不吞键**

    全局监听走 ``pynput`` 的键盘钩子（见 :mod:`gamebot.ui.hotkeys` 的说明）：
    它**不注册**这个键，只是旁听。所以：

    * 同一个键被别的软件（编辑器、输入法、游戏本身）用着也照样能监听
      —— 不会出现"被占了就完全没反应"；
    * **游戏自己仍然收得到这个键**。这一点很重要：``F5`` 这类键游戏里
      可能也有用途，旧的 ``RegisterHotKey`` 方案会把它在整个系统里吞掉。

    唯一的注意点：按 ``F5`` 时本工具和游戏都会收到 —— 如果那个键在游戏里有
    作用，就会同时发生两件事。真冲突就把这里的 ``global_hotkey`` 关掉，
    界面内照样能按。
    """

    global_fallback: str = ""
    """**已废弃**（保留字段是为了不破坏已有配置）。

    ``RegisterHotKey`` 的时代需要它：那个 API 对已被别的软件占用的组合返回
    ``False``，而裸键（``F5`` / ``Esc``）被占很常见，所以每个动作要准备一个
    ``Ctrl+Alt+*`` 的备选。

    ``pynput`` 的钩子**不存在"被占用"这回事**（它不注册、不占键），
    所以备选永远不会被用到。留着这个字段和 :data:`SHORTCUTS` 里那些备选值，
    只是为了``Keymap`` 的代码不用改、老配置也不会突然报"未知字段"。
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
#: ## 停止用 `F9`，不用 `Esc`
#:
#: ``Esc`` 是**游戏自己也常用**的键（关弹窗、取消、退出菜单）。虽然现在的
#: ``pynput`` 方案不吞键了（游戏照样收得到），但"按 Esc 同时停脚本又关弹窗"
#: 仍然会让两件事一起发生，不是想要的。
#:
#: ``F9`` 和 ``F5`` 在同一排功能键上，手不用挪，而且游戏基本不用它。
#:
#: ## ``global_fallback`` 现在用不上了
#:
#: 那是 ``RegisterHotKey`` 时代的产物（裸键被占就注册不上，所以要备选）。
#: ``pynput`` 不占键，所以首选永远生效 —— 但字段和值都留着，
#: 见 :attr:`Shortcut.global_fallback`。
SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut(
        "run",
        "F5",
        "开始运行",
        button="start",
        global_hotkey=True,
        global_fallback="Ctrl+Alt+F5",
    ),
    Shortcut(
        "stop",
        "F9",
        "停止（毫秒级）",
        button="stop",
        global_hotkey=True,
        global_fallback="Ctrl+Alt+F9",
    ),
    Shortcut("detect", "F7", "重新检测可见软件窗口", button="detect"),
    Shortcut("page_diagram", "Ctrl+1", "切到「状态 / 流程」"),
    Shortcut("page_recognition", "Ctrl+2", "切到「识图日志」"),
    Shortcut("page_check", "Ctrl+3", "切到「检查输出」"),
    Shortcut(
        "help",
        "F1",
        "显示这份快捷键说明",
        button="",
        global_hotkey=True,
        global_fallback="Ctrl+Alt+F1",
    ),
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
        #: ``action -> **实际生效**的键``。首选被别的软件占了就会是备选键 ——
        #: 帮助里显示它，而不是显示"我们想要的键"（那样用户按不出来还找不到原因）。
        self._global_keys: dict[str, str] = {}

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
        """把标了 ``global_hotkey`` 的几条交给全局监听。

        **界面内那份照挂**（上面那个循环）—— 全局和窗口内是两套并行：
        全局负责"没焦点时也能按"，窗口内那份在界面有焦点时照旧生效。
        两边同时收到同一次按键是可能的（``pynput`` 钩子不吞键），
        所以动作必须**幂等**：``stop`` 重复调没事，``run`` 在跑的时候直接 return。
        这不是巧合，是这两条动作本来就该有的性质。

        ## 候选键现在只用首选

        ``pynput`` 的钩子**不存在"键被占用"**（它不注册、不占键），
        所以 :attr:`Shortcut.global_fallback` 永远用不上。这里仍然把它放进
        候选列表，是为了不动这套"计划 -> 生效的键"的结构；
        :meth:`GlobalHotkeys.start` 只用首选。

        **实际生效的键记在 :attr:`global_keys`，界面会显示它** ——
        "按了没反应但看不出为什么"是最难查的一类问题。
        """
        wanted = [spec for spec in SHORTCUTS if spec.global_hotkey]
        if not wanted:
            return
        plans = []
        for spec in wanted:
            target = self._bindings.get(spec.action)
            if target is None or not callable(target):
                continue
            wanted_keys = [spec.keys]
            if spec.global_fallback:
                wanted_keys.append(spec.global_fallback)
            parsed = tuple(
                hotkey
                for hotkey in (parse_hotkey(spec.action, keys) for keys in wanted_keys)
                if hotkey is not None
            )
            if parsed:
                plans.append(HotkeyPlan(action=spec.action, candidates=parsed))

        service = GlobalHotkeys(plans, parent=self.parent)
        service.triggered.connect(self._on_global)
        if service.start():
            self._global = service
            #: ``action -> 实际生效的键写法``。界面显示它，而不是显示"我们想要的键"。
            self._global_keys = {h.action: h.keys for h in service.registered}
            self._global_ok = set(self._global_keys)
        else:
            # 现在挂不上的原因只剩两种：pynput 没装好，或者写法解析不出来。
            # **"候选键全被占用"已经不可能是原因了** —— 钩子不占键。
            log.info(
                "全局快捷键一条都没挂上（%s）—— 界面内快捷键不受影响",
                "pynput 不可用" if not is_supported() else "写法解析不出来",
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

    @property
    def global_keys(self) -> dict[str, str]:
        """``action -> **实际生效**的键写法``。

        首选键被别的软件占了就会是备选键。界面显示**这个**，而不是
        ``SHORTCUTS`` 里那个"我们想要的"键 —— 否则帮助里写着一个按不出来的键，
        用户只会以为程序坏了。
        """
        return dict(self._global_keys)

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

        **全局那几条显示"实际生效的键"**：首选被占用了就显示备选键，
        并在末尾说明原来那个被谁占了。用户按不出来时最需要的就是这条信息。
        """
        lines = []
        for spec in SHORTCUTS:
            active = spec.action in self._global_ok
            mark = "*" if active else " "
            # 实际生效的键（没挂全局就用声明的那个）
            shown = self._global_keys.get(spec.action, spec.keys) if active else spec.keys
            line = f" {mark}{shown:<12} {spec.label}"
            if active and shown != spec.keys:
                line += f"（{spec.keys} 已被别的软件占用）"
            lines.append(line)
        if self._global_ok:
            lines.append("")
            lines.append("  * = 界面没焦点时也能按（系统级，游戏在前台照样生效）")
        elif any(spec.global_hotkey for spec in SHORTCUTS):
            lines.append("")
            lines.append(
                "  系统级快捷键一条都没挂上（候选键被别的软件占用了）——"
                "所有键都要求界面有焦点"
            )
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
