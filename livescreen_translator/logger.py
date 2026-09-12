"""Local, rotating file logging. Never logs screenshots; text logging can be disabled."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .config import app_data_dir

_LOGGER_NAME = "livescreen"
_configured = False


def log_path() -> Path:
    return app_data_dir() / "livescreen.log"


def setup_logging(enabled: bool = True, level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        logger.disabled = not enabled
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        fh = RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.disabled = not enabled
    _configured = True
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME if not name else f"{_LOGGER_NAME}.{name}")


class TextLogFilter:
    """Decides whether recognized/translated text may be written to the log."""

    def __init__(self, log_text: bool = True):
        self.log_text = log_text

    def fmt(self, text: str) -> str:
        if self.log_text:
            return repr(text)
        return f"<{len(text)} chars, text logging disabled>"
