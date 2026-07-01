# -*- coding: utf-8 -*-
"""Application logging for camera, SDK, and UI diagnostics."""

from __future__ import annotations

import faulthandler
import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from .resources import project_root


_LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_CONFIGURED = False
_FAULT_FILE = None


def debug_log_path() -> Path:
    """Return the legacy debug log path."""
    return app_log_path()


def app_log_path() -> Path:
    """Return the persistent application log path."""
    return project_root() / "logs" / "tucam_control.log"


def setup_app_logging() -> Path:
    """Configure persistent rotating file logging once and return the log path."""
    global _CONFIGURED, _FAULT_FILE
    log_path = app_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("tucam_control")
    root_logger.setLevel(logging.DEBUG)
    root_logger.propagate = False

    if not _CONFIGURED:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root_logger.addHandler(handler)

        _FAULT_FILE = (log_path.parent / "tucam_fault.log").open("a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE)

        sys.excepthook = _log_unhandled_exception
        root_logger.info(
            "Logging initialized: log=%s python=%s platform=%s executable=%s",
            log_path,
            sys.version.replace("\n", " "),
            platform.platform(),
            sys.executable,
        )
        _CONFIGURED = True

    return log_path


def setup_debug_logging() -> Path:
    """Backward-compatible alias for older imports."""
    return setup_app_logging()


def get_debug_logger(name: str) -> logging.Logger:
    """Return a logger under the tucam_control namespace."""
    setup_app_logging()
    return logging.getLogger(f"tucam_control.{name}")


def get_app_logger(name: str) -> logging.Logger:
    """Return a logger under the tucam_control namespace."""
    return get_debug_logger(name)


def _log_unhandled_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger("tucam_control.unhandled").critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
