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
from typing import TYPE_CHECKING, Any

from .atomic.session import Session, build_session
from .atomic.vision import Matcher, TextReader, UnavailableTextReader
from .config.loader import load_config, load_regions
from .config.schema import AppConfig, BackendKind
from .context import RunContext
from .exceptions import ConfigError, GameBotError, TemplateNotFoundError
from .execution.executor import Executor, ExecutorHooks
from .execution.journal import Journal, JsonlJournal, NullJournal
from .flow.definition import FlowDefinition
from .flow.engine import EngineOptions, FlowEngine, RunReport
from .flow.loader import load_flow
from .state.detector import StateDetector
from .utils.logging import get_logger, setup_logging

if TYPE_CHECKING:
    pass

log = get_logger("bootstrap")

__all__ = [
    "bootstrap",
    "build_context",
    "build_engine",
    "build_matcher",
    "build_reader",
    "build_session_from_config",
    "check_templates",
    "run_flow",
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

    matcher = OpenCvMatcher(
        templates_dir=config.paths.resolve(config.vision.templates_dir),
        grayscale=config.vision.grayscale,
        use_pyramid=config.vision.use_pyramid,
        preload=True,
    )
    log.info("模板匹配就绪: %d 个模板, 灰度=%s, 多尺度=%s",
             len(matcher.cached_templates), matcher.grayscale, matcher.use_pyramid)
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
def check_templates(config: AppConfig, definition: FlowDefinition) -> list[str]:
    """检查流程引用的模板文件是否都存在，返回缺失列表。

    **这是装配期最有价值的一个检查**。模板名拼错、导出时忘了放进 assets、
    大小写不一致……这些问题在运行期表现为"莫名其妙找不到图"，
    排查成本极高；在这里只是一行路径比较。

    做法：遍历 definition 里所有 Query 的 ``template`` 字段（含嵌套组合查询），
    逐个 ``config.template_path()`` 查存在性。
    """
    raise NotImplementedError("待实现：递归提取 template 字段 -> 查文件存在性 -> 返回缺失列表")


def check_config_paths(config: AppConfig) -> None:
    """确保运行期目录存在。"""
    config.paths.ensure()


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
def build_context(
    config: AppConfig,
    *,
    session: Session | None = None,
    journal: Journal | None = None,
    hooks: ExecutorHooks | None = None,
) -> RunContext:
    """装配 RunContext（含 Session 与 Executor）。"""
    session = session or build_session_from_config(config)
    ctx = RunContext(
        session,
        config,
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
    definition: FlowDefinition,
    *,
    options: EngineOptions | None = None,
) -> FlowEngine:
    """装配流程引擎。"""
    detector = StateDetector(definition.states)
    return FlowEngine(
        definition,
        ctx,
        detector=detector,
        executor=ctx.executor,
        options=options or EngineOptions.from_definition(definition),
    )


def bootstrap(
    config_path: str | Path = "config/app.yaml",
    *,
    overrides: dict[str, Any] | None = None,
    journal: Journal | None = None,
) -> tuple[RunContext, FlowEngine]:
    """一次完整的装配：配置 -> 日志 -> 目录 -> 视觉 -> Session -> 流程 -> 引擎。

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

    definition = load_flow(config.paths.resolve(config.flow_file))
    missing = check_templates(config, definition)
    if missing:
        raise TemplateNotFoundError(
            "以下模板图不存在（检查 assets/templates 与流程配置里的路径）:\n  - "
            + "\n  - ".join(missing)
        )

    ctx = build_context(config, journal=journal)
    engine = build_engine(config, ctx, definition)
    log.info("装配完成: flow=%r, states=%d, transitions=%d",
             definition.name, len(definition.states), len(definition.transitions))
    return ctx, engine


def run_flow(
    config_path: str | Path = "config/app.yaml",
    *,
    overrides: dict[str, Any] | None = None,
    log_journal: bool = True,
) -> RunReport:
    """装配并跑完一次流程，返回报告。CLI 的主入口之一。"""
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
