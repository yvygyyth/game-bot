"""业务层命令行。

    python -m games list                  列出所有脚本
    python -m games describe <脚本>       打印状态树 + 流程图（不连游戏）
    python -m games check <脚本>          校验定义 + 检查模板文件是否齐全
    python -m games run <脚本>            **真的跑起来**（会操作游戏！）

除 ``run`` 外都不需要游戏在运行 —— 它们只做静态检查。
写脚本时最花时间的就是"图还没截、流程还没跑"，先靠它们把能查的错查掉。

## ``run`` 的顺序建议

1. ``python -m games check <脚本>`` —— 先确认定义和模板都没问题
2. ``python -m games run <脚本> --dry-run`` —— 空跑：只识别、只决策，不碰键鼠
3. ``python -m games run <脚本>`` —— 真跑
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

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
            print(f"  {spec.key:<{width}}  {spec.title}")
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
        print(f"没有节点认领的状态（不会出现在定位结果里）: {', '.join(unclaimed)}")
    else:
        print("每个状态都有节点认领（分类节点和叠加层不算 —— 它们不需要节点）")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """校验定义 + 检查模板文件。**这是写脚本时最该反复跑的一条。**"""
    spec = get_script(args.script)
    config = spec.build_config()
    scenario = spec.build_scenario()

    scenario.validate()
    print(f"✓ 定义校验通过: {spec.key}（{spec.title}）")
    print(
        f"  {len(scenario.tree)} 个状态 / {len(scenario.graph)} 个节点 / "
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

    # **不再检查"模板齐不齐"** —— 那要靠"哪一步用哪张图"的声明，
    # 而步骤现在是普通函数、没有那个属性。缺图的报错由识图本身给出
    # （带模板路径），重复出现在日志里同样看得见。
    return 0


def _parse_params(items: list[str]) -> tuple[dict[str, Any], list[str]]:
    """把 ``["rounds=5", "target=battle"]`` 解析成字典。

    值**尽量转成数字/布尔**：``--param rounds=5`` 传下去的应该是 ``int``，
    否则步骤里拿到的是字符串 ``"5"``，``range(rounds)`` 会直接炸 ——
    而那种错报在步骤里，跟命令行看不出关系。

    转换失败就当字符串（不报错）：值本来就可能长得像数字但不是，比如
    ``--param label=1号队``。
    """
    values: dict[str, Any] = {}
    bad: list[str] = []
    for item in items:
        name, sep, raw = item.partition("=")
        if not sep or not name.strip():
            bad.append(item)
            continue
        values[name.strip()] = _coerce_param(raw.strip())
    return values, bad


def _coerce_param(raw: str) -> Any:
    """``"5"`` -> 5，``"1.5"`` -> 1.5，``"true"`` -> True，其余原样。"""
    lowered = raw.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def cmd_run(args: argparse.Namespace) -> int:
    """**真的跑起来**：装配 -> 跑流程 -> 打报告。

    和 ``gamebot run`` 的区别：那个跑的是 ``config/app.yaml`` 里那个"文档级"
    示例流程；这个跑**业务层脚本**（``games/<游戏>/<功能>`` 的 ``build_config``
    + ``build_scenario``）—— 也就是真正认识某个游戏的那份定义。

    跑完一定要看报告里的三样东西：

    * ``stop_reason``：为什么停的（``max_ticks`` 是"跑到预算了"，正常；
      ``unknown`` 是"长时间认不出来"，多半是没站在预期的界面上）；
    * ``recoveries``：每次**重定位**。正常情况下每次点击换屏都会有一条 ——
      重点不是"有没有"，而是 ``to_node`` 是不是你预期的那个节点；
    * ``steps`` 里的失败项：哪一步没成、重试了几次。journal 文件里有逐条记录。
    """
    from gamebot.bootstrap import build_context, build_engine
    from gamebot.exceptions import ConfigError
    from gamebot.execution.journal import JsonlJournal, NullJournal
    from gamebot.flow.engine import StopReason
    from gamebot.utils.logging import setup_logging

    spec = get_script(args.script)
    given, bad = _parse_params(args.param)
    if bad:
        print(f"✗ --param 格式应该是 名字=值，这几条没看懂: {', '.join(bad)}", file=sys.stderr)
        return 2

    # 运行参数走**和界面同一个入口**：``FORM.fill()``。
    #
    # 界面那边是"表单值 → fill()"，这里是"--param → fill()"，两条路共用同一份
    # 声明做校验/转换。各写一份的话迟早出现"界面拦得住的、命令行拦不住"
    # （或者反过来），而那种不一致查起来很难 —— 用户会以为是自己参数写错了。
    #
    # 顺带把**声明的默认值**也补齐：命令行只给一两个参数时，步骤读其它参数
    # 仍然拿得到值，不必再写一遍默认值。
    try:
        params = spec.form.fill(given)
    except ConfigError as exc:
        print(f"✗ 参数不对: {exc}", file=sys.stderr)
        return 2

    config = spec.build_config()
    if args.window:
        config.screen.window_title = args.window
    if args.dry_run:
        config.dry_run = True

    scenario = spec.build_scenario()
    if args.max_runtime is not None:
        scenario.options.max_runtime = args.max_runtime
    if args.max_ticks is not None:
        scenario.options.max_ticks = args.max_ticks
    if args.node and scenario.graph.node(args.node) is None:
        print(f"✗ 没有这个节点: {args.node!r}", file=sys.stderr)
        return 2

    # 装配期就把能查的错查掉：配置 + 定义。
    scenario.validate()
    config.paths.ensure()

    setup_logging(config.logging.level)

    journal: Any = NullJournal()
    if not args.no_journal:
        journal = JsonlJournal(config.paths.resolve(config.paths.journals) / f"{spec.slug}.jsonl")

    print(f"跑 {spec.key}（{spec.title}）")
    print(f"  窗口   {config.screen.window_title!r} @ {config.screen.source_size or '自动探测'}")
    print(f"  起点   {args.node or scenario.graph.initial}")
    print(f"  模式   {'空跑（只识别，不操作）' if config.dry_run else '真跑（会操作游戏）'}")
    runtime = scenario.options.max_runtime or "不限"
    ticks = scenario.options.max_ticks or "不限"
    print(f"  预算   {runtime}s / {ticks} 轮")
    if params:
        shown = "  ".join(f"{k}={v}" for k, v in params.items())
        print(f"  参数   {shown}")
    if config.dry_run:
        print("  （空跑时动作步骤不真的下发，但仍然走完整的决策与记账）")
    print()

    ctx = None
    try:
        ctx = build_context(
            config,
            scenario=scenario,
            journal=journal,
            scenario_options=scenario.options,
            params=params,
        )
        engine = build_engine(config, ctx, scenario)
        report = engine.run()
    except KeyboardInterrupt:
        print("\n… 被 Ctrl+C 中断")
        return 130
    finally:
        if ctx is not None:
            ctx.close()
        journal.close()

    print()
    print(report.summary())
    if report.errors:
        print(f"✗ {len(report.errors)} 条错误:")
        for message in report.errors[:5]:
            print(f"    - {message}")

    recoveries = [r for r in report.recoveries if r.to_node]
    if recoveries:
        print(f"· 重定位 {len(recoveries)} 次（画面变了、游标下一轮才跟上，属正常）:")
        for record in recoveries[:5]:
            print(f"    {record.expected} -> {record.actual}  =>  {record.to_node}")
        if len(recoveries) > 5:
            print(f"    …… 还有 {len(recoveries) - 5} 次")

    failed = report.failed_steps
    if failed:
        print(f"✗ {len(failed)} 个步骤失败:")
        for outcome in failed[:5]:
            print(f"    {outcome.step}: {outcome.message}")

    if report.stop_reason is StopReason.UNKNOWN:
        print("\n提示: 长时间认不出状态 —— 游戏现在停在脚本认识的那个界面上吗？")
        print("      窗口标题/分辨率对不对，用 `python -m games check` 看一下。")

    # 退出码要能反映"有没有真的做事"。
    # 一个步骤都没执行、而且从头到尾都是 unknown —— 那基本就是
    # "窗口标题不对 / 游戏没开 / 没站在预期界面上"，必须算失败。
    # 否则 CI 和调用方会把一次"什么都没干"当成成功（`max_ticks` 本身是正常停止原因）。
    did_nothing = report.step_count == 0 and report.initial_page == "unknown"
    if report.ok and did_nothing:
        print("\n⚠ 一轮都没做事（0 个步骤）—— 多半是没抓到画面或没认出状态：")
        print(f"    初始状态 {report.initial_page} / 最终状态 {report.final_page}")
        print("  先确认窗口标题和分辨率（`python -m games check <脚本>`），")
        print("  再确认游戏确实停在脚本认识的那个界面上。")
        return 1

    return 0 if report.ok else 1


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
        ("describe", "打印状态树 + 流程图"),
        ("check", "校验定义并检查模板文件"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("script", help="脚本 key，如 mingjiangsha/jingji")

    p_run = sub.add_parser("run", help="真的跑起来（会操作游戏）")
    p_run.add_argument("script", help="脚本 key，如 mingjiangsha/jingji")
    p_run.add_argument("--dry-run", action="store_true", help="空跑：只识别不操作")
    p_run.add_argument("--max-runtime", type=float, default=None, help="总时长上限（秒）")
    p_run.add_argument("--max-ticks", type=int, default=None, help="最大轮数")
    p_run.add_argument("--node", default="", help="从哪个节点开始（调试用，不解除状态校验）")
    p_run.add_argument("--window", default="", help="覆盖窗口标题")
    p_run.add_argument("--no-journal", action="store_true", help="不写 journal 文件")
    p_run.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="名字=值",
        help=(
            "传给脚本的运行参数（入参）。可重复：--param rounds=5 --param dry=1。"
            "步骤用 ctx.param('rounds', 默认值) 读；值会尽量转成 int/float/true/false"
        ),
    )

    return parser


_HANDLERS = {
    "list": cmd_list,
    "describe": cmd_describe,
    "check": cmd_check,
    "run": cmd_run,
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
