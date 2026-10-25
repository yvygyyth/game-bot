"""命令行入口。

业务脚本请用 ``python -m games …``。这里保留调试辅助与 UI：

    gamebot windows   [--keyword K]                列出可见窗口
    gamebot capture   [--window T] [--out F]       截一张图存盘
    gamebot grab      --region x,y,w,h [--out F]   只截一个区域
    gamebot ui        [--script K] [--snapshot F]  打开本地控制台界面
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .exceptions import GameBotError
from .types import Region
from .utils.logging import get_logger, setup_logging

log = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gamebot",
        description="传统识图游戏脚本框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"game-bot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_win = sub.add_parser("windows", help="列出可见窗口")
    p_win.add_argument("-k", "--keyword", default="", help="标题关键字过滤")

    p_cap = sub.add_parser("capture", help="截一张全屏/窗口图")
    p_cap.add_argument("--window", default="", help="窗口标题关键字（空=整屏）")
    p_cap.add_argument("-o", "--out", default="logs/screenshots/manual.png", help="输出文件")

    p_grab = sub.add_parser("grab", help="截一个指定区域")
    p_grab.add_argument("--window", default="", help="窗口标题关键字（空=整屏）")
    p_grab.add_argument("--region", required=True, help="x,y,w,h")
    p_grab.add_argument("-o", "--out", default="logs/screenshots/region.png", help="输出文件")

    p_ui = sub.add_parser("ui", help="打开本地控制台界面")
    p_ui.add_argument("--script", default=None, help="预选脚本 key，如 mingjiangsha/jingji")
    p_ui.add_argument(
        "--snapshot",
        default=None,
        help="不开窗口，渲染一张界面截图存到指定路径后退出（无头自检用）",
    )

    # 旧的 YAML 路径：明确指路到 games
    for name, help_text in (
        ("info", "已移除：请用 python -m games describe <脚本>"),
        ("check", "已移除：请用 python -m games check <脚本>"),
        ("run", "已移除：请用 python -m games run <脚本>"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("script", nargs="?", default="")
        p.add_argument("-c", "--config", default="", help=argparse.SUPPRESS)

    return parser


def _session(*, window: str = ""):
    from pathlib import Path

    from .atomic.session import build_session
    from .atomic.vision import UnavailableTextReader
    from .vision.opencv_matcher import OpenCvMatcher

    # capture/grab 不需要真实模板；给个空目录占位
    empty = Path("logs/_empty_templates")
    empty.mkdir(parents=True, exist_ok=True)
    matcher = OpenCvMatcher(templates_dir=empty, preload=False)
    kwargs: dict = {
        "matcher": matcher,
        "reader": UnavailableTextReader("capture/grab"),
        "client_area_only": True,
        "coordinate_space": "source",
        "logic_size": None,
    }
    if window:
        return build_session("windows", window_title=window, **kwargs)
    return build_session("windows", **kwargs)


def cmd_windows(args: argparse.Namespace) -> int:
    from .atomic.backends.windows import WindowsWindowBackend

    backend = WindowsWindowBackend()
    windows = backend.list_windows(args.keyword)
    if not windows:
        print("没有找到匹配的窗口")
        return 1
    for info in windows:
        print(f"{info.title}  @ {info.region.to_tuple()}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    session = _session(window=args.window)
    with session:
        frame = session.capture()
        result = frame.save(args.out)
    if not result.ok:
        print(f"✗ {result.message}")
        return 1
    print(f"✓ 已保存 {args.out}  尺寸={frame.size}  origin={frame.origin.to_tuple()}")
    return 0


def cmd_grab(args: argparse.Namespace) -> int:
    try:
        parts = tuple(int(v) for v in args.region.split(","))
        if len(parts) != 4:
            raise ValueError(f"要 4 个数，给了 {len(parts)} 个")
        region = Region(*parts)
    except Exception:
        print("✗ --region 格式应为 x,y,w,h，例如 100,50,80,30")
        return 2

    session = _session(window=args.window)
    with session:
        frame = session.capture_region(region)
        result = frame.save(args.out)
    if not result.ok:
        print(f"✗ {result.message}")
        return 1
    print(f"✓ 已保存 {args.out}  尺寸={frame.size}  origin={frame.origin.to_tuple()}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from .ui import run_ui

    if args.snapshot:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return run_ui(
        script_key=args.script or "",
        snapshot=args.snapshot or "",
    )


def cmd_moved(args: argparse.Namespace) -> int:
    print(
        f"✗ `{args.command}` 已迁到业务入口。请用：\n"
        f"    python -m games {args.command} <脚本>\n"
        f"例如：python -m games run mingjiangsha/jingji --dry-run",
        file=sys.stderr,
    )
    return 2


_HANDLERS = {
    "windows": cmd_windows,
    "capture": cmd_capture,
    "grab": cmd_grab,
    "ui": cmd_ui,
    "info": cmd_moved,
    "check": cmd_moved,
    "run": cmd_moved,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    log_file = None
    if args.command == "ui":
        from pathlib import Path

        log_file = Path("logs/ui.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)
    setup_logging("INFO", log_file=log_file)

    handler = _HANDLERS[args.command]
    try:
        return handler(args)
    except GameBotError as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except NotImplementedError as exc:
        print(f"… 该功能尚未实现: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:  # pragma: no cover
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
