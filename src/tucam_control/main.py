# -*- coding: utf-8 -*-
"""Entry point for the Dhyana-95-V2 camera control application."""

from __future__ import annotations

import os
import sys
import threading
import ctypes


# ── Redirect C-level stderr (fd 2) to suppress libpng iCCP warnings ──
_original_fd2: int | None = None
_pipe_r: int | None = None

def _start_stderr_filter() -> None:
    global _original_fd2, _pipe_r
    _original_fd2 = os.dup(2)
    _pipe_r, _pipe_w = os.pipe()
    os.dup2(_pipe_w, 2)
    os.close(_pipe_w)

    def _filter() -> None:
        while True:
            try:
                data = os.read(_pipe_r, 4096)
            except OSError:
                break
            if not data:
                break
            text = data.decode("utf-8", errors="replace")
            if "iCCP" not in text and "sRGB" not in text \
                    and "mousePressEvent" not in text \
                    and "mouseDoubleClickEvent" not in text \
                    and "showEvent" not in text:
                try:
                    os.write(_original_fd2, data)
                except OSError:
                    break

    t = threading.Thread(target=_filter, daemon=True)
    t.start()

_start_stderr_filter()


from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from tucam_control.debug_log import get_app_logger, setup_app_logging
from tucam_control.resources import app_icon_path
from tucam_control.ui.main_window import MainWindow


def _set_windows_app_id() -> None:
    """Help Windows use the application icon on the taskbar."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "TucamControl.Dhyana95V2"
        )
    except Exception:
        pass


def _install_qt_message_handler() -> None:
    """Route Qt diagnostic messages into the application log."""
    log = get_app_logger("qt")

    def _handler(msg_type, context, message: str) -> None:
        location = ""
        if context and context.file:
            location = f" ({context.file}:{context.line})"
        text = f"{message}{location}"
        if msg_type == QtMsgType.QtDebugMsg:
            log.debug(text)
        elif msg_type == QtMsgType.QtInfoMsg:
            log.info(text)
        elif msg_type == QtMsgType.QtWarningMsg:
            log.warning(text)
        elif msg_type == QtMsgType.QtCriticalMsg:
            log.error(text)
        elif msg_type == QtMsgType.QtFatalMsg:
            log.critical(text)
        else:
            log.info(text)

    qInstallMessageHandler(_handler)


def main() -> None:
    log_path = setup_app_logging()
    log = get_app_logger("main")
    log.info("Application starting; log: %s", log_path)
    _set_windows_app_id()
    app = QApplication(sys.argv)
    _install_qt_message_handler()
    app.setApplicationName("Dhyana-95-V2 Camera Control")
    app.setOrganizationName("TucamControl")

    icon_path = app_icon_path()
    app_icon = QIcon(str(icon_path)) if icon_path is not None else QIcon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()

    # Ensure camera is released on any exit
    app.aboutToQuit.connect(window.close)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
