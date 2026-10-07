"""命令行入口。

子命令（都是"装配期能独立验证"的动作，先跑这些再跑真流程）::

    gamebot info      [--config PATH]              打印本次生效的完整配置
    gamebot check     [--config PATH]              校验配置 + 流程 + 模板文件是否存在
    gamebot windows   [--keyword K]                列出可见窗口（找 window_title 用）
    gamebot capture   [--config PATH] [--out F]    截一张图存盘（验证坐标和后端）
    gamebot grab      --region x,y,w,h [--out F]   只截一个区域
    gamebot run       [--config PATH] [--dry-run]  跑流程
    gamebot ui        [--script K] [--snapshot F]  打开本地控制台界面

设计意图：**调试识图脚本 80% 的时间花在"确认我截到的是不是我以为的画面"上**，
所以 capture / grab / windows 三个命令要放在最显眼的位置，而不是让人写临时脚本。
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .exceptions import GameBotError
from .types import Region
from .utils.logging import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gamebot",
        description="传统识图游戏脚本框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"game-bot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default="config/app.yaml", help="配置文件路径")

    p_info = sub.add_parser("info", parents=[common], help="打印生效配置")
    p_info.add_argument("--json", action="store_true", help="以 JSON 输出")

    sub.add_parser("check", parents=[common], help="校验配置、流程与模板文件")

    p_win = sub.add_parser("windows", help="列出可见窗口")
    p_win.add_argument("-k", "--keyword", default="", help="标题关键字过滤")

    p_cap = sub.add_parser("capture", parents=[common], help="截一张全屏图")
    p_cap.add_argument("-o", "--out", default="logs/screenshots/manual.png", help="输出文件")

    p_grab = sub.add_parser("grab", parents=[common], help="截一个指定区域")
    p_grab.add_argument("--region", required=True, help="x,y,w,h")
    p_grab.add_argument("-o", "--out", default="logs/screenshots/region.png", help="输出文件")

    p_run = sub.add_parser("run", parents=[common], help="运行流程")
    p_run.add_argument("--dry-run", action="store_true", help="只识别不操作")
    p_run.add_argument("--max-runtime", type=float, default=None, help="总时长上限（秒）")
    p_run.add_argument("--max-ticks", type=int, default=None, help="最大轮数")
    p_run.add_argument("--window", default=None, help="覆盖窗口标题")
    p_run.add_argument("--no-journal", action="store_true", help="不写 journal 文件")

    p_ui = sub.add_parser("ui", parents=[common], help="打开本地控制台界面")
    p_ui.add_argument("--script", default=None, help="预选脚本 key，如 testgame")
    p_ui.add_argument(
        "--snapshot",
        default=None,
        help="不开窗口，渲染一张界面截图存到指定路径后退出（无头自检用）",
    )

    return parser


# --------------------------------------------------------------------------- #
# 子命令实现
# --------------------------------------------------------------------------- #
def cmd_info(args: argparse.Namespace) -> int:
    """打印本次生效的配置。**排查"配置文件到底有没有被读到"的第一手段。**"""
    import json

    from .config.loader import config_to_dict, load_config

    config = load_config(args.config)
    data = config_to_dict(config)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for section, values in data.items():
            if not isinstance(values, dict):
                print(f"{section}: {values}")
                continue
            print(f"[{section}]")
            for key, value in values.items():
                print(f"  {key} = {value}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """校验配置 + 脚本定义。CI 里跑这个能挡住大部分低级错误。

    **不再检查模板文件齐不齐** —— 那要靠哪一步用哪张图的声明，
    而步骤现在是普通函数、没有那个属性。缺图的报错由识图本身给出
    （带模板路径），重复出现在日志里同样看得见。
    """
    from .config.loader import load_config
    from .flow.loader import load_scenario

    config = load_config(args.config)
    scenario = load_scenario(config.paths.resolve(config.flow_file))
    scenario.validate()
    print(f"✓ 配置 OK: {args.config}")
    print(
        f"✓ 脚本 OK: {scenario.name} "
        f"({len(scenario.tree)} 状态 / {len(scenario.graph)} 节点 / "
        f"{len(scenario.graph.edges)} 边)"
    )

    # 未认领的状态**本该**是启动期错误（Scenario.validate 里由 validate_binding
    # 拦下），走到这里说明它被豁免了（分类节点 / 叠加层）—— 所以只是提示。
    unclaimed = scenario.unclaimed_pages()
    if unclaimed:
        print(f"· 以下状态没有节点认领（不会出现在定位结果里）: {', '.join(unclaimed)}")

    return 0


def cmd_windows(args: argparse.Namespace) -> int:
    """列出可见窗口。用来确定 ``screen.window_title`` 该填什么。"""
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
    """截一张全屏图存盘。"""
    from .bootstrap import build_session_from_config
    from .config.loader import load_config

    config = load_config(args.config)
    session = build_session_from_config(config)
    with session:
        frame = session.capture()
        result = frame.save(args.out)
    if not result.ok:
        print(f"✗ {result.message}")
        return 1
    print(f"✓ 已保存 {args.out}  尺寸={frame.size}  origin={frame.origin.to_tuple()}")
    return 0


def cmd_grab(args: argparse.Namespace) -> int:
    """截一个指定区域存盘。调 ROI 的时候反复用这个。"""
    from .bootstrap import build_session_from_config
    from .config.loader import load_config

    try:
        parts = tuple(int(v) for v in args.region.split(","))
        if len(parts) != 4:
            raise ValueError(f"要 4 个数，给了 {len(parts)} 个")
        region = Region(*parts)
    except Exception:
        print("✗ --region 格式应为 x,y,w,h，例如 100,50,80,30")
        return 2

    config = load_config(args.config)
    session = build_session_from_config(config)
    with session:
        frame = session.capture_region(region)
        result = frame.save(args.out)
    if not result.ok:
        print(f"✗ {result.message}")
        return 1
    print(f"✓ 已保存 {args.out}  尺寸={frame.size}  origin={frame.origin.to_tuple()}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """跑脚本。"""
    from .bootstrap import run_scenario

    overrides: dict[str, object] = {}
    if args.dry_run:
        overrides["dry_run"] = True
    if args.window is not None:
        overrides["screen.window_title"] = args.window

    report = run_scenario(args.config, overrides=overrides or None, log_journal=not args.no_journal)
    print(report.summary())
    if report.failed_steps:
        print(f"  失败步骤 {len(report.failed_steps)} 个:")
        for outcome in report.failed_steps[:10]:
            print(f"    - {outcome.step}: {outcome.message}")
    return 0 if report.ok else 1


def cmd_ui(args: argparse.Namespace) -> int:
    """打开本地控制台界面。"""
    from .ui import run_ui

    if args.snapshot:
        # 无头渲染：Qt 必须走离屏平台插件，否则没有显示器时构造窗口就退出
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return run_ui(
        script_key=args.script or "",
        snapshot=args.snapshot or "",
    )


_HANDLERS = {
    "info": cmd_info,
    "check": cmd_check,
    "windows": cmd_windows,
    "capture": cmd_capture,
    "grab": cmd_grab,
    "run": cmd_run,
    "ui": cmd_ui,
}


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    # ``ui`` 额外写一份日志文件。
    #
    # 理由：界面是**用 ``pythonw.exe`` 启动的**（无控制台版本）——那样双击才不会
    # 弹一个黑窗口，代价是 stdout 常常接不到东西（没有控制台，日志就丢了）。
    # 所以界面自己写文件，出问题时有地方可查；控制台那份照常保留。
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
