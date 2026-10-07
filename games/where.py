"""``python -m games where`` —— 坐标校准。

## 它解决什么问题

脚本里写的坐标和"真正会点到的屏幕位置"之间差一个常量，而那个常量取决于
两件事：窗口**现在**在屏幕哪儿、以及你量坐标时用的是哪一套原点。

盲猜它很坑：症状是"整体偏一个固定量"，看起来像识别不准，其实是坐标差。
所以给一条命令把账算清楚：

```bash
uv run python -m games where mingjiangsha/jingji 1365 585
```

输出会写清：这个点在你写的坐标空间里是多少、在捕获区坐标里是多少、
**真正会点到屏幕的哪一点**。

## 怎么用它校准

1. 拿一个你在**自己的取点工具**里量到的点（比如竞技卡中心）；
2. 跑这条命令，看它报的"真正会点到"的屏幕坐标；
3. 用另一个工具（或肉眼对着屏幕）看那个位置**实际是哪**；
4. 差多少，就是需要修的偏移量：
   * 整体差一个常量（比如固定偏上 31）-> 改 ``screen.coordinate_space``
     或检查窗口位置；
   * 反过来，如果你量的是**屏幕绝对坐标**、却把 ``coordinate_space``
     留成 ``source``（默认），就会**多偏一个窗口原点** —— 这正是最常见的错。

## 为什么不做成"自动校准"

自动校准需要"我知道屏幕上某个东西在哪"—— 而那正是要测的量，循环了。
人工比一次是这件事里最便宜的一步。
"""

from __future__ import annotations

from typing import Any

from . import get_script

__all__ = ["cmd_where", "register_where"]


def cmd_where(args: Any) -> int:
    """打印一个坐标在各套坐标系里的值。"""
    from gamebot.bootstrap import build_session_from_config

    spec = get_script(args.script)
    config = spec.build_config()
    if args.window:
        config.screen.window_title = args.window
    if args.space:
        config.screen.coordinate_space = args.space

    x, y = args.x, args.y
    space = config.screen.coordinate_space
    print(f"脚本: {spec.key}")
    print(f"窗口标题: {config.screen.window_title!r}")
    print(f"你写的坐标空间(screen.coordinate_space): {space!r}")
    print(f"你给的点: ({x}, {y})")
    print()

    try:
        session = build_session_from_config(config)
    except Exception as exc:
        print(f"✗ 装不起来 Session: {type(exc).__name__}: {exc}")
        return 1

    try:
        return _report(session, x, y, space)
    finally:
        session.close()


def _report(session: Any, x: int, y: int, space: str) -> int:
    from gamebot.types import Point

    # 捕获区（客户区）在屏幕上的位置 —— 从输入后端拿，和点击时用的是同一个来源
    provider = getattr(session.input, "_offset_provider", None)
    origin: tuple[int, int] | None = None
    if provider is not None:
        try:
            region = provider()
            origin = (int(region.x), int(region.y))
        except Exception as exc:
            print(f"· 取捕获区位置失败（{type(exc).__name__}）—— 窗口没开？后面按 (0,0) 算")
    if origin is None:
        origin = (0, 0)

    ox, oy = origin
    print(f"捕获区（客户区）在屏幕上的原点: ({ox}, {oy})")
    screen_size = session.mapper.source_width, session.mapper.source_height
    print(f"捕获区尺寸（= 帧的尺寸）: {screen_size[0]}x{screen_size[1]}")
    print(f"逻辑->源 缩放: {session.mapper.scale_x:.4f} x {session.mapper.scale_y:.4f}"
          f"{'（恒等）' if session.mapper.is_identity else ''}")
    print()

    point = Point(x, y)
    if space == "screen":
        source = Point(x - ox, y - oy)
        print("· 你写的是**屏幕绝对坐标**")
        print(f"    -> 减去捕获区原点 -> 源坐标 ({source.x}, {source.y})")
    else:
        source = point
        print("· 你写的是**捕获区相对坐标**（source）")
        print(f"    -> 捕获区坐标 ({source.x}, {source.y})")
    print(f"    -> 真正会点到的**屏幕位置**: ({source.x + ox}, {source.y + oy})")
    print()

    inside = 0 <= source.x < screen_size[0] and 0 <= source.y < screen_size[1]
    print(f"· 这个源坐标落在捕获区里吗: {'是' if inside else '✗ 否（点到窗口外面去了）'}")
    if not inside and space == "source":
        print(
            "   提示：偏出去多半说明**你把屏幕坐标当成 source 写了**。"
            f" 试试 --space screen（那样会减掉 ({ox}, {oy})）。"
        )
    return 0


def register_where(sub: Any) -> None:
    """把 ``where`` 子命令挂到解析器上（``__main__`` 调它）。"""
    parser = sub.add_parser(
        "where",
        help="坐标校准：某个点在各套坐标系里分别是多少、真正会点到屏幕哪",
        description=(
            "坐标校准。示例：uv run python -m games where mingjiangsha/jingji 1365 585"
        ),
    )
    parser.add_argument("script", help="脚本 key，如 mingjiangsha/jingji")
    parser.add_argument("x", type=int, help="横坐标（按你写的坐标空间）")
    parser.add_argument("y", type=int, help="纵坐标（按你写的坐标空间）")
    parser.add_argument(
        "--space",
        choices=("source", "screen"),
        default="",
        help="覆盖配置里的 coordinate_space，用来对比两种解释",
    )
    parser.add_argument("--window", default="", help="覆盖窗口标题")
    parser.set_defaults(func=cmd_where)
