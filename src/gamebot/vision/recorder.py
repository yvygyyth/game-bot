"""识图 / OCR 的记录器 —— **把每一次匹配连图带框留下来**。

## 为什么是"记录匹配"而不是"实时预览"

实时画面看着热闹，但它回答不了调脚本时真正要问的问题：**它到底在哪块上匹配到的？**
同一帧上，"首页 logo 在左上角 0.98"和"首页 logo 在右下角 0.91"在缩略预览里
长得一模一样，但一个是命中、一个是偶然相似。能看出差别的是**框画在图上**。

所以这里做两件事，每次匹配都做：

1. 把当帧 + 命中框（红框）/ 搜索范围（蓝框）画出来存成 PNG；
2. 记一条结构化日志（查了什么、在哪块搜、分数多少、命中还是没中）。

存图有上限（默认 20 张，旧的自动删），日志只留内存里最近若干条 ——
**调脚本时要看的是"刚才那几次"，不是三个月前的**。

## 为什么用"包一层"而不是改 Matcher

``Matcher`` / ``TextReader`` 是协议（``Protocol``），实现只管算法。
在这里包一层的好处：

* 原子层完全不知道"记录"这件事存在，性能和职责都不受影响；
* 同一个 Session 上的**所有**查询都会被记下来，不用在每个调用点插桩
  （漏一个调用点就等于漏一段证据）；
* 测试和结构测试都不受影响 —— 不装这个包装，一切照旧。

## 线程

``Frame`` 的查询发生在**引擎线程**（或抓帧线程），而界面线程要读日志 ——
所以 :class:`RecognitionRecorder` 内部加锁，并且对外只暴露：
``install()``（装配期调一次）和 :meth:`RecognitionRecorder.entries`（拿快照）。
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, Any

from ..utils.logging import get_logger

if TYPE_CHECKING:
    from ..types import Region
    from .vision import Matcher, TextReader

log = get_logger("vision.recorder")

__all__ = [
    "MatchRecord",
    "RecognitionRecorder",
    "draw_annotations",
    "frame_context",
    "set_frame_context",
]

#: 存图文件名的前缀。**只清理带这个前缀的文件** —— 手工截的图不能碰。
FRAME_PREFIX = "match_"

#: 画框用的颜色（BGR，因为底层是 OpenCV）。红框是主色。
COLOR_HIT = (60, 60, 235)  # 红：命中
COLOR_MISS = (0, 165, 255)  # 橙：没命中（也画出来，"没中"是同样重要的信息）
COLOR_ROI = (200, 140, 60)  # 蓝：搜索范围
COLOR_TEXT = (255, 255, 255)

#: 当前正在被查询的帧的上下文：``(origin_x, origin_y, frame_id)``。
#:
#: 为什么要有这个东西：``Matcher.match`` 只拿得到一个**图像数组**，它不知道
#: 这张图在源分辨率里的位置、也不知道自己属于哪一帧 —— 而 ROI 裁剪过的帧，
#: 框必须加上原点才能画对地方，同帧的多条记录还得攒成一张图。
#: 所以由 ``Frame`` 在发起查询前把它记在这里，包装层读。
#:
#: 用 ``ContextVar`` 而不是全局变量：它**每线程独立**，抓帧线程和引擎线程
#: 各查各的不会互相串（全局变量会串）。也不用加进 Matcher 的签名 ——
#: 那等于让算法知道"记录"这件事存在，职责就混了。
_frame_context: ContextVar[tuple[int, int, int]] = ContextVar(
    "gamebot_frame_context", default=(0, 0, -1)
)


def set_frame_context(x: int, y: int, frame_id: int) -> None:
    """由 ``Frame`` 在查询前调用：声明"这张图的原点、以及它属于哪一帧"。"""
    _frame_context.set((x, y, frame_id))


def frame_context() -> tuple[int, int, int]:
    """``(origin_x, origin_y, frame_id)``。查不到时是 ``(0, 0, -1)``。"""
    return _frame_context.get()


def _with_path(record: MatchRecord, path: str) -> MatchRecord:
    """补一个落盘路径的同构新记录（frozen dataclass 不能就地改）。"""
    return MatchRecord(
        seq=record.seq,
        at=record.at,
        kind=record.kind,
        target=record.target,
        searched=record.searched,
        score=record.score,
        hit=record.hit,
        found=record.found,
        point=record.point,
        box=record.box,
        confidence=record.confidence,
        frame_path=path,
        extra=record.extra,
    )


@dataclass(frozen=True, slots=True)
class MatchRecord:
    """一次识图 / OCR 尝试的记录。"""

    seq: int
    at: float
    kind: str
    """``image`` | ``all_images`` | ``compare`` | ``ocr`` | ``ocr_read``"""

    target: str
    """模板名或要找的文字。"""

    searched: tuple[int, int, int, int] | None
    """搜索范围（源坐标）。None = 整帧。"""

    score: float | None
    hit: bool
    found: int
    """命中几个（单点匹配是 0/1）。"""

    point: tuple[int, int] | None
    box: tuple[int, int, int, int] | None
    """画出来的那个框（命中框，没命中就是搜索范围）。"""

    confidence: float = 0.0
    frame_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.target}  {self.score:.3f}" if self.score is not None else self.target

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": round(self.at, 4),
            "kind": self.kind,
            "target": self.target,
            "searched": self.searched,
            "score": None if self.score is None else round(self.score, 4),
            "hit": self.hit,
            "found": self.found,
            "point": self.point,
            "box": self.box,
            "confidence": self.confidence,
            "frame": self.frame_path,
            "extra": self.extra,
        }

    def __str__(self) -> str:
        where = "整帧" if self.searched is None else f"ROI{self.searched}"
        verdict = "命中" if self.hit else "未命中"
        score = "—" if self.score is None else f"{self.score:.3f}"
        point = f" @{self.point}" if self.point else ""
        return f"[{self.kind}] {self.target}  {verdict}  分数 {score}{point}  搜 {where}"


def draw_annotations(
    image: Any,
    records: Sequence[MatchRecord],
    *,
    title: str = "",
) -> Any:
    """在图上把每次匹配的框画出来。返回**新图**，不改原图。

    颜色语义（和日志里的措辞一致，别改乱）：

    * **红框** —— 命中。框的位置就是「它认到的是哪一块」；
    * **橙框** —— 没命中，框的是它**搜过的那块**。看不到这个就没法判断
      "圈对了但阈值高了"还是"圈错了"；
    * **蓝框** —— 搜索范围（ROI）。它比命中框大一圈时，能一眼看出 ROI 收得对不对；
    * **小字** —— 模板名 + 分数，标在框的左上角。

    :param image: BGR 数组（源分辨率）。会被复制，调用方可以继续用原图。
    """
    try:
        import cv2  # noqa: F401 - 只是确认装了；下面用的都是本模块的 _rect/_label
    except ImportError:  # pragma: no cover - 没装 opencv 时不该走到这里
        return image

    canvas = image.copy()
    height, width = canvas.shape[:2]

    # 只画最近几条：同一帧上可能查了十来次，全画上去会糊成一片
    for record in records[-8:]:
        if record.searched is not None:
            x, y, w, h = record.searched
            _rect(canvas, (x, y, w, h), COLOR_ROI, 1)

        if record.box is None:
            continue
        color = COLOR_HIT if record.hit else COLOR_MISS
        _rect(canvas, record.box, color, 2)

        label = f"{record.target} {'' if record.score is None else f'{record.score:.2f}'}"
        _label(canvas, label, record.box, color, width, height)

    if title:
        _label(canvas, title, (4, 4, 1, 1), COLOR_TEXT, width, height, offset=0)
    return canvas


def _rect(canvas: Any, box: tuple[int, int, int, int], color: tuple[int, int, int], w: int) -> None:
    import cv2

    x, y, bw, bh = box
    cv2.rectangle(canvas, (x, y), (x + bw, y + bh), color, w)


def _label(
    canvas: Any,
    text: str,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    width: int,
    height: int,
    *,
    offset: int = 14,
) -> None:
    """在框左上角写一行小字。字总要垫个底，不然压在浅色画面上看不清。"""
    import cv2

    x, y = box[0], box[1]
    ty = max(12, y - offset)
    scale, thickness = 0.5, 1
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    tx = min(max(0, x), max(0, width - tw - 4))
    cv2.rectangle(canvas, (tx, ty - th - 3), (tx + tw + 4, ty + 3), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        text,
        (tx + 2, ty),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


class RecognitionRecorder:
    """包在 Matcher / TextReader 外面，记录每次匹配并落盘带框的图。

    :param directory: 存图目录；None = 只记日志不存图。
    :param keep: 最多留几张图（旧的自动删）。
    :param history: 内存里保留最近多少条记录。
    :param on_record: 每记一条就回调一次（界面用它刷新日志）。
        **在查询线程里同步调用** —— 实现要快，别在那里刷控件。
    """

    def __init__(
        self,
        *,
        directory: Path | None = None,
        keep: int = 20,
        history: int = 300,
        on_record: Callable[[MatchRecord], None] | None = None,
    ) -> None:
        self.directory = directory
        self.keep = max(0, keep)
        self._entries: deque[MatchRecord] = deque(maxlen=max(1, history))
        self._lock = Lock()
        self._seq = itertools.count(1)
        self._counter = 0
        self._on_record = on_record
        self.saved_frames = 0
        self.pruned = 0
        #: 当前正在累积的那一帧（帧号 + 它的图 + 它的全部记录）
        self._pending: tuple[int, Any, list[MatchRecord]] | None = None

    # ------------------------------------------------------------------ #
    # 装配
    # ------------------------------------------------------------------ #
    def wrap_matcher(self, matcher: Matcher | None) -> Matcher | None:
        """把 Matcher 包一层。已经是包装的就原样返回（别套两层，会记两遍）。"""
        if matcher is None or isinstance(matcher, _MatcherTap):
            return matcher
        return _MatcherTap(matcher, self)

    def wrap_reader(self, reader: TextReader | None) -> TextReader | None:
        if reader is None or isinstance(reader, _ReaderTap):
            return reader
        return _ReaderTap(reader, self)

    # ------------------------------------------------------------------ #
    # 记录
    # ------------------------------------------------------------------ #
    def record_match(
        self,
        *,
        kind: str,
        target: str,
        image: Any,
        searched: Region | None,
        results: Sequence[Any],
        confidence: float,
        frame_id: int = -1,
    ) -> None:
        """记一次模板匹配。``results`` 是 ``MatchResult`` 列表（可能为空）。

        :param frame_id: 这一帧的编号。**同一个 ``frame_id`` 的记录会攒在一起**，
            等下一帧（或 :meth:`flush`）时**只存一张图**，把所有框都画在上面 ——
            否则一帧里查 10 次就存 10 张几乎一样的图，20 张上限两帧就满了。
            框的坐标换算成源坐标由 :data:`_frame_origin` 提供（见它的说明）。
        """
        self._emit(
            kind=kind,
            target=target,
            image=image,
            searched=searched,
            confidence=confidence,
            points=[getattr(r, "point", None) for r in results],
            boxes=[getattr(r, "region", None) for r in results],
            scores=[getattr(r, "score", None) for r in results],
            frame_id=frame_id,
        )

    def record_compare(
        self,
        *,
        target: str,
        image: Any,
        searched: Region | None,
        score: float | None,
        confidence: float,
        frame_id: int = -1,
    ) -> None:
        hit = score is not None and score >= confidence
        self._emit(
            kind="compare",
            target=target,
            image=image,
            searched=searched,
            confidence=confidence,
            points=[],
            boxes=[searched] if searched is not None else [],
            scores=[score],
            hit_override=hit,
            frame_id=frame_id,
        )

    def record_text(
        self,
        *,
        kind: str,
        text: str,
        image: Any,
        searched: Region | None,
        boxes: Sequence[Any],
        confidence: float,
        frame_id: int = -1,
    ) -> None:
        self._emit(
            kind=kind,
            target=text,
            image=image,
            searched=searched,
            confidence=confidence,
            points=[getattr(b, "point", None) for b in boxes],
            boxes=[getattr(b, "region", None) for b in boxes],
            scores=[getattr(b, "score", None) for b in boxes],
            frame_id=frame_id,
        )

    def _emit(
        self,
        *,
        kind: str,
        target: str,
        image: Any,
        searched: Region | None,
        confidence: float,
        points: Sequence[Any],
        boxes: Sequence[Any],
        scores: Sequence[Any],
        hit_override: bool | None = None,
        frame_id: int = -1,
    ) -> None:
        scores = [s for s in scores if isinstance(s, (int, float))]
        best = max(scores) if scores else None
        hit = hit_override if hit_override is not None else bool(points or boxes)

        base_x, base_y, ctx_frame = frame_context()
        if frame_id < 0:
            frame_id = ctx_frame

        def to_source(region: Any) -> tuple[int, int, int, int] | None:
            if region is None:
                return None
            return (region.x + base_x, region.y + base_y, region.w, region.h)

        point = None
        if points and points[0] is not None:
            point = (points[0].x + base_x, points[0].y + base_y)

        box = to_source(boxes[0]) if boxes else to_source(searched)

        with self._lock:
            seq = next(self._seq)
        record = MatchRecord(
            seq=seq,
            at=perf_counter(),
            kind=kind,
            target=target,
            searched=to_source(searched),
            score=best,
            hit=hit,
            found=len(points) or len(boxes),
            point=point,
            box=box,
            confidence=float(confidence),
        )

        with self._lock:
            self._entries.append(record)

        log.debug("识图 %s", record)
        if self._on_record is not None:
            try:
                self._on_record(record)
            except Exception as exc:  # 观察者的问题不该影响识图
                log.warning("识别记录回调失败: %s", exc)

        self._accumulate(frame_id, image, record)

    # ------------------------------------------------------------------ #
    # 存图：一帧一张
    # ------------------------------------------------------------------ #
    def _accumulate(self, frame_id: int, image: Any, record: MatchRecord) -> None:
        """把记录攒到当前帧上；换帧了就先落盘上一帧。

        **一帧只存一张图**，所有框画在一起。这样"这一帧它认了什么"是一张
        能看懂的图，而不是十几张只差一个框的图。
        """
        if self.directory is None or self.keep <= 0:
            return
        with self._lock:
            pending = self._pending
            if pending is not None and pending[0] == frame_id:
                pending[2].append(record)
                return
            self._pending = (frame_id, image, [record])
        # 换帧了：把上一帧落盘（锁外做 IO）
        if pending is not None:
            self._flush_pending(pending)

    def flush(self) -> None:
        """把当前累积的那一帧落盘。运行结束、或只想立刻看到时调它。"""
        with self._lock:
            pending = self._pending
            self._pending = None
        if pending is not None:
            self._flush_pending(pending)

    def annotate_now(self, frame: Any, *, reason: str = "手动抓帧") -> str:
        """立刻把**当前帧**连同它已经记下的框存一张图。

        用途是界面上的「抓一张」：不跑脚本，也想看一眼"现在这个画面，
        按上次那套查询会画成什么样"。

        先 :meth:`flush` 再存 —— 否则这一帧的框还攒在待落盘队列里，
        抓出来的图会是空的。

        :return: 存下来的路径；没开记录或存失败时是空串。
        """
        self.flush()
        if self.directory is None or self.keep <= 0:
            return ""
        with self._lock:
            frame_id = self._pending[0] if self._pending else -1
            recent = [r for r in self._entries if r.frame_path == ""][-8:]
        records = list(recent)
        if not records:
            records = [
                MatchRecord(
                    seq=0,
                    at=perf_counter(),
                    kind="manual",
                    target=reason,
                    searched=None,
                    score=None,
                    hit=False,
                    found=0,
                    point=None,
                    box=None,
                )
            ]
        _ = frame_id
        return self._save(frame, records)

    def _flush_pending(self, pending: tuple[int, Any, list[MatchRecord]]) -> None:
        _frame_id, image, records = pending
        if not records:
            return
        path = self._save(image, records)
        if not path:
            return
        # 把落盘路径补回到这几条记录上（界面靠它显示缩略图）
        with self._lock:
            updated = [
                record if record.frame_path else _with_path(record, path)
                for record in self._entries
            ]
            self._entries.clear()
            self._entries.extend(updated)

    def _save(self, image: Any, records: Sequence[MatchRecord]) -> str:
        """把带框的图存下来。**存图失败绝不影响识图** —— 返回空串就好。"""
        if self.directory is None or self.keep <= 0:
            return ""
        try:
            import cv2

            self.directory.mkdir(parents=True, exist_ok=True)
            self._counter += 1
            path = self.directory / f"{FRAME_PREFIX}{self._counter:05d}.png"
            annotated = draw_annotations(image, records, title=records[-1].label)
            cv2.imwrite(str(path), annotated)
            self.saved_frames += 1
            self._prune()
            return str(path)
        except Exception as exc:
            log.debug("存识别帧失败（不影响识图）: %s", exc)
            return ""

    def _prune(self) -> None:
        """删掉超出上限的旧帧。

        **只删带 ``FRAME_PREFIX`` 的文件**：手工截的图（``gamebot capture``、
        调试脚本、界面快照）混在同一个目录里，误删了才是最烦的。
        """
        if self.directory is None or self.keep <= 0:
            return
        ours = sorted(
            self.directory.glob(f"{FRAME_PREFIX}*.png"),
            key=lambda p: p.stat().st_mtime,
        )
        for stale in ours[: max(0, len(ours) - self.keep)]:
            try:
                stale.unlink()
                self.pruned += 1
            except OSError:
                pass

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def entries(self, limit: int = 0) -> list[MatchRecord]:
        """最近若干条记录（新的在后）。界面线程用它刷日志。"""
        with self._lock:
            items = list(self._entries)
        return items[-limit:] if limit > 0 else items

    def latest_frames(self) -> list[str]:
        """现存带框图标的路径，**新的在前**（界面用它列"最近看过的图"）。"""
        if self.directory is None:
            return []
        try:
            files = list(self.directory.glob(f"{FRAME_PREFIX}*.png"))
        except OSError:
            return []
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [str(p) for p in files]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __repr__(self) -> str:
        return (
            f"RecognitionRecorder({len(self)} 条记录, 存图 {self.saved_frames} 张, "
            f"上限 {self.keep})"
        )


# --------------------------------------------------------------------------- #
# 包装
# --------------------------------------------------------------------------- #
class _MatcherTap:
    """``Matcher`` 的透明包装：先记录，再交给真正的实现。

    透明是关键 —— 它不改变任何行为（照样返回原来的结果、照样抛原来的异常），
    只是路过时记一笔。
    """

    def __init__(self, inner: Matcher, recorder: RecognitionRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def match(self, image: Any, template: str, **kwargs: Any) -> Any:
        result = self._inner.match(image, template, **kwargs)
        self._recorder.record_match(
            kind="image",
            target=template,
            image=image,
            searched=kwargs.get("region"),
            results=[result] if result is not None else [],
            confidence=kwargs.get("confidence", 0.9),
            frame_id=frame_context()[2],
        )
        return result

    def match_all(self, image: Any, template: str, **kwargs: Any) -> Any:
        results = self._inner.match_all(image, template, **kwargs)
        self._recorder.record_match(
            kind="all_images",
            target=template,
            image=image,
            searched=kwargs.get("region"),
            results=results,
            confidence=kwargs.get("confidence", 0.9),
            frame_id=frame_context()[2],
        )
        return results

    def compare(self, image: Any, region: Any, template: str, confidence: float = 0.9) -> Any:
        score = self._inner.compare(image, region, template, confidence)
        self._recorder.record_compare(
            target=template,
            image=image,
            searched=region,
            score=score,
            confidence=confidence,
        )
        return score

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _ReaderTap:
    """``TextReader`` 的透明包装（OCR）。"""

    def __init__(self, inner: TextReader, recorder: RecognitionRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def locate(self, image: Any, text: str, **kwargs: Any) -> Any:
        boxes = self._inner.locate(image, text, **kwargs)
        self._recorder.record_text(
            kind="ocr",
            text=text,
            image=image,
            searched=kwargs.get("region"),
            boxes=boxes,
            confidence=kwargs.get("confidence", 0.8),
            frame_id=frame_context()[2],
        )
        return boxes

    def read(self, image: Any, **kwargs: Any) -> Any:
        raw = self._inner.read(image, **kwargs)
        self._recorder.record_text(
            kind="ocr_read",
            text=str(raw or ""),
            image=image,
            searched=kwargs.get("region"),
            boxes=[],
            confidence=kwargs.get("confidence", 0.8),
            frame_id=frame_context()[2],
        )
        return raw

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
