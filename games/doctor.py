"""``python -m games doctor`` —— 跑脚本前的环境自检。

## 为什么要它

这个项目里有一类失败是**彻底静默**的：程序退出码 0、日志里识别命中、
动作层返回 `success`，**只有游戏没反应**。已经踩过的两个：

1. **权限级别不够**（UIPI）。这台机器上游戏是**提权运行**的，而 Windows
   规定"发送方进程的完整性级别必须 >= 目标窗口的级别"。级别不够时：

   * 鼠标指针**会**移到正确位置（`SetCursorPos` 不受 UIPI 限制）；
   * 点击**不生效**（`SendInput` 返回成功，消息被丢掉）；
   * 失焦后全局快捷键也收不到。

   实测：普通终端（Low）/ 普通双击（Medium）都不行，
   **管理员（High）才可以**。

2. **窗口不在前台**。点击会落到别的窗口上 —— 和坐标写错长得一模一样。

`doctor` 把这两件事（还有几件别的）在**开跑之前**问一遍，
让人不用去猜"为什么点了没反应"。

## 用法

```bash
uv run python -m games doctor mingjiangsha/jingji
```
"""

from __future__ import annotations

from typing import Any

from . import get_script

__all__ = ["cmd_doctor", "register_doctor"]


def _section(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(0, 60 - len(title)))


