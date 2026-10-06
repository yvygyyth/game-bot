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
   ``load_scenario`` 内部会跑 ``Scenario.validate()`` —— 状态 id 写错、有状态
   没有任何流程节点认领，都在这一步就炸，而不是跑到一半才"什么都不做"。

**关于 Matcher / OCR 的实现**：它们依赖 opencv / rapidocr，属于"可选重依赖"，
所以放在 ``gamebot.vision`` 包里，按需 import。本文件只负责挑和接。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .atomic.session import Session, build_session
from .atomic.vision import Matcher, TextReader, UnavailableTextReader
from .config.loader import load_config, load_regions
from .config.schema import AppConfig, BackendKind
from .context import RunContext
from .exceptions import ConfigError, GameBotError
from .execution.executor import Executor, ExecutorHooks
from .execution.journal import Journal, JsonlJournal, NullJournal
from .flow.engine import FlowEngine, RunReport
from .flow.loader import load_scenario
from .flow.scenario import Scenario
from .utils.logging import get_logger, setup_logging
from .vision.recorder import RecognitionRecorder

log = get_logger("bootstrap")

__all__ = [
    "bootstrap",
    "build_context",
    "build_engine",
    "build_matcher",
    "build_reader",
    "build_recorder",
    "build_session_from_config",
    "check_config_paths",
    "run_scenario",
]


