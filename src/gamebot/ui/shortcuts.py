"""快捷键表 —— **一份定义，三处使用**。

## 为什么要单独一个文件

快捷键最容易出的问题不是"没绑上"，而是**说的和做的不一致**：
tooltip 里写着 F5，代码里绑的是 F6；帮助里写着 Esc 停止，实际绑在 F8。
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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtGui import QKeySequence, QShortcut

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

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
#: * ``F8`` 只抓一张 —— 调试时按得最多的就是它，所以给它一个单键；
#: * ``Ctrl+1/2/3`` 切左边三页；``F1`` 出帮助。
SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("run", "F5", "开始运行", button="start"),
    Shortcut("stop", "Esc", "停止（毫秒级）", button="stop"),
    Shortcut("grab", "F8", "抓一张：截一帧并画出识别到的框", button="grab"),
    Shortcut("check", "F6", "检查定义与模板文件", button="check"),
    Shortcut("selftest", "Shift+F6", "跑脚本自带的自检", button="selftest"),
    Shortcut("detect", "F7", "重新检测可见软件窗口", button="detect"),
    Shortcut("page_diagram", "Ctrl+1", "切到「状态 / 流程」"),
    Shortcut("page_recognition", "Ctrl+2", "切到「识图日志」"),
    Shortcut("page_check", "Ctrl+3", "切到「检查输出」"),
    Shortcut("help", "F1", "显示这份快捷键说明"),
)


class Keymap:
    """按 :data:`SHORTCUTS` 把动作绑到键上，并给 UI 提供提示文字。

    ``bindings`` 里给的每个动作都要有对应的可调用对象；缺了的会被跳过
    （而不是抛异常）—— 快捷键少一个不影响界面能用。
    """

    def __init__(self, parent: QWidget, bindings: dict[str, object]) -> None:
        self.parent = parent
        self._shortcuts: list[QShortcut] = []
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

    def __len__(self) -> int:
        return len(self._shortcuts)

    def hint_for(self, action: str) -> str:
        """某个动作的 ``（F5）`` 后缀；没有就返回空串。"""
        spec = _find(action)
        return spec.hint if spec else ""

    def help_lines(self) -> list[str]:
        """给帮助对话框用的清单（不带按钮对应关系，只有键和说明）。"""
        return [f"  {spec.keys:<12} {spec.label}" for spec in SHORTCUTS]

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
