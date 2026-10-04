"""业务层命令行。

    python -m games list                  列出所有脚本
    python -m games describe <脚本>       打印页面树 + 流程图（不连游戏）
    python -m games check <脚本>          校验定义 + 检查模板文件是否齐全
    python -m games setup <脚本>          生成 / 下载这个脚本需要的资源
    python -m games selftest <脚本>       跑脚本自带的自检

前四条**都不需要游戏在运行** —— 它们只做静态检查。
写脚本时最花时间的就是"图还没截、流程还没跑"，先靠它们把能查的错查掉。

（真正的 ``run`` 要等 ``PageTree.locate()`` 和 ``FlowEngine.tick()`` 实现完，
那时候会加一个 ``python -m games run <脚本>``。）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 先把自己所在的项目根加进 sys.path，这样 `python -m games` 不需要先安装框架
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gamebot.exceptions import GameBotError  # noqa: E402
from games import get_script, list_scripts  # noqa: E402
from games._spec import discovery_errors  # noqa: E402


def cmd_list(args: argparse.Namespace) -> int:
    """列出所有脚本 + 发现过程中的错误。"""
    scripts = list_scripts(refresh=args.refresh)
    if args.games:
        for game in sorted({s.game for s in scripts}):
            print(game)

    if not scripts:
        print("（还没有任何脚本 —— 见 games/README.md 的约定）")
    else:
        width = max(len(s.key) for s in scripts)
        for spec in scripts:
            marks = []
            if spec.selftest is not None:
                marks.append("有自检")
            if spec.prepare is not None:
                marks.append("有资源脚本")
            suffix = f"  [{' / '.join(marks)}]" if marks else ""
            print(f"  {spec.key:<{width}}  {spec.title}{suffix}")
            if spec.description:
                print(f"  {'':<{width}}  {spec.description}")

    errors = discovery_errors()
    if errors:
        print(f"\n⚠️  {len(errors)} 个脚本没能加载:")
        for key, message in errors:
            print(f"    {key}: {message}")
        return 1
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    """不连游戏，打印这个脚本长什么样。"""
    spec = get_script(args.script)
    scenario = spec.build_scenario()
    print(f"脚本 {spec.key} —— {spec.title}")
    if spec.description:
        print(spec.description)
    print()
    print(scenario.tree.describe())
    print()
    print(scenario.graph.describe())

    unclaimed = scenario.unclaimed_pages()
    print()
    if unclaimed:
        print(f"没有节点认领的页面（只观察不动作）: {', '.join(unclaimed)}")
    else:
        print("每个页面都有节点认领（叠加层和终态页面不算 —— 它们不需要节点）")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """校验定义 + 检查模板文件。**这是写脚本时最该反复跑的一条。**"""
    spec = get_script(args.script)
    config = spec.build_config()
    scenario = spec.build_scenario()

    scenario.validate()
    print(f"✓ 定义校验通过: {spec.key}（{spec.title}）")
    print(
        f"  {len(scenario.tree)} 个页面 / {len(scenario.graph)} 个节点 / "
        f"{len(scenario.graph.edges)} 条边"
    )

    problems = config.validate()
    if problems:
        print("✗ 配置有问题:")
        for problem in problems:
            print(f"    - {problem}")
        return 1
    print(f"✓ 配置校验通过: 窗口={config.screen.window_title!r} @ {config.screen.source_size}")

    roots = config.template_roots()
    print("  模板根（按搜索优先级）:")
    for index, root in enumerate(roots):
        exists = "存在" if root.is_dir() else "目录不存在"
        label = root.relative_to(_ROOT) if root.is_relative_to(_ROOT) else root
        print(f"    {index + 1}. {label}（{exists}）")

    from gamebot.bootstrap import check_templates

    missing = check_templates(config, scenario)
    if missing and spec.auto_prepare and spec.prepare is not None:
        # 脚本自己声明了"可以帮我准备资源"（AUTO_PREPARE = True）。
        # 真实游戏不会开这个 —— 下载几百张图不该藏在 check 里。
        print(f"\n· 缺 {len(missing)} 个资源，脚本声明了 AUTO_PREPARE，正在准备……")
        written = spec.prepare()
        print(f"  已生成 {written} 个文件")
        missing = check_templates(config, scenario)

    if missing:
        print(f"\n✗ 缺 {len(missing)} 个模板文件（截好图放到上面的模板根里）:")
        for name in missing:
            print(f"    - {name}")
        if spec.prepare is not None and not spec.auto_prepare:
            print(f"\n提示: 这个脚本提供了 prepare()，可以跑 python -m games setup {spec.key}")
        return 1

    print("\n✓ 模板文件齐全")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """生成 / 下载脚本需要的资源（图片等）。幂等。"""
    spec = get_script(args.script)
    if spec.prepare is None:
        print(f"· {spec.key} 没有 prepare()，不需要准备资源")
        return 0
    written = spec.prepare(force=args.force) if args.force else spec.prepare()
    print(f"✓ {spec.key}: 生成/更新了 {written} 个文件")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """跑脚本自带的自检（检查的是"这份定义本身对不对"）。"""
    spec = get_script(args.script)
    if spec.selftest is None:
        print(f"· {spec.key} 没有 selftest()")
        return 0

    # 自检通常要读模板文件，先确保资源在
    if spec.prepare is not None:
        spec.prepare()

    print(f"自检 {spec.key}（{spec.title}）")
    failures = spec.selftest()
    print()
    if failures:
        print(f"✗ {len(failures)} 项失败")
        return 1
    print("✓ 全部通过")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m games",
        description="业务层：具体游戏的脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出所有脚本")
    p_list.add_argument("--games", action="store_true", help="只列游戏名")
    p_list.add_argument("--refresh", action="store_true", help="忽略缓存重新发现")

    for name, help_text in (
        ("describe", "打印页面树 + 流程图"),
        ("check", "校验定义并检查模板文件"),
        ("selftest", "跑脚本自带的自检"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("script", help="脚本 key，如 testgame")

    p_setup = sub.add_parser("setup", help="生成 / 下载脚本需要的资源")
    p_setup.add_argument("script", help="脚本 key，如 testgame")
    p_setup.add_argument("--force", action="store_true", help="已存在的也重新生成")

    return parser


_HANDLERS = {
    "list": cmd_list,
    "describe": cmd_describe,
    "check": cmd_check,
    "setup": cmd_setup,
    "selftest": cmd_selftest,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _HANDLERS[args.command](args)
    except KeyError as exc:
        print(f"✗ {exc.args[0]}", file=sys.stderr)
        return 2
    except GameBotError as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except NotImplementedError as exc:
        print(f"… 该功能尚未实现: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
