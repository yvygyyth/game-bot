"""命令行入口 —— **只有一件事：开界面**。

```bash
python -m gamebot                                   # 打开本地控制台
python -m gamebot --script mingjiangsha/jingji      # 预选脚本
python -m gamebot --snapshot out.png                # 不开窗，渲一张图就退（无头自检）
gamebot --version
```

## 为什么只剩这一条

写脚本需要的动作（选窗口、选脚本、检查、空跑、开跑、看识图日志）**全在界面里**：

* 选完脚本 = 做一次检查（定义 + 逐张对模板文件），结果进「检查输出」页；
* 「空跑（只识别，不操作）」是开始按钮旁边的勾选框；
* 识别过程、每次匹配的带框图、运行报告都在界面上。

命令行再留一套 ``list / check / run`` 就等于**两套入口、两份文档、两处要维护的
报错** —— 而实际只用界面。所以这里只保留启动。

> 需要无界面跑一轮（自动化、CI）时，公开入口是
> :func:`gamebot.bootstrap.bootstrap_from_spec`，十来行 Python 就够；
> `tests/test_bootstrap_integration.py` 就是那条路的样板。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .exceptions import GameBotError
from .utils.logging import get_logger, setup_logging

log = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gamebot",
        description="传统识图游戏脚本框架（启动本地控制台）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"game-bot {__version__}")
    parser.add_argument(
        "--script",
        default=None,
        help="预选脚本 key，如 mingjiangsha/jingji",
    )
    parser.add_argument(
        "--snapshot",
        default=None,
        help="不开窗口，渲染一张界面截图存到指定路径后退出（无头自检用）",
    )
    return parser


def cmd_ui(args: argparse.Namespace) -> int:
    from .ui import run_ui

    if args.snapshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return run_ui(
        script_key=args.script or "",
        snapshot=args.snapshot or "",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    log_file = Path("logs/ui.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    setup_logging("INFO", log_file=log_file)

    try:
        return cmd_ui(args)
    except GameBotError as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - 人工中断
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