# --------------------------------------------------------------------------- #
# 视觉部件
# --------------------------------------------------------------------------- #
def build_matcher(config: AppConfig, recorder: Any = None) -> Matcher:
    """造模板匹配实现（OpenCV ``matchTemplate``）。

    ``preload=True``：启动时把模板目录整个读进内存。好处是第一次查询不会卡一下，
    坏处是模板路径写错时启动就炸 —— 这正是我们想要的（早炸早发现）。

    :param recorder: 识别记录器。给了就把 Matcher **包一层**（记录每次匹配并
        画框存图），原子层完全不知道这件事存在。见 ``vision/recorder.py``。

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
    return recorder.wrap_matcher(matcher) if recorder is not None else matcher


def build_reader(config: AppConfig, recorder: Any = None) -> TextReader:
    """造 OCR 实现。``ocr_engine == "none"`` 时返回退化实现（不报错）。

    这是刻意的：找图能撑起绝大多数游戏脚本，OCR 是加分项。
    没装 OCR 就整个跑不起来，是很糟糕的体验。

    :param recorder: 识别记录器；给了就包一层（OCR 的框也画出来）。
    """
    engine = config.vision.ocr_engine.lower()
    if engine in ("none", "", "off"):
        log.info("未启用 OCR，find_text / read_text 将返回 not_found")
        reader: TextReader = UnavailableTextReader("config.vision.ocr_engine = none")
        return recorder.wrap_reader(reader) if recorder is not None else reader

    if engine == "rapid":
        from .vision.ocr import RapidOcrReader

        rapid = RapidOcrReader(lang=config.vision.ocr_lang)
        if config.meta.get("ocr_warmup", True):
            # 第一次 OCR 要加载 onnx 模型（几秒），挪到启动阶段，别让流程误判超时
            rapid.warmup()
        return recorder.wrap_reader(rapid) if recorder is not None else rapid

    if engine == "tesseract":
        from .vision.ocr import TesseractReader

        tess = TesseractReader(
            tesseract_cmd=str(config.meta.get("tesseract_cmd", "")),
            lang="eng" if config.vision.ocr_lang == "en" else "eng+chi_sim",
        )
        return recorder.wrap_reader(tess) if recorder is not None else tess

    raise ConfigError(
        f"未知 OCR 引擎: {config.vision.ocr_engine!r}（可选 none / rapid / tesseract）"
    )


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
def build_recorder(
    config: AppConfig,
    *,
    on_record: Any = None,
) -> RecognitionRecorder | None:
    """按配置造识别记录器（``vision.record`` 关了就是 ``None``）。

    存图目录用 ``paths.screenshots``（和失败帧、手工截图同一个目录）——
    清理时只删本框架写的 ``match_*.png``，不会碰到别的图。
    """
    if not config.vision.record:
        log.info("未启用识图记录（config.vision.record = false）")
        return None
    recorder = RecognitionRecorder(
        directory=config.paths.resolve(config.paths.screenshots),
        keep=config.vision.record_keep,
        on_record=on_record,
    )
    log.info("识图记录已启用: 最多留 %d 张带框的图 → %s", recorder.keep, recorder.directory)
    return recorder


def build_session_from_config(
    config: AppConfig,
    *,
    recorder: RecognitionRecorder | None = None,
) -> Session:
    """按配置装配 Session（含后端选择与坐标映射）。

    :param recorder: 识别记录器。给了就把 Matcher / Reader 各包一层，
        于是**这个 Session 上的所有查询**都会被记下来（不用在每个调用点插桩）。
    """
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
        matcher=build_matcher(config, recorder),
        reader=build_reader(config, recorder),
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
    recorder: RecognitionRecorder | None = None,
    scenario_options: object | None = None,
    params: Mapping[str, Any] | None = None,
) -> RunContext:
    """装配 RunContext（含 Session 与 Executor）。

    ``scenario`` 用来构造状态跟踪器 —— 跟踪器需要状态树才能查
    ``min_stable_frames`` / ``timeout``。没给就是一棵空树（跟踪器退化，但仍可用）。

    :param recorder: 识别记录器。不传时**按配置自动造一个**
        （``vision.record`` 为假则是 ``None``）；界面会从 ``ctx.recorder`` 拿它
        来显示"识图日志"和带框的图。
    :param scenario_options: 流程层的运行选项（``Scenario.options``）。**故意用
        ``object`` 而不是导入那个类型**：配置层不该依赖流程层。目前只从中取
        ``save_frames_on_error`` 转交给执行器；没给就按关处理。
    """
    if recorder is None and config.vision.record:
        recorder = build_recorder(config)
    session = session or build_session_from_config(config, recorder=recorder)
    ctx = RunContext(
        session,
        config,
        tree=scenario.tree if scenario is not None else None,
        frame_ttl=max(0.2, config.timing.tick_interval * 2),
        params=params,
    )
    ctx.executor = Executor(
        ctx,
        hooks=hooks,
        journal=journal or NullJournal(),
        dry_run=config.dry_run,
        # 把流程层的开关在这里翻译成布尔值交给执行器：执行层不该 import
        # 流程层的 Options 类型（依赖方向），但"失败要不要存帧"这件事
        # 只有执行器知道时机 —— 它必须在写 journal **之前**存，
        # 这样帧路径才能跟着那一条记录一起落盘。
        save_frames_on_error=bool(getattr(scenario_options, "save_frames_on_error", False)),
    )
    ctx.recorder = recorder
    return ctx


def build_engine(
    config: AppConfig,
    ctx: RunContext,
    scenario: Scenario,
) -> FlowEngine:
    """装配流程引擎。

    顺手补一次 ``save_frames_on_error``：调用方可能只把 ``scenario`` 交给
    ``build_context``（跟踪器需要它）而没传 ``scenario_options``。这一句保证
    "存失败帧"那个开关不会因为调用约定不同而悄悄失效 —— 那正是它之前的样子。
    """
    executor = ctx.executor
    if executor is not None:
        executor.save_frames_on_error = bool(
            getattr(scenario.options, "save_frames_on_error", False)
        )
    return FlowEngine(scenario, ctx, executor=executor)


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

    ctx = build_context(
        config,
        scenario=scenario,
        journal=journal,
        # 显式传一次（build_engine 里还有一道兜底）：这个开关决定
        # "失败时存不存帧、存了能不能在 journal 里找到"，不能靠调用约定。
        scenario_options=scenario.options,
    )
    engine = build_engine(config, ctx, scenario)
    log.info(
        "装配完成: %r, %d 状态 / %d 节点 / %d 边",
        scenario.name,
        len(scenario.tree),
        len(scenario.graph),
        len(scenario.graph.edges),
    )
    unclaimed = scenario.unclaimed_pages()
    if unclaimed:
        log.info("以下状态没有节点认领（不会出现在定位结果里）: %s", ", ".join(unclaimed))
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
