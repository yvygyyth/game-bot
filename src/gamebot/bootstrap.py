"""装配 —— 从 :class:`~gamebot.feature.FeatureSpec` 接到可跑的引擎。

产出是 ``(RunContext, FlowEngine)``。所有重依赖的 import 发生在这里。

**装配期的职责**（错了就在这里炸，别拖到运行期）：

1. 解析仓库根与模板目录、建日志目录；
2. 造 Matcher（OpenCV）与 Session（Windows 找窗）；
3. 物化 Scenario、造 Context 与 Engine。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .atomic.session import Session, build_session
from .atomic.vision import Matcher, TextReader, UnavailableTextReader
from .config.schema import RunPaths
from .context import RunContext
from .execution.executor import Executor, ExecutorHooks
from .execution.journal import Journal, NullJournal
from .flow.engine import FlowEngine
from .flow.scenario import Scenario
from .utils.integrity import check_integrity
from .utils.logging import get_logger
from .vision.recorder import RecognitionRecorder

if TYPE_CHECKING:
    from .feature import FeatureSpec

log = get_logger("bootstrap")

__all__ = [
    "bootstrap_from_spec",
    "build_engine",
    "build_matcher",
    "build_reader",
    "build_recorder",
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
    recorder: Any = None,
    grayscale: bool = True,
    use_pyramid: bool = True,
) -> Matcher:
    """造模板匹配实现（OpenCV ``matchTemplate``）。

    ``preload=True``：启动时把模板目录整个读进内存。路径写错时启动就炸。
    """
    from .vision.opencv_matcher import OpenCvMatcher

    matcher = OpenCvMatcher(
        templates_dir=templates_dir,
        grayscale=grayscale,
        use_pyramid=use_pyramid,
        preload=True,
    )
    log.info(
        "模板匹配就绪: %d 个模板, 根=%s, 灰度=%s, 多尺度=%s",
        len(matcher.cached_templates),
        templates_dir,
        matcher.grayscale,
        matcher.use_pyramid,
    )
    return recorder.wrap_matcher(matcher) if recorder is not None else matcher


def build_reader(*, recorder: Any = None) -> TextReader:
    """OCR 默认关闭（找图撑绝大多数脚本）。"""
    reader: TextReader = UnavailableTextReader("OCR 未启用")
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


def build_engine(ctx: RunContext, scenario: Scenario) -> FlowEngine:
    """装配流程引擎。"""
    executor = ctx.executor
    if executor is not None:
        executor.save_frames_on_error = bool(
            getattr(scenario.options, "save_frames_on_error", False)
        )
    return FlowEngine(scenario, ctx, executor=executor)


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
    record: bool = True,
) -> tuple[RunContext, FlowEngine]:
    """从脚本声明装配 ``(RunContext, FlowEngine)``。

    :param window_title: 覆盖 ``FeatureSpec.window_title``（UI 选窗时用）。
    :param dry_run: 空跑：只识别、不操作。
    :param recorder: 外部传入的识别记录器（界面长期持有那份）；不传则按 ``record`` 自造。
    """
    root = project_root()
    paths = RunPaths.under(root)
    paths.ensure()

    title = (window_title if window_title is not None else feature.window_title).strip()
    templates = paths.resolve(feature.templates_dir)
    if not templates.is_dir():
        from .exceptions import ConfigError

        raise ConfigError(f"{feature.name}: 模板目录不存在: {templates}")

    if recorder is None and record:
        recorder = build_recorder(paths)
    matcher = build_matcher(templates, recorder=recorder)
    reader = build_reader(recorder=recorder)

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
    )
    ctx.executor = Executor(
        ctx,
        hooks=hooks,
        journal=journal or NullJournal(),
        dry_run=dry_run,
        save_frames_on_error=bool(getattr(scenario.options, "save_frames_on_error", False)),
    )
    ctx.recorder = recorder

    engine = build_engine(ctx, scenario)
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
