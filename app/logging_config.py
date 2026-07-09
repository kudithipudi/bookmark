import logging
import os
import sys

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# Logs go to stdout only, captured by gunicorn/systemd — see `journalctl -u
# bookmark`. No file logging: keeps the app directory free of log files.
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging() -> logging.Logger:
    """Configure the application's root logger. Idempotent."""
    global _configured
    logger = logging.getLogger("bookmark")
    if _configured:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Console -> stdout, captured by gunicorn / systemd journal.
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # Don't double-log through the root logger.
    logger.propagate = False
    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the application logger (e.g. 'bookmark.scraper')."""
    base = logging.getLogger("bookmark")
    return base.getChild(name) if name else base
