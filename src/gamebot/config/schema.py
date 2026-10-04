"""配置的数据模型。

原则：**配置是数据，不是逻辑**。这里只放字段和默认值，不放解析、不放校验副作用。
校验放 ``loader.py``（或 ``validate()``），业务逻辑一律不在这里。

为什么用 dataclass 而不是直接吃 dict：
* 拼错字段名会在装配期炸，而不是跑到一半返回 None；
* IDE 有补全，改配置时不用翻文档；
* 默认值集中在一处，`AppConfig.defaults()` 就是"最小可跑配置"的定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..types import Region

__all__ = [
    "AppConfig",
    "BackendKind",
    "LoggingConfig",
    "PathsConfig",
    "ScreenConfig",
    "TimingConfig",
    "VisionConfig",
]


class BackendKind(StrEnum):
    """截图 / 输入后端类型。"""

    WINDOWS = "windows"
    """PC 游戏 / PC 客户端：mss + pydirectinput。"""

    ANDROID = "android"
    """手游模拟器 / 真机：adb。"""

    FAKE = "fake"
    """内存假后端：测试和空跑。"""


@dataclass(slots=True)
class ScreenConfig:
    """截图层配置。"""

    backend: BackendKind = BackendKind.WINDOWS
    window_title: str = ""
    """窗口标题关键字。空串表示抓整个显示器。"""

    monitor_index: int = 1
    """mss 显示器序号，1 = 主屏。抓窗口时忽略。"""

    client_area_only: bool = True
    """只抓客户区（不含标题栏 / 边框）。"""

    source_size: tuple[int, int] | None = None
    """源分辨率。None = 运行时自动探测。显式指定可以用来做校验。"""

    logic_size: tuple[int, int] | None = None
    """逻辑分辨率（写脚本用的坐标系）。None = 与源分辨率一致，不做换算。"""

    serial: str = ""
    """adb 设备序列号。多设备时必填。"""

    adb_path: str = "adb"
    """adb 可执行文件路径。"""

    max_fps: float = 5.0
    """adb 截图帧率上限。**不要调太高** —— screencap 很慢，调高只会排队。"""

    input_engine: str = "direct"
    """Windows 输入引擎：``direct`` (pydirectinput) / ``pyautogui``。"""

    default_confidence: float = 0.9
    """找图的默认置信度。单次查询可以覆盖。"""

    keep_awake: bool = True
    """运行时阻止系统休眠 / 屏保。脚本跑了半小时被屏保打断是最蠢的失败方式。"""


@dataclass(slots=True)
class VisionConfig:
    """视觉识别配置。"""

    templates_dir: str = "assets/templates"
    """主模板根。通常是**游戏级公共模板**（断线弹窗、通用按钮……）。"""

    extra_template_dirs: tuple[str, ...] = ()
    """附加模板根，**优先于主根搜索**。

    用途：让每个脚本功能把自己的图片资源放在自己目录里
    （``games/<游戏>/<功能>/templates/``），而不是把全游戏的图都堆到一个目录。
    顺序即优先级，靠前的先搜 —— 于是功能级模板可以覆盖游戏级同名模板。

    解析顺序见 :meth:`AppConfig.template_roots`。
    """

    roi: dict[str, Region] = field(default_factory=dict)
    """命名区域表（从 ``config/regions.yaml`` 加载）。"""

    grayscale: bool = True
    """模板匹配是否灰度化。**通常都该开** —— 快很多，且对颜色渐变更鲁棒。
    只有"靠颜色区分同名图标"时才关。"""

    use_pyramid: bool = True
    """多尺度匹配。窗口可能被缩放时开；分辨率固定时可以关掉换速度。"""

    ocr_engine: str = "none"
    """``none`` / ``rapid`` / ``tesseract``。none 时 find_text 系列返回 not_found。"""

    ocr_lang: str = "ch"
    ocr_confidence: float = 0.8

    max_templates: int = 512
    """模板图缓存上限。启动时预加载，运行时不再读盘。"""


@dataclass(slots=True)
class TimingConfig:
    """节奏配置。**节奏是这个脚本里最需要调的参数**，全放一起。"""

    tick_interval: float = 0.2
    """流程每轮之间的最小间隔。给 0 会打满 CPU 并让日志不可读。"""

    action_interval: float = 0.1
    """连续动作之间的间隔。给太小会被游戏丢事件。"""

    wait_timeout: float = 10.0
    """wait_* 系列默认超时。"""

    wait_interval: float = 0.3
    """wait_* 系列默认轮询间隔。"""

    stable_threshold: float = 0.98
    """画面稳定的相似度阈值。"""

    stable_frames: int = 3
    """连续多少帧算稳定。"""


@dataclass(slots=True)
class PathsConfig:
    """路径配置。相对路径一律相对项目根目录。"""

    root: Path = Path(".")
    assets: Path = Path("assets")
    templates: Path = Path("assets/templates")
    logs: Path = Path("logs")
    screenshots: Path = Path("logs/screenshots")
    journals: Path = Path("logs/journals")

    def resolve(self, path: Path | str) -> Path:
        """把相对路径拼到项目根上。"""
        candidate = Path(path)
        return candidate if candidate.is_absolute() else (self.root / candidate)

    def ensure(self) -> None:
        """创建所有运行期目录。启动时调一次。"""
        for directory in (self.logs, self.screenshots, self.journals, self.templates):
            self.resolve(directory).mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    file: str = ""
    """空串 = 只输出到控制台。"""

    rich_traceback: bool = True
    log_frames_on_error: bool = False
    """失败时自动存图。调试识图问题基本都要开。"""


@dataclass(slots=True)
class AppConfig:
    """应用总配置。装配期读一次，运行期只读。"""

    name: str = "game-bot"
    flow_file: str = "config/flows/example_flow.yaml"
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    dry_run: bool = False
    """空跑：不真的操作游戏，只识别 + 走流程。第一次跑新脚本务必先开。"""

    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> AppConfig:
        """最小可跑配置（Windows 后端 + 假流程）。"""
        return cls()

    def template_roots(self) -> tuple[Path, ...]:
        """模板根的搜索顺序：**附加根（更具体）在前，主根垫底**。

        于是 ``games/<游戏>/<功能>/templates/`` 里的同名模板会覆盖
        ``games/<游戏>/templates/`` 里的那份 —— 功能可以按自己的需要
        替换公共模板，而不用把公共的挪走。
        """
        roots = [self.paths.resolve(d) for d in self.vision.extra_template_dirs]
        roots.append(self.paths.resolve(self.vision.templates_dir))
        return tuple(roots)

    def template_path(self, name: str) -> Path:
        """把模板名解析成绝对路径。

        按 :meth:`template_roots` 的顺序找**第一个存在的**；都不存在时返回
        主根下的路径（报错信息里给个合理的猜测，比返回 ``None`` 好排查）。
        绝对路径原样返回。
        """
        candidate = Path(name)
        if candidate.is_absolute():
            return candidate
        roots = self.template_roots()
        for root in roots:
            path = root / candidate
            if path.is_file():
                return path
        return roots[-1] / candidate

    def region(self, name: str) -> Region | None:
        """按名字取配置好的区域。"""
        return self.vision.roi.get(name)

    def validate(self) -> list[str]:
        """返回问题列表（空列表 = 没问题）。

        只做"跑起来之前一定能发现"的检查，不检查模板文件是否存在
        （那个由装配期单独做，因为需要遍历磁盘）。
        """
        problems: list[str] = []
        if self.screen.backend is BackendKind.ANDROID and not self.screen.adb_path:
            problems.append("android 后端需要 screen.adb_path")
        if self.screen.backend is BackendKind.WINDOWS and self.screen.input_engine not in (
            "direct",
            "pyautogui",
        ):
            problems.append(f"未知的输入引擎: {self.screen.input_engine!r}")
        if self.timing.tick_interval <= 0:
            problems.append("timing.tick_interval 必须 > 0")
        if not 0.0 < self.screen.default_confidence <= 1.0:
            problems.append("screen.default_confidence 必须在 (0, 1] 之间")
        if not self.flow_file:
            problems.append("flow_file 不能为空")
        return problems
