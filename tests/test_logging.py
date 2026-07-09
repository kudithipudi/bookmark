import logging

import pytest

from app.logging_config import get_logger, setup_logging


def test_setup_logging_is_idempotent():
    logger = setup_logging()
    handler_count = len(logger.handlers)
    # Calling again must not stack duplicate handlers.
    again = setup_logging()
    assert again is logger
    assert len(again.handlers) == handler_count
    assert handler_count >= 1


def test_get_logger_returns_namespaced_child():
    child = get_logger("scraper")
    assert child.name == "bookmark.scraper"
    assert get_logger().name == "bookmark"


def test_log_records_are_emitted():
    setup_logging()
    # propagate=False, so attach a capturing handler to the app logger directly.
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    app_logger = logging.getLogger("bookmark")
    handler = _Capture()
    app_logger.addHandler(handler)
    try:
        get_logger("test").info("hello %s", "world")
    finally:
        app_logger.removeHandler(handler)
    assert "hello world" in records


def test_no_file_handler_attached():
    # Logging is stdout-only (captured by journald); no file handlers.
    setup_logging()
    logger = logging.getLogger("bookmark")
    assert not any(
        isinstance(h, logging.FileHandler) for h in logger.handlers
    )
