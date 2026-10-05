"""识图记录器测试：**每一次匹配都被记下来、并且框画在对的地方**。

这块是"看不到就是没证据"的部分 —— 用户反馈实时画面没用，能看出问题的是
"它认到的是哪一块"，所以记录的正确性直接决定调脚本的效率。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gamebot.atomic.backends.fake import build_fake_backends
from gamebot.atomic.session import BaseSession
from gamebot.types import Point, Region
from gamebot.vision.recorder import (
    FRAME_PREFIX,
    MatchRecord,
    RecognitionRecorder,
    draw_annotations,
    set_frame_context,
)

from .conftest import FakeMatcher, FakeReader


def _session(recorder: RecognitionRecorder, matches: dict | None = None):
    """造一个装了记录器的假 Session。"""
    matcher = recorder.wrap_matcher(FakeMatcher(matches=matches or {}))
    return BaseSession(
        build_fake_backends(size=(640, 360)),
        matcher=matcher,
        reader=recorder.wrap_reader(FakeReader()),
    )


# --------------------------------------------------------------------------- #
# 记录
# --------------------------------------------------------------------------- #
class TestRecording:
    def test_hit_is_recorded_with_point_and_score(self):
        recorder = RecognitionRecorder(directory=None)
        frame = _session(recorder, {"a.png": (Point(100, 50), 0.98)}).capture()

        assert frame.find_image("a.png").ok

        (record,) = recorder.entries()
        assert record.kind == "image"
        assert record.target == "a.png"
        assert record.hit is True
        assert record.score == pytest.approx(0.98)
        assert record.point == (100, 50)

    def test_miss_is_recorded_too(self):
        """没命中**也要记** —— "它没找到"和"它没查"是两件完全不同的事。"""
        recorder = RecognitionRecorder(directory=None)
        frame = _session(recorder).capture()

        assert not frame.find_image("nope.png").ok

        (record,) = recorder.entries()
        assert record.hit is False
        assert record.target == "nope.png"
        assert record.score is None

    def test_roi_is_recorded_and_offset_by_frame_origin(self):
        """ROI 裁剪过的帧：框必须加上帧原点，否则画出来整体偏一块。"""
        recorder = RecognitionRecorder(directory=None)
        frame = _session(recorder, {"a.png": (Point(30, 20), 0.95)}).capture()
        cropped = frame.crop(Region(200, 100, 300, 200))

        assert cropped.find_image("a.png", region=Region(210, 110, 80, 60)).ok

        (record,) = recorder.entries()
        # 搜索范围：帧内 (10,10) + 原点 (200,100) = 源坐标 (210,110)
        assert record.searched == (210, 110, 80, 60)
        # 命中点：假匹配器返回帧内 (30,20)，加上原点 = (230,120)
        assert record.point == (230, 120)

    def test_compare_records_score_and_verdict(self):
        recorder = RecognitionRecorder(directory=None)

        class _Matcher(FakeMatcher):
            def compare(self, image, region, template, confidence=0.9):
                return 0.5

        session = BaseSession(
            build_fake_backends(size=(640, 360)),
            matcher=recorder.wrap_matcher(_Matcher()),
        )
        session.matcher.compare(np.zeros((10, 10, 3), np.uint8), Region(0, 0, 10, 10), "t.png")

        (record,) = recorder.entries()
        assert record.kind == "compare"
        assert record.score == pytest.approx(0.5)
        # 0.5 < 默认 0.9 -> 算未命中
        assert record.hit is False

    def test_ocr_box_is_recorded(self):
        recorder = RecognitionRecorder(directory=None)
        frame = _session(recorder).capture()

        frame.find_text("开始")

        (record,) = recorder.entries()
        assert record.kind == "ocr"
        assert record.target == "开始"

    def test_history_is_bounded(self):
        """只留最近的：调脚本要看的是"刚才那几次"，不是三个月前的。"""
        recorder = RecognitionRecorder(directory=None, history=5)
        frame = _session(recorder).capture()
        for index in range(20):
            frame.find_image(f"t{index}.png")

        assert len(recorder) == 5
        assert [r.target for r in recorder.entries()] == [f"t{i}.png" for i in range(15, 20)]


# --------------------------------------------------------------------------- #
# 存图
# --------------------------------------------------------------------------- #
class TestFrames:
    def test_one_image_per_frame_not_per_match(self, tmp_path):
        """同一帧查 3 次只存 1 张图。

        否则一帧里查十来个模板就存十来张几乎一样的图，20 张上限两帧就满了。

        注意用**三个不同**的模板名：同参数的查询在一帧内会命中帧缓存
        （``Frame.cached``），根本不会走到匹配器，也就不会产生记录。
        """
        recorder = RecognitionRecorder(directory=tmp_path, keep=20)
        session = _session(recorder, {"a.png": (Point(1, 1), 0.99)})
        frame = session.capture()
        for name in ("a.png", "b.png", "c.png"):
            frame.find_image(name)
        recorder.flush()

        images = list(tmp_path.glob(f"{FRAME_PREFIX}*.png"))
        assert len(images) == 1
        assert len(recorder.entries()) == 3

    def test_next_frame_flushes_the_previous_one(self, tmp_path):
        recorder = RecognitionRecorder(directory=tmp_path, keep=20)
        session = _session(recorder, {"a.png": (Point(1, 1), 0.99)})

        session.capture().find_image("a.png")
        session.capture().find_image("a.png")
        session.capture().find_image("a.png")

        # 前两帧已经因为"换帧"落盘，第三帧还在攒着
        assert len(list(tmp_path.glob(f"{FRAME_PREFIX}*.png"))) == 2
        recorder.flush()
        assert len(list(tmp_path.glob(f"{FRAME_PREFIX}*.png"))) == 3

    def test_keep_limit_deletes_the_oldest(self, tmp_path):
        """最多留存 N 张 —— 用户明确要的上限。"""
        recorder = RecognitionRecorder(directory=tmp_path, keep=3)
        session = _session(recorder, {"a.png": (Point(1, 1), 0.99)})
        for _ in range(8):
            session.capture().find_image("a.png")
        recorder.flush()

        images = sorted(tmp_path.glob(f"{FRAME_PREFIX}*.png"))
        assert len(images) == 3
        # 留的是新的那三张（文件名前缀递增，所以序号最大的三个）
        assert [p.name for p in images] == [
            f"{FRAME_PREFIX}00006.png",
            f"{FRAME_PREFIX}00007.png",
            f"{FRAME_PREFIX}00008.png",
        ]

    def test_prune_never_touches_other_files(self, tmp_path):
        """**只删自己写的** —— 手工截的图和别的调试产物混在同一个目录里。"""
        keep_me = tmp_path / "manual_shot.png"
        keep_me.write_bytes(b"x")
        other = tmp_path / "frame_something.png"
        other.write_bytes(b"x")

        recorder = RecognitionRecorder(directory=tmp_path, keep=1)
        session = _session(recorder, {"a.png": (Point(1, 1), 0.99)})
        for _ in range(4):
            session.capture().find_image("a.png")
        recorder.flush()

        assert keep_me.is_file()
        assert other.is_file()
        assert len(list(tmp_path.glob(f"{FRAME_PREFIX}*.png"))) == 1

    def test_recording_disabled_writes_nothing(self, tmp_path):
        recorder = RecognitionRecorder(directory=tmp_path, keep=0)
        frame = _session(recorder, {"a.png": (Point(1, 1), 0.99)}).capture()
        frame.find_image("a.png")
        recorder.flush()

        assert list(tmp_path.glob("*.png")) == []
        # 但日志照样记（不存图不等于不记）
        assert len(recorder.entries()) == 1

    # ------------------------------------------------------------------ #
    # 「抓一张」和编号
    # ------------------------------------------------------------------ #
    def test_annotate_now_writes_a_frame(self, tmp_path):
        """「抓一张」必须真的存下一条记录。

        ## 这里踩过的坑

        ``annotate_now`` 一度把 ``Frame`` **对象**直接传给 ``_save``，而底下
        画框用的是 cv2、要的是 numpy 数组 —— 于是 ``image.copy()`` 抛异常，
        被 ``_save`` 的兜底吞掉、只留一条 debug 日志。
        表现是：点「抓一张」，弹一句"抓到了帧，但没存图（vision.record 关了？）"
        —— 提示指向配置，而真正的原因是类型传错了。**非常难查**。

        所以这条用例只断言"它返回了路径"，不管别的。
        """
        recorder = RecognitionRecorder(directory=tmp_path, keep=20)
        frame = _session(recorder, {"a.png": (Point(1, 1), 0.99)}).capture()

        path = recorder.annotate_now(frame, reason="测试")

        assert path, "annotate_now 应当返回存下来的路径"
        assert Path(path).is_file()
        assert Path(path).stat().st_size > 0

    def test_annotate_now_works_with_no_queries_at_all(self, tmp_path):
        """这一帧什么都没查也要存一张（让人看到当前画面），只是没框可画。"""
        recorder = RecognitionRecorder(directory=tmp_path, keep=20)
        frame = _session(recorder).capture()

        path = recorder.annotate_now(frame)

        assert path and Path(path).is_file()

    def test_annotate_now_does_not_modify_the_frame(self, tmp_path):
        """画框不能改原图（下面的记录器还在用同一帧）。"""
        recorder = RecognitionRecorder(directory=tmp_path, keep=20)
        frame = _session(recorder, {"a.png": (Point(1, 1), 0.99)}).capture()
        before = frame.to_numpy().copy()

        recorder.annotate_now(frame)

        assert (frame.to_numpy() == before).all()

    def test_counter_resumes_from_existing_files(self, tmp_path):
        """新记录器要接着磁盘上已有的编号 —— **否则会覆盖上一次会话的图**。

        记录器是每次「开始」/「抓一张」新建一个的。编号从 0 起的话，第二次
        会话就从 ``match_00001.png`` 开始写、把还在的文件覆盖掉，
        于是"最多留 20 张"这个留存机制形同虚设（实测撞过：磁盘上同时有
        00001/00002 和 00026~00043，编号回退一大截）。
        """
        for index in (1, 2, 26, 43):
            (tmp_path / f"{FRAME_PREFIX}{index:05d}.png").write_bytes(b"x")

        recorder = RecognitionRecorder(directory=tmp_path, keep=20)

        assert recorder._counter == 43

    def test_counter_starts_at_zero_on_empty_directory(self, tmp_path):
        assert RecognitionRecorder(directory=tmp_path, keep=20)._counter == 0

    def test_two_sessions_do_not_overwrite_each_other(self, tmp_path):
        """两次会话写的文件名不能撞 —— 这是上面那条的实际后果。"""
        first = RecognitionRecorder(directory=tmp_path, keep=20)
        frame = _session(first, {"a.png": (Point(1, 1), 0.99)}).capture()
        frame.find_image("a.png")
        first.flush()

        second = RecognitionRecorder(directory=tmp_path, keep=20)
        frame2 = _session(second, {"a.png": (Point(1, 1), 0.99)}).capture()
        frame2.find_image("a.png")
        second.flush()

        files = sorted(p.name for p in tmp_path.glob(f"{FRAME_PREFIX}*.png"))
        assert len(files) == 2, f"两次会话应该留下两个文件，实际 {files}"

    def test_counter_ignores_files_that_are_not_ours(self, tmp_path):
        """别的文件（手工截图、失败帧）不该影响编号。"""
        (tmp_path / "manual_00999.png").write_bytes(b"x")
        (tmp_path / "fail_t9_1_x.png").write_bytes(b"x")
        (tmp_path / f"{FRAME_PREFIX}00007.png").write_bytes(b"x")

        assert RecognitionRecorder(directory=tmp_path, keep=20)._counter == 7

    def test_counter_tolerates_odd_names(self, tmp_path):
        """前缀对但编号不是数字的文件（手工改过名）忽略掉，不该炸。"""
        (tmp_path / f"{FRAME_PREFIX}abc.png").write_bytes(b"x")
        (tmp_path / f"{FRAME_PREFIX}00003.png").write_bytes(b"x")

        assert RecognitionRecorder(directory=tmp_path, keep=20)._counter == 3

    def test_save_failure_does_not_break_matching(self, tmp_path, monkeypatch):
        """存图失败绝不能影响识图 —— 记录是旁路。"""
        recorder = RecognitionRecorder(directory=tmp_path, keep=5)
        frame = _session(recorder, {"a.png": (Point(1, 1), 0.99)}).capture()

        import cv2

        def boom(*args, **kwargs):
            raise OSError("磁盘满了")

        monkeypatch.setattr(cv2, "imwrite", boom)

        assert frame.find_image("a.png").ok  # 照样命中
        recorder.flush()
        assert len(recorder.entries()) == 1

    def test_wrapping_twice_does_not_double_record(self):
        """重复 install 会包装套包装 -> 每次匹配记两遍。这里钉住幂等。"""
        recorder = RecognitionRecorder(directory=None)
        inner = FakeMatcher(matches={"a.png": (Point(1, 1), 0.99)})
        once = recorder.wrap_matcher(inner)
        twice = recorder.wrap_matcher(once)
        assert twice is once

        session = BaseSession(build_fake_backends(size=(640, 360)), matcher=twice)
        session.capture().find_image("a.png")
        assert len(recorder.entries()) == 1


# --------------------------------------------------------------------------- #
# 画框
# --------------------------------------------------------------------------- #
class TestAnnotation:
    def test_draws_red_for_hit_orange_for_miss_blue_for_roi(self):
        image = np.zeros((200, 300, 3), dtype=np.uint8)
        records = [
            MatchRecord(
                seq=1, at=0.0, kind="image", target="hit.png", searched=(10, 10, 120, 60),
                score=0.97, hit=True, found=1, point=(60, 40), box=(50, 30, 20, 20),
            ),
            MatchRecord(
                seq=2, at=0.0, kind="image", target="miss.png", searched=(160, 100, 100, 60),
                score=0.4, hit=False, found=0, point=None, box=(160, 100, 20, 20),
            ),
        ]

        out = draw_annotations(image, records)
        blue = out[:, :, 0].astype(int)
        green = out[:, :, 1].astype(int)
        red = out[:, :, 2].astype(int)

        # 红框（命中）：B 低、R 高
        assert ((red > 180) & (blue < 120)).sum() > 100
        # 橙框（未命中）：R 高、G 中、B 低
        assert ((red > 180) & (green > 120) & (blue < 120)).sum() > 20
        # 蓝框（ROI）：B 高
        assert ((blue > 120) & (red < 120)).sum() > 100

    def test_does_not_modify_the_original_image(self):
        image = np.zeros((50, 50, 3), dtype=np.uint8)
        draw_annotations(
            image,
            [MatchRecord(1, 0.0, "image", "a.png", None, 1.0, True, 1, (1, 1), (0, 0, 9, 9))],
        )
        assert (image == 0).all()

    def test_empty_records_returns_a_copy(self):
        image = np.full((10, 10, 3), 7, dtype=np.uint8)
        out = draw_annotations(image, [])
        assert (out == 7).all()
        assert out is not image


class TestSharedDirectory:
    """识图记录与失败帧**躺在同一个目录里**，各自只删自己的。

    这是最容易出事的地方：两套留存机制共用一个目录，只要有一套的清理
    不带 pattern，另一套的文件就会被连带删掉。而且它们都不报错 ——
    等你发现"失败帧怎么没了"的时候已经查不出来了。
    """

    def _recorder(self, tmp_path, keep=3):
        recorder = RecognitionRecorder(directory=tmp_path, keep=keep)
        session = _session(recorder, {"a.png": (Point(1, 1), 0.99)})
        for _ in range(10):
            session.capture().find_image("a.png")
        recorder.flush()
        return recorder

    def test_prune_old_only_touches_the_pattern(self, tmp_path):
        from gamebot.vision.recorder import prune_old

        for name in ("match_1.png", "match_2.png", "fail_1.png", "fail_2.png", "manual.png"):
            (tmp_path / name).write_bytes(b"x")

        assert prune_old(tmp_path, "match_*.png", 1) == 1
        left = sorted(p.name for p in tmp_path.glob("*.png"))
        assert left == ["fail_1.png", "fail_2.png", "manual.png", "match_2.png"]

    def test_failure_frames_survive_match_pruning(self, tmp_path):
        """识图记录清理时，失败帧和手工截图都得活着。"""
        (tmp_path / "fail_9.png").write_bytes(b"x")
        (tmp_path / "mine.png").write_bytes(b"x")

        self._recorder(tmp_path, keep=2)

        assert (tmp_path / "fail_9.png").is_file()
        assert (tmp_path / "mine.png").is_file()
        assert len(list(tmp_path.glob("match_*.png"))) == 2

    def test_match_frames_survive_failure_pruning(self, tmp_path):
        """反过来也一样。"""
        from gamebot.vision.recorder import prune_old

        self._recorder(tmp_path, keep=2)
        before = sorted(p.name for p in tmp_path.glob("match_*.png"))
        for index in range(10):
            (tmp_path / f"fail_{index}.png").write_bytes(b"x")

        prune_old(tmp_path, "fail_*.png", 2)

        assert sorted(p.name for p in tmp_path.glob("match_*.png")) == before
        assert len(list(tmp_path.glob("fail_*.png"))) == 2


class TestFrameContext:
    def test_frame_marks_its_own_origin_and_id(self):
        """帧在查询前把"原点 + 帧号"写给记录层。

        **不是**测默认值：``ContextVar`` 在同一线程里会一直是上次设的值
        （它本来就该这样 —— 它的作用是"当前这张图的上下文"）。所以这里
        显式设一个可辨认的值再读回来。
        """
        from gamebot.vision.recorder import frame_context

        set_frame_context(12, 34, 7)
        assert frame_context() == (12, 34, 7)

    def test_querying_a_frame_sets_the_context(self):
        """真的查一次，上下文就被那一帧填上了。"""
        from gamebot.vision.recorder import frame_context

        recorder = RecognitionRecorder(directory=None)
        session = _session(recorder, {"a.png": (Point(5, 6), 0.99)})
        frame = session.capture()
        frame.find_image("a.png")

        x, y, frame_id = frame_context()
        assert (x, y) == (0, 0)  # 整帧的原点就是 (0,0)
        assert frame_id == frame.frame_id
