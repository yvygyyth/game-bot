"""装配 —— 从 :class:`~gamebot.feature.FeatureSpec` 接到可跑的引擎。

产出是 ``(RunContext, FlowEngine)``。所有重依赖的 import 发生在这里。

**装配期的职责**（错了就在这里炸，别拖到运行期）：

1. 解析仓库根与模板目录、建日志目录；
2. 造 Matcher（OpenCV）与 Session（Windows 找窗）；
3. 接事件流（总线 + JSONL）与状态仓库（跨运行的记忆）；
4. 物化 Scenario、造 Context 与 Engine。

**装配期也是唯一"把三样东西接起来"的地方**：仓库的变更回调 -> ``store_changed``
事件，执行器的前后钩子 -> ``step_started`` / ``step_finished`` 事件。
状态层和流程层各自都**不认识**事件这个概念，接线只在这里做。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .atomic.session import Session, build_session
from .atomic.vision import Matcher, TextReader, UnavailableTextReader
from .config.schema import RunPaths
from .context import RunContext
from .events import Event, EventBus, EventKind, JsonlEventWriter
from .execution.executor import Executor, ExecutorHooks
from .execution.journal import Journal, NullJournal
from .flow.engine import FlowEngine
from .flow.scenario import Scenario
from .state.store import StoreChange, StoreManager
from .utils.integrity import check_integrity
from .utils.logging import get_logger
from .vision.recorder import RecognitionRecorder

if TYPE_CHECKING:
    from .feature import FeatureSpec

log = get_logger("bootstrap")

__all__ = [
    "bootstrap_from_spec",
    "build_engine",
    "build_event_bus",
    "build_matcher",
    "build_reader",
    "build_recorder",
    "build_store_manager",
    "project_root",
]


def project_root() -> Path:
    """仓库根：``games`` 包的上一级。"""
    import games

    return Path(games.__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# 视觉部件
# --------------------------------------------------------------------------- #
def build_matcher(
    templates_dir: Path,
    *,
    fallback_dirs: tuple[Path, ...] = (),
    recorder: Any = None,
    grayscale: bool = True,
    use_pyramid: bool = True,
) -> Matcher:
    """造模板匹配实现（OpenCV ``matchTemplate``）。

    ``preload=True``：启动时把**所有模板根**整个读进内存。路径写错时启动就炸。

    :param templates_dir: 主根（功能级）。业务层写的模板名相对它。
    :param fallback_dirs: 兜底根（游戏级公共模板）。主根找不到时才回落 ——
        这样"功能级写自己的图、公共图放游戏级"能共存，且功能级可以覆盖同名图。
    """
    from .vision.opencv_matcher import OpenCvMatcher

    matcher = OpenCvMatcher(
        templates_dir=templates_dir,
        fallback_dirs=fallback_dirs,
        grayscale=grayscale,
        use_pyramid=use_pyramid,
        preload=True,
    )
    log.info(
        "模板匹配就绪: %d 个模板, 根=%s, 兜底=%s, 灰度=%s, 多尺度=%s",
        len(matcher.cached_templates),
        templates_dir,
        ", ".join(str(d) for d in fallback_dirs) or "（无）",
        matcher.grayscale,
        matcher.use_pyramid,
    )
    return recorder.wrap_matcher(matcher) if recorder is not None else matcher


def _module_available(name: str) -> bool:
    """这个包**装没装**（不导入，只看能不能找到）。"""
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover - 极端环境
        return False


def choose_ocr_engine(is_available: Callable[[str], bool] | None = None) -> str | None:
    """挑一个能用的 OCR 引擎。都没有返回 ``None``。

    顺序是 **RapidOCR -> Tesseract**：前者是纯 pip 包（模型自带），
    ``uv sync --extra ocr-rapid`` 之后就能用；后者还要单独装 exe，
    能用前一个时不该折腾它。

    :param is_available: "这个包在不在"的探测函数。测试注入用 —— 免得
        用例的结果取决于跑测试那台机器装了什么。
    """
    probe = is_available or _module_available
    for engine, module in (("rapid", "rapidocr_onnxruntime"), ("tesseract", "pytesseract")):
        if probe(module):
            return engine
    return None


def build_reader(*, recorder: Any = None, engine: str = "auto") -> TextReader:
    """造 OCR 实现。``engine``：``"auto"``（默认）/ ``"rapid"`` / ``"tesseract"`` / ``"none"``。

    ## 为什么要"自动选"

    早先这里**永远**返回 ``UnavailableTextReader``，于是不管装没装 OCR，
    ``find_text`` / ``read_text`` / ``read_number`` 全是 ``not_found`` ——
    `vision/ocr.py` 里那两个实现写了却**从没被接上**，属于"代码在、路不通"。
    装依赖是用户明确的动作（``--extra ocr-rapid``），装了就说明想用。

    没装时照旧退化，并且在日志里说清"为什么没有文字识别"——
    否则 ``find_text`` 返回 ``not_found`` 看起来和"画面上真没有那行字"一模一样。
    """
    chosen = engine
    if engine == "auto":
        chosen = choose_ocr_engine() or "none"

    reader: TextReader
    if chosen == "rapid":
        from .vision.ocr import RapidOcrReader

        reader = RapidOcrReader()
        log.info("OCR 已启用: RapidOCR")
    elif chosen == "tesseract":
        from .vision.ocr import TesseractReader

        reader = TesseractReader()
        log.info("OCR 已启用: Tesseract")
    else:
        if engine not in ("auto", "none"):
            log.warning(
                "未知的 OCR 引擎 %r（可选 auto/rapid/tesseract/none），按未启用处理",
                engine,
            )
        reader = UnavailableTextReader(
            "OCR 未启用（没装 rapidocr-onnxruntime / pytesseract）"
        )
        log.info("未启用 OCR，find_text / read_text 将返回 not_found")
    return recorder.wrap_reader(reader) if recorder is not None else reader


def build_recorder(
    paths: RunPaths,
    *,
    keep: int = 200,
    on_record: Any = None,
) -> RecognitionRecorder:
    """造识别记录器（带框图落在 screenshots 目录）。"""
    recorder = RecognitionRecorder(
        directory=paths.resolve(paths.screenshots),
        keep=keep,
        on_record=on_record,
    )
    log.info("识图记录已启用: 最多留 %d 张带框的图 → %s", recorder.keep, recorder.directory)
    return recorder


def build_event_bus(
    paths: RunPaths,
    *,
    slug: str = "run",
    record: bool = True,
) -> EventBus:
    """造事件总线。``record=True`` 时顺手把事件落进 ``logs/events/<slug>.jsonl``。

    为什么默认落盘：事件流最大的用处是**事后复盘**（"它那一晚到底是几点开始
    不对的"）。只在内存里留 200 条的话，界面一关就没了，而一次真机跑要几十分钟。
    """
    bus = EventBus()
    if record:
        writer = JsonlEventWriter(paths.resolve(Path("logs") / "events" / f"{slug}.jsonl"))
        bus.subscribe(writer)
        log.info("事件流: %s", writer.path)
    return bus


def build_store_manager(
    paths: RunPaths,
    *,
    game: str,
    on_change: Callable[[StoreChange], None] | None = None,
) -> StoreManager:
    """造状态仓库管理器。落盘根固定为 ``<仓库根>/data/stores``。

    放 ``data/`` 而不是 ``logs/``：``logs/`` 是**运行产物**（会清、会按次分目录），
    而记忆是"下次开还要用的东西"。
    """
    manager = StoreManager(
        paths.resolve(Path("data") / "stores"),
        game=game,
        on_change=on_change,
    )
    log.info("状态仓库: %s", manager.root)
    return manager


def make_store_change_emitter(
    bus: EventBus,
    ctx_getter: Callable[[], Any],
) -> Callable[[StoreChange], None]:
    """把仓库的变更回调接到事件流上（``store_changed``）。

    单独一个函数是为了**能被直接测**：这里接错一个属性名，表现是
    "仓库确实在变、但事件流里一条 ``store_changed`` 都没有" ——
    静默缺失，比报错难查得多。

    :param ctx_getter: 取当前上下文的函数。装配期上下文还没造好，所以传个
        "取的时候再说"的闭包，而不是直接传 ctx。
    """

    def emit_change(change: StoreChange) -> None:
        ctx = ctx_getter()
        if ctx is None:  # pragma: no cover - 开跑前不会写仓库
            return
        bus.emit(
            Event(
                EventKind.STORE_CHANGED,
                at=ctx.now(),
                tick=ctx.pages.tick,
                data=change.to_dict(),
            )
        )

    return emit_change


def build_engine(
    ctx: RunContext,
    scenario: Scenario,
    *,
    events: EventBus | None = None,
) -> FlowEngine:
    """装配流程引擎。

    :param events: 事件总线；不传就用 ``ctx.events``（装配期挂在上下文字上那份）。
    """
    executor = ctx.executor
    if executor is not None:
        executor.save_frames_on_error = bool(
            getattr(scenario.options, "save_frames_on_error", False)
        )
    return FlowEngine(scenario, ctx, executor=executor, events=events)


def bootstrap_from_spec(
    feature: FeatureSpec,
    *,
    dry_run: bool = False,
    window_title: str | None = None,
    params: Mapping[str, Any] | None = None,
    journal: Journal | None = None,
    hooks: ExecutorHooks | None = None,
    session: Session | None = None,
    recorder: RecognitionRecorder | None = None,
    events: EventBus | None = None,
    record: bool = True,
    record_events: bool = True,
    ocr: str = "auto",
    root: Path | None = None,
) -> tuple[RunContext, FlowEngine]:
    """从脚本声明装配 ``(RunContext, FlowEngine)``。

    :param window_title: 覆盖 ``FeatureSpec.window_title``（UI 选窗时用）。
    :param dry_run: 空跑：只识别、不操作。
    :param recorder: 外部传入的识别记录器（界面长期持有那份）；不传则按 ``record`` 自造。
    :param events: 外部传入的事件总线（界面要订阅）；不传就造一个（默认落盘）。
    :param record_events: 自造总线时要不要落 ``logs/events/``；界面可用它只订阅不落盘。
    :param ocr: OCR 引擎，``auto`` / ``rapid`` / ``tesseract`` / ``none``
        （见 :func:`build_reader`）。
    :param root: 仓库根。不传就按 ``games`` 包的位置推 —— **测试会传临时目录**
        （否则跑一次装配就往项目的 ``logs/`` / ``data/`` 里写东西）。
    """
    base = root if root is not None else project_root()
    paths = RunPaths.under(base)
    paths.ensure()

    title = (window_title if window_title is not None else feature.window_title).strip()
    templates = paths.resolve(feature.templates_dir)
    if not templates.is_dir():
        from .exceptions import ConfigError

        raise ConfigError(f"{feature.name}: 模板目录不存在: {templates}")

    bus = events if events is not None else build_event_bus(
        paths, slug=feature.slug, record=record_events
    )

    # 仓库的回调需要 ctx（拿 tick / 时钟），但 ctx 又要收下这个 manager ——
    # 用一个小盒子打破这个循环。写入只发生在开跑之后，那时 ctx 一定已经在了。
    holder: dict[str, Any] = {}
    stores = build_store_manager(
        paths,
        game=feature.name.split("/", 1)[0],
        on_change=make_store_change_emitter(bus, lambda: holder.get("ctx")),
    )

    if recorder is None and record:
        recorder = build_recorder(paths)
    # 游戏级公共模板（跨脚本共用）：功能级找不到时回落。
    game_templates = paths.resolve(feature.game_templates_dir)
    matcher = build_matcher(
        templates,
        fallback_dirs=(game_templates,) if game_templates.is_dir() else (),
        recorder=recorder,
        use_pyramid=feature.use_pyramid,
    )
    reader = build_reader(recorder=recorder, engine=ocr)

    if session is None:
        session = build_session(
            "windows",
            matcher=matcher,
            reader=reader,
            window_title=title,
            client_area_only=True,
            coordinate_space="source",
            logic_size=None,
        )
        log.info(
            "Session 就绪: backend=windows, source=%sx%s, window=%r",
            session.mapper.source_width,
            session.mapper.source_height,
            title,
        )
        if title:
            warning = check_integrity(title)
            if warning:
                log.warning("%s", warning)

    scenario = feature.materialize_scenario()
    tick = scenario.options.tick_interval or 0.4
    ctx = RunContext(
        session,
        name=feature.name,
        paths=paths,
        tree=scenario.tree,
        frame_ttl=max(0.2, tick * 2),
        params=params,
        stores=stores,
        events=bus,
    )
    holder["ctx"] = ctx

    # 注意：**步骤级事件不在这里接线** —— 由引擎挂在执行器上（见
    # ``FlowEngine.__init__`` 里的 ``add_hooks``）。这样测试里 new 一个引擎
    # 也能拿到完整事件流，而"事件从哪来"也只有引擎一处。
    ctx.executor = Executor(
        ctx,
        hooks=hooks,
        journal=journal or NullJournal(),
        dry_run=dry_run,
        save_frames_on_error=bool(getattr(scenario.options, "save_frames_on_error", False)),
    )
    ctx.recorder = recorder

    engine = build_engine(ctx, scenario, events=bus)
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
