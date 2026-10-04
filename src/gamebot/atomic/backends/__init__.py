"""平台后端实现。

三个后端目录式并列，互不引用：

* ``windows`` —— mss 截图 + pydirectinput / pyautogui 输入（PC 游戏、PC 客户端）
* ``android`` —— adb screencap 截图 + ``adb shell input`` 输入（手游模拟器 / 真机）
* ``fake``    —— 内存假后端，给单元测试和流程空跑用

共用协议在 ``base.py``。上层的选择逻辑在 ``..session.build_session``。

**关于依赖**：本目录下所有模块都不在顶层 import 第三方库，
而是延迟到 ``build_*`` 里导入 —— 这样 ``import gamebot`` 永远不会因为
"没装 pywin32 / adbutils" 而失败。
"""

from __future__ import annotations

from .base import BackendBundle, InputBackend, ScreenBackend, WindowBackend, WindowInfo

__all__ = [
    "BackendBundle",
    "InputBackend",
    "ScreenBackend",
    "WindowBackend",
    "WindowInfo",
]
