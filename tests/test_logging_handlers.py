"""日志给界面用的部分：环形缓冲、回调桥、handlers 的挂/摘。

这些不是"框架内部实现细节"—— 界面完全依赖它们的三个性质，
所以每一条都值得钉住：

1. 环形缓冲能事后补看（界面比引擎晚开）；
2. 挂上去的 handler 不会被 ``setup_logging`` 冲掉（界面可能先挂、后装配日志）；
3. 能摘干净（不摘的话窗口关了对象也不释放）。
"""

from __future__ import annotations

import logging

import pytest

from gamebot.utils.logging import (
    CallbackHandler,
    RingBufferHandler,
    attach_handlers,
    detach_handlers,
    get_logger,
    setup_logging,
)


@pytest.fixture
def logger() -> logging.Logger:
    """一个干净的 logger，测完把 handler 收掉。"""
    log = logging.getLogger("gamebot.test.logging")
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.propagate = False
    yield log
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()


class TestRingBuffer:
    def test_keeps_records_in_order(self, logger: logging.Logger) -> None:
        buffer = RingBufferHandler(10)
        logger.addHandler(buffer)
        for index in range(3):
            logger.info("第 %d 条", index)
        messages = [r.getMessage() for r in buffer.snapshot()]
        assert messages == ["第 0 条", "第 1 条", "第 2 条"]

    def test_drops_the_oldest_when_full(self, logger: logging.Logger) -> None:
        buffer = RingBufferHandler(3)
        logger.addHandler(buffer)
        for index in range(5):
            logger.info("第 %d 条", index)
        messages = [r.getMessage() for r in buffer.snapshot()]
        assert messages == ["第 2 条", "第 3 条", "第 4 条"]

    def test_snapshot_can_filter_by_level(self, logger: logging.Logger) -> None:
        buffer = RingBufferHandler(10)
        logger.addHandler(buffer)
        logger.debug("细的")
        logger.warning("粗的")
        assert [r.levelno for r in buffer.snapshot(level=logging.INFO)] == [logging.WARNING]

    def test_clear(self, logger: logging.Logger) -> None:
        buffer = RingBufferHandler(10)
        logger.addHandler(buffer)
        logger.info("一")
        buffer.clear()
        assert buffer.snapshot() == []

    def test_maxlen_is_at_least_one(self) -> None:
        assert RingBufferHandler(0).records.maxlen == 1


class TestCallbackHandler:
    def test_calls_back_for_each_record(self, logger: logging.Logger) -> None:
        seen: list[str] = []
        logger.addHandler(CallbackHandler(seen.append))
        logger.info("a")
        logger.info("b")
        assert [r.getMessage() for r in seen] == ["a", "b"]

    def test_callback_exception_does_not_escape(self, logger: logging.Logger) -> None:
        """日志桥出问题不能把业务流程带崩 —— 这是默认行为，不是巧合。"""

        def boom(_record: logging.LogRecord) -> None:
            raise RuntimeError("界面那边炸了")

        logger.addHandler(CallbackHandler(boom))
        logger.info("这条不该抛出去")  # 不抛就是通过

    def test_callback_exception_can_be_allowed_through(self, logger: logging.Logger) -> None:
        def boom(_record: logging.LogRecord) -> None:
            raise RuntimeError("要我就抛")

        logger.addHandler(CallbackHandler(boom, swallow=False))
        with pytest.raises(RuntimeError):
            logger.info("这条会抛")


class TestAttachDetach:
    def test_attach_is_idempotent(self, logger: logging.Logger) -> None:
        buffer = RingBufferHandler(5)
        assert attach_handlers(logger, [buffer]) == [buffer]
        assert attach_handlers(logger, [buffer]) == []
        assert logger.handlers.count(buffer) == 1

    def test_detach_removes_and_closes(self, logger: logging.Logger) -> None:
        buffer = RingBufferHandler(5)
        attach_handlers(logger, [buffer])
        detach_handlers(logger, [buffer])
        assert buffer not in logger.handlers

    def test_detach_ignores_handlers_never_attached(self, logger: logging.Logger) -> None:
        detach_handlers(logger, [RingBufferHandler(5)])  # 不该抛


class TestSetupLoggingKeepsForeignHandlers:
    def test_external_handler_survives_resetup(self) -> None:
        """界面先挂日志桥、装配过程后调 setup_logging —— 桥不能被冲掉。

        这是 ``_gamebot_managed`` 标记存在的唯一理由。没有它的话
        ``setup_logging`` 会清空所有 handler，界面上的日志框变成空的，
        而且看起来像"日志没产生"，极难查。
        """
        root = logging.getLogger("gamebot")
        original = list(root.handlers)
        bridge = RingBufferHandler(10)
        try:
            setup_logging("INFO")
            attach_handlers(root, [bridge])
            setup_logging("DEBUG")  # 再配一次
            assert bridge in root.handlers
            # 而它自己创建的 handler 只管自己人：console 不该被叠加
            managed = [h for h in root.handlers if getattr(h, "_gamebot_managed", False)]
            assert len(managed) == 1
        finally:
            detach_handlers(root, [bridge])
            for handler in list(root.handlers):
                root.removeHandler(handler)
                handler.close()
            for handler in original:
                root.addHandler(handler)


class TestGetLogger:
    def test_prefixes_name(self) -> None:
        assert get_logger("flow.engine").name == "gamebot.flow.engine"

    def test_idempotent_for_root_name(self) -> None:
        assert get_logger("gamebot").name == "gamebot"

    def test_does_not_double_prefix(self) -> None:
        assert get_logger("gamebot.flow").name == "gamebot.flow"