def cmd_doctor(args: Any) -> int:
    """把"跑之前该知道的环境事实"一次打完。"""
    from gamebot.bootstrap import build_session_from_config
    from gamebot.utils.integrity import check_integrity, level_of_pid, level_of_window

    spec = get_script(args.script)
    config = spec.build_config()
    if args.window:
        config.screen.window_title = args.window

    print(f"脚本: {spec.key} —— {spec.title}")
    print(f"目标窗口: {config.screen.window_title!r}")

    problems: list[str] = []

    # ---- 1. 定义能不能装起来 ----
    _section("定义")
    try:
        scenario = spec.build_scenario()
        scenario.validate()
        print(f"  ✓ 状态 {len(scenario.tree)} 个 / 节点 {len(scenario.graph)} 个")
    except Exception as exc:
        print(f"  ✗ 装不起来: {type(exc).__name__}: {exc}")
        problems.append("定义装不起来")
        return _report(problems)

    # ---- 2. 权限级别（**最要紧的一条**）----
    _section("权限（UIPI）")
    import os

    mine = level_of_pid(os.getpid())
    print(f"  本进程: {mine.name if mine else '读不到'}")

    title = config.screen.window_title
    if title:
        import win32gui

        hwnd = win32gui.FindWindow(None, title) or 0
        if not hwnd:
            matches = [
                h
                for h in _visible_windows()
                if title.lower() in (win32gui.GetWindowText(h) or "").lower()
            ]
            hwnd = matches[0] if matches else 0
        if hwnd:
            theirs = level_of_window(hwnd)
            print(f"  目标窗口: {theirs.name if theirs else '读不到'}")
            print("    ⚠️ 这个数字**可能偏低**：低完整性进程读不到提权进程的真实")
            print("       级别（Windows 会隐藏它）。所以『读出来相等』也不代表真的够。")
            print("       判据看下面那条结论 —— 拿不准就直接以管理员身份跑。")
        else:
            print("  目标窗口: **没找到**（游戏没开？标题写错了？）")
            problems.append(f"找不到窗口 {title!r}")
            theirs = None
        warning = check_integrity(title) if hwnd else None
        if warning:
            problems.append("权限级别不够，输入会被静默丢掉")
            print()
            for line in warning.splitlines():
                print(f"  {line}")
        elif theirs is not None:
            print("  ✓ 没发现级别不足（但见上面那条提醒）")
    else:
        print("  没配窗口标题 —— 抓整屏，不做这个判断")

    # ---- 3. 窗口在不在前台 ----
    _section("前台窗口")
    try:
        import win32gui

        fg = win32gui.GetForegroundWindow()
        fg_title = win32gui.GetWindowText(fg)
        print(f"  当前前台: {fg_title!r}")
        if title and title.lower() not in fg_title.lower():
            problems.append("游戏不在前台 —— 点击会落到别的窗口上")
            print("  ⚠️ 不在前台：点击会落到上面那个窗口，游戏收不到。")
        elif title:
            print("  ✓ 就是目标窗口")
    except Exception as exc:
        print(f"  （读前台窗口失败: {type(exc).__name__}）")

    # ---- 4. 识图/模板能不能真的读到 ----
    _section("模板")
    try:
        session = build_session_from_config(config)
    except Exception as exc:
        print(f"  ✗ 装不起 Session: {type(exc).__name__}: {exc}")
        problems.append("装不起 Session")
        return _report(problems)
    try:
        from pathlib import Path

        roots = list(config.template_roots())

        def resolves(name: str) -> bool:
            """这个模板名在某个模板根下真的存在吗。

            规则和 ``OpenCvMatcher`` 一致：**相对路径按模板名在各根下找**。
            所以这里也逐根找一遍 —— 用 matcher 的私有接口会把
            "能不能找到"这件事绑到某个具体实现上。
            """
            candidate = Path(name)
            if candidate.is_absolute():
                return candidate.is_file()
            return any((root / name).is_file() for root in roots)

        missing: list[str] = []
        for page in scenario.tree.walk():
            if page.is_group:
                continue
            for query in getattr(page, "queries", ()):
                name = getattr(query, "template", None)
                if name and not resolves(name):
                    missing.append(f"{page.id} -> {name}")
        if missing:
            print(f"  ✗ 这些模板读不到（{len(missing)} 个）:")
            for item in missing[:10]:
                print(f"      {item}")
            if len(missing) > 10:
                print(f"      …还有 {len(missing) - 10} 个")
            problems.append(f"{len(missing)} 个模板读不到")
        else:
            print(f"  ✓ 状态树引用的模板都能读到（在 {len(roots)} 个模板根里找的）")

        # 抓一张真实的帧，确认抓屏这条路是通的
        frame = session.capture()
        arr = frame.to_numpy()
        print(f"  ✓ 抓屏正常: {arr.shape[1]}x{arr.shape[0]}")
        found = scenario.tree.locate(frame)
        if found.value is not None:
            print(f"  当前识别结果: {found.value.id!r}")
            if found.value.id == "unknown":
                print("    （认不出来 —— 你现在没站在脚本认得的界面上，正常）")
    finally:
        session.close()

    return _report(problems)


def _report(problems: list[str]) -> int:
    print()
    print("=" * 66)
    if problems:
        print(f"✗ 有 {len(problems)} 个问题会让脚本'看起来在跑、其实没效果':")
        for item in problems:
            print(f"    * {item}")
        return 1
    print("✓ 没发现问题 —— 可以开跑了")
    return 0


def _visible_windows() -> list[int]:
    import win32gui

    found: list[int] = []

    def callback(hwnd: int, _extra: object) -> bool:
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            found.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return found


def register_doctor(sub: Any) -> None:
    """把 ``doctor`` 子命令挂上。"""
    parser = sub.add_parser(
        "doctor",
        help="跑脚本前的环境自检（权限级别 / 前台窗口 / 模板 / 抓屏）",
        description=(
            "跑之前先自检。这个项目有一类失败是完全静默的："
            "程序退出码 0、识别命中、动作返回成功，只有游戏没反应。"
            "最常见的原因是权限级别不够（UIPI）和窗口不在前台。\n\n"
            "示例：uv run python -m games doctor mingjiangsha/jingji"
        ),
    )
    parser.add_argument("script", help="脚本 key，如 mingjiangsha/jingji")
    parser.add_argument("--window", default="", help="覆盖窗口标题")
    parser.set_defaults(func=cmd_doctor)
