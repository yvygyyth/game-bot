"""装配 —— 把配置变成一堆互相接好的对象，然后开跑。

这一步的产出是 ``(RunContext, FlowEngine)``。所有 ``import`` 的重活都发生在这里，
所以这是唯一可能出现"缺依赖"的地方，也是唯一需要判断平台的地方。

**装配期的职责**（错了就在这里炸，别拖到运行期）：

1. 读配置、建目录、配日志；
2. 检查模板目录和流程里引用的模板文件是否都存在 ——
   等到运行时才发现 ``xxx.png`` 不存在，是最浪费时间的一种 bug；
3. 按 backend 选后端（windows / android / fake），构造 Session；
4. 按 ocr_engine 选 OCR 实现（没有就退化成 ``UnavailableTextReader``）；
5. 造 Match 实现（OpenCV 模板匹配）；
6. 加载流程定义、加载区域表、造 Context 与 Engine。

**关于 Matcher / OCR 的实现**：它们依赖 opencv / rapidocr，属于"可选重依赖"，
所以放在 ``gamebot.vision`` 包里，按需 import。本文件只负责挑和接。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .atomic.session import Session, build_session
from .atomic.vision import Matcher, TextReader, UnavailableTextReader
from .config.loader import load_config, load_regions
from .config.schema import AppConfig, BackendKind
from .context import RunContext
from .exceptions import ConfigError, GameBotError, TemplateNotFoundError
from .execution.executor import Executor, ExecutorHooks
from .execution.journal import Journal, JsonlJournal, NullJournal
from .flow.engine import FlowEngine, RunReport
from .flow.loader import load_scenario
from .flow.scenario import Scenario
from .utils.logging import get_logger, setup_logging

log = get_logger("bootstrap")

__all__ = [
    "bootstrap",
    "build_context",
    "build_engine",
    "build_matcher",
    "build_reader",
    "build_session_from_config",
    "check_config_paths",
    "check_templates",
    "run_scenario",
]


# --------------------------------------------------------------------------- #
# 视觉部件
# --------------------------------------------------------------------------- #
def build_matcher(config: AppConfig) -> Matcher:
    """造模板匹配实现（OpenCV ``matchTemplate``）。

    ``preload=True``：启动时把模板目录整个读进内存。好处是第一次查询不会卡一下，
    坏处是模板路径写错时启动就炸 —— 这正是我们想要的（早炸早发现）。

    :raises TemplateNotFoundError: 预加载时遇到损坏的模板文件。
    """
    from .vision.opencv_matcher import OpenCvMatcher

    roots = config.template_roots()
    matcher = OpenCvMatcher(
        templates_dir=roots[-1],
        # 前面的都是附加根（功能级），优先搜索
        extra_dirs=roots[:-1],
        grayscale=config.vision.grayscale,
        use_pyramid=config.vision.use_pyramid,
        preload=True,
    )
    log.info(
        "模板匹配就绪: %d 个模板, %d 个模板根, 灰度=%s, 多尺度=%s",
        len(matcher.cached_templates),
        len(roots),
        matcher.grayscale,
        matcher.use_pyramid,
    )
    return matcher


def build_reader(config: AppConfig) -> TextReader:
    """造 OCR 实现。``ocr_engine == "none"`` 时返回退化实现（不报错）。

    这是刻意的：找图能撑起绝大多数游戏脚本，OCR 是加分项。
    没装 OCR 就整个跑不起来，是很糟糕的体验。
    """
    engine = config.vision.ocr_engine.lower()
    if engine in ("none", "", "off"):
        log.info("未启用 OCR，find_text / read_text 将返回 not_found")
        return UnavailableTextReader("config.vision.ocr_engine = none")

    if engine == "rapid":
        from .vision.ocr import RapidOcrReader

        reader = RapidOcrReader(lang=config.vision.ocr_lang)
        if config.meta.get("ocr_warmup", True):
            # 第一次 OCR 要加载 onnx 模型（几秒），挪到启动阶段，别让流程误判超时
            reader.warmup()
        return reader

    if engine == "tesseract":
        from .vision.ocr import TesseractReader

        return TesseractReader(
            tesseract_cmd=str(config.meta.get("tesseract_cmd", "")),
            lang="eng" if config.vision.ocr_lang == "en" else "eng+chi_sim",
        )

    raise ConfigError(
        f"未知 OCR 引擎: {config.vision.ocr_engine!r}（可选 none / rapid / tesseract）"
    )


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
def build_session_from_config(config: AppConfig) -> Session:
    """按配置装配 Session（含后端选择与坐标映射）。"""
    screen = config.screen
    kwargs: dict[str, Any] = {}
    if screen.backend is BackendKind.WINDOWS:
        kwargs = {
            "window_title": screen.window_title,
            "monitor_index": screen.monitor_index,
            "client_area_only": screen.client_area_only,
            "input_engine": screen.input_engine,
        }
    elif screen.backend is BackendKind.ANDROID:
        kwargs = {
            "serial": screen.serial,
            "adb_path": screen.adb_path,
            "max_fps": screen.max_fps,
        }
    elif screen.backend is BackendKind.FAKE:
        kwargs = {"size": screen.source_size or (1280, 720)}

    session = build_session(
        screen.backend.value,
        matcher=build_matcher(config),
        reader=build_reader(config),
        logic_size=screen.logic_size,
        **kwargs,
    )
    log.info(
        "Session 就绪: backend=%s, source=%s, logic=%s",
        screen.backend.value,
        session.mapper.source_width,
        screen.logic_size,
    )
    return session


# --------------------------------------------------------------------------- #
# 装配期检查
# --------------------------------------------------------------------------- #
def check_templates(config: AppConfig, scenario: Scenario) -> list[str]:
    """检查脚本引用的模板文件是否都存在，返回缺失列表。

    **这是装配期最有价值的一个检查**。模板名拼错、导出时忘了放进 assets、
    大小写不一致……这些问题在运行期表现为"莫名其妙找不到图"（而且是在
    某个分支才出现，跑了十分钟才撞上），排查成本极高；
    在这里只是一行路径比较。

    查两个来源：

    1. **页面树**里所有 Query 的 ``template``（含嵌套组合查询）——
       决定"能不能认出来是哪一页"；
    2. **流程图**里所有 Step 的 :meth:`Step.used_templates` ——
       决定"点不点得动"。

    第 2 条容易漏：页面条件用的图往往就那几张，真正多的是各种按钮。
    只查第 1 条会让检查给出"模板齐全"的假安全感。
    自定义步骤请覆写 ``used_templates()``，否则查不到（漏报，不误伤）。
    """
    missing: list[str] = []
    roots = config.template_roots()

    for template in sorted(_collect_templates(scenario)):
        # 任何一个模板根里有就算找到（附加根优先，但对"存在性"检查无所谓顺序）
        if not any((root / template).is_file() for root in roots):
            missing.append(template)
    return missing


def _collect_templates(scenario: Scenario) -> set[str]:
    """提取整份脚本会用到的模板名：页面查询 + 步骤。"""
    found: set[str] = set()

    def walk_query(obj: Any, depth: int = 0) -> None:
        if depth > 8:  # 组合查询最多嵌几层，防手滑写出环
            return
        template = getattr(obj, "template", None)
        if isinstance(template, str) and template:
            found.add(template)
        for attr in ("queries", "query", "exclude"):
            nested = getattr(obj, attr, None)
            if nested is None:
                continue
            if isinstance(nested, (list, tuple)):
                for item in nested:
                    walk_query(item, depth + 1)
            else:
                walk_query(nested, depth + 1)

    for page in scenario.tree.walk():
        walk_query(page)

    for node in scenario.graph.nodes.values():
        for step in (*node.steps, *node.on_enter, *node.on_exit):
            used = getattr(step, "used_templates", None)
            if callable(used):
                found.update(t for t in used() if t)

    return found


def check_config_paths(config: AppConfig) -> None:
    """确保运行期目录存在。"""
    config.paths.ensure()


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
def build_context(
    config: AppConfig,
    *,
    scenario: Scenario | None = None,
    session: Session | None = None,
    journal: Journal | None = None,
    hooks: ExecutorHooks | None = None,
) -> RunContext:
    """装配 RunContext（含 Session 与 Executor）。

    ``scenario`` 用来构造页面跟踪器 —— 跟踪器需要页面树才能查
    ``min_stable_frames`` / ``timeout``。没给就是一棵空树（跟踪器退化，但仍可用）。
    """
    session = session or build_session_from_config(config)
    ctx = RunContext(
        session,
        config,
        tree=scenario.tree if scenario is not None else None,
        frame_ttl=max(0.2, config.timing.tick_interval * 2),
    )
    ctx.executor = Executor(
        ctx,
        hooks=hooks,
        journal=journal or NullJournal(),
        dry_run=config.dry_run,
    )
    return ctx


def build_engine(
    config: AppConfig,
    ctx: RunContext,
    scenario: Scenario,
) -> FlowEngine:
    """装配流程引擎。"""
    return FlowEngine(scenario, ctx, executor=ctx.executor)


def bootstrap(
    config_path: str | Path = "config/app.yaml",
    *,
    overrides: dict[str, Any] | None = None,
    journal: Journal | None = None,
) -> tuple[RunContext, FlowEngine]:
    """一次完整的装配：配置 -> 日志 -> 目录 -> 视觉 -> Session -> 脚本 -> 引擎。

    :return: ``(ctx, engine)``，调用方接着 ``engine.run()``。
    """
    config = load_config(config_path, overrides=overrides)

    log_file = config.paths.resolve(config.logging.file) if config.logging.file else None
    setup_logging(config.logging.level, log_file=log_file)

    check_config_paths(config)

    regions = load_regions(config.paths.resolve("config/regions.yaml"))
    if regions:
        config.vision.roi.update(regions)
        log.debug("已加载 %d 个命名区域", len(regions))

    scenario = load_scenario(config.paths.resolve(config.flow_file))
    missing = check_templates(config, scenario)
    if missing:
        raise TemplateNotFoundError(
            "以下模板图不存在（检查 assets/templates 与页面树里的路径）:\n  - "
            + "\n  - ".join(missing)
        )

    ctx = build_context(config, scenario=scenario, journal=journal)
    engine = build_engine(config, ctx, scenario)
    log.info(
        "装配完成: %r, %d 页面 / %d 节点 / %d 边",
        scenario.name,
        len(scenario.tree),
        len(scenario.graph),
        len(scenario.graph.edges),
    )
    unclaimed = scenario.unclaimed_pages()
    if unclaimed:
        log.info("以下页面没有节点认领（只观察不动作）: %s", ", ".join(unclaimed))
    return ctx, engine


def run_scenario(
    config_path: str | Path = "config/app.yaml",
    *,
    overrides: dict[str, Any] | None = None,
    log_journal: bool = True,
) -> RunReport:
    """装配并跑完一次脚本，返回报告。CLI 的主入口之一。"""
    ctx: RunContext | None = None
    journal: Journal | None = None
    try:
        config = load_config(config_path, overrides=overrides)
        if log_journal:
            journal = JsonlJournal(Path(config.paths.resolve(config.paths.journals)) / "run.jsonl")
        ctx, engine = bootstrap(config_path, overrides=overrides, journal=journal)
        return engine.run()
    except GameBotError:
        raise
    finally:
        if ctx is not None:
            ctx.close()
        if journal is not None:
            journal.close()
