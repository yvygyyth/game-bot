"""``python -m games poke`` —— 真的点一下，然后报告到底发生了什么。

## 为什么需要它

"日志里命中了，但没点击生效"有四个完全不同的原因，而它们的症状一模一样：

| 原因 | 症状 | 怎么区分 |
|---|---|---|
| 空跑（``--dry-run`` / 界面空跑） | 只识别、不下发 | 看有没有"空跑，未执行" |
| 环境拦掉了输入注入 | 后端说成功，鼠标没动 | 对比**点击前后鼠标位置** |
| 游戏不在前台 | 鼠标动了，游戏没收到 | 看前台窗口是谁 |
| 坐标偏了 | 点了，但点到别处 | 报出真正点到的屏幕位置 |

这条命令把这些一次性打出来：读鼠标位置 -> 点 -> 再读鼠标位置 ->
报前台窗口 -> 报它真正发出去的坐标。

```bash
uv run python -m games poke mingjiangsha/jingji 1365 585
```
"""

from __future__ import annotations

from typing import Any

from . import get_script

__all__ = ["cmd_poke", "register_poke"]


def cmd_poke(args: Any) -> int:
    """在指定坐标真点一下，并报告全过程。"""
    from gamebot.bootstrap import build_session_from_config

    spec = get_script(args.script)
    config = spec.build_config()
    if args.window:
        config.screen.window_title = args.window

    print(f"脚本: {spec.key}")
    print(f"窗口标题: {config.screen.window_title!r}")
    print(f"坐标空间: {config.screen.coordinate_space!r}")
    print(f"目标点: ({args.x}, {args.y})")
    print()

    session = build_session_from_config(config)
    try:
        if args.dry_run:
            # 空跑开关在 session 上（动作层要直接看得到），不在 config 上
            session.dry_run = True
            print("· 已开空跑：动作不会真的下发\n")
        _report_foreground(session, config)
        return _poke(session, args)
    finally:
        session.close()


def _report_foreground(session: Any, config: Any) -> None:
    """谁是前台窗口 —— 点击落到哪取决于它。"""
    try:
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        print(f"当前前台窗口: {title!r}")
        want = config.screen.window_title
        if want and want.lower() not in title.lower():
            print(
                f"  ⚠️ 游戏（{want!r}）**不在前台** —— 点击会落在上面那个窗口上，"
                "游戏收不到。先点一下游戏窗口再跑。"
            )
    except Exception as exc:
        print(f"（读前台窗口失败: {type(exc).__name__}: {exc}）")

    # **权限级别**：这一条最容易被忽略，而且失败是完全静默的。
    # SetCursorPos 照常把鼠标移过去，SendInput 返回成功，游戏什么都收不到 ——
    # 看起来像坐标错、像游戏不认合成输入，其实原因在这里。
    try:
        from gamebot.utils.integrity import check_integrity

        warning = check_integrity(config.screen.window_title)
        if warning:
            print(f"\n{warning}\n")
        else:
            print("权限检查: 本进程完整性级别不低于游戏 —— 输入送得进去（UIPI 不是障碍）")
    except Exception as exc:  # pragma: no cover - 读不到就不猜
        print(f"（权限检查跳过: {type(exc).__name__}）")
    print()


def _cursor() -> tuple[int, int] | None:
    """鼠标现在在哪（绝对屏幕坐标）。"""
    try:
        import win32api

        return win32api.GetCursorPos()
    except Exception:
        return None


def _poke(session: Any, args: Any) -> int:
    from gamebot.atomic import actions
    from gamebot.types import Point

    before = _cursor()
    print(f"点击前鼠标位置: {before}")

    point = Point(args.x, args.y)
    if args.space:
        session.input.coordinate_space = args.space
    result = actions.click_logic_point(session, point)

    print(f"动作层返回: status={result.status.value} message={result.message!r}")
    if result.meta.get("dry_run"):
        print("  ⚠️ **空跑** —— 动作没有真的下发（这就是'没点击'的原因）")

    after = _cursor()
    print(f"点击后鼠标位置: {after}")
    if before is not None and after is not None:
        if after == before:
            print(
                "  ⚠️ 鼠标**没动** —— 说明输入注入没生效（系统拦了 / 后端没跑起来）。\n"
                "     再拿这个点算一遍它应该到哪: 见 `games where` 的输出。"
            )
        else:
            print("  ✓ 鼠标动了 —— 至少『移动』这条链路是通的")

    # 它真正发出去的屏幕坐标（复刻后端那两层换算）
    provider = getattr(session.input, "_offset_provider", None)
    ox, oy = (0, 0)
    if provider is not None:
        try:
            region = provider()
            ox, oy = int(region.x), int(region.y)
        except Exception:
            pass
    if session.input.coordinate_space == "screen":
        source = Point(args.x - ox, args.y - oy)
    else:
        source = point
    print(f"它真正发出去的屏幕坐标: ({source.x + ox}, {source.y + oy})")
    print(f"捕获区原点: ({ox}, {oy})")
    return 0


def register_poke(sub: Any) -> None:
    """把 ``poke`` 子命令挂上。"""
    parser = sub.add_parser(
        "poke",
        help="真点一下并报告全过程（鼠标有没有动、前台窗口是谁、发出去的坐标）",
        description="诊断「点了没反应」：一次读完鼠标位置 / 前台窗口 / 实际发出去的坐标",
    )
    parser.add_argument("script", help="脚本 key，如 mingjiangsha/jingji")
    parser.add_argument("x", type=int, help="横坐标（按配置的坐标空间）")
    parser.add_argument("y", type=int, help="纵坐标（按配置的坐标空间）")
    parser.add_argument("--space", choices=("source", "screen"), default="")
    parser.add_argument("--window", default="", help="覆盖窗口标题")
    parser.add_argument("--dry-run", action="store_true", help="只走一遍不下发")
    parser.set_defaults(func=cmd_poke)
