# -*- coding: utf-8 -*-
"""Entry point for the Dhyana-95-V2 camera control application."""

from __future__ import annotations

import os
import sys
import threading


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
            if "iCCP" not in text and "sRGB" not in text:
                try:
                    os.write(_original_fd2, data)
                except OSError:
                    break

    t = threading.Thread(target=_filter, daemon=True)
    t.start()

_start_stderr_filter()


from PySide6.QtWidgets import QApplication

from tucam_control.ui.main_window import MainWindow


def main() -> None:
    import traceback
    app = QApplication(sys.argv)
    app.setApplicationName("Dhyana-95-V2 Camera Control")
    app.setOrganizationName("TucamControl")

    # Global exception hook for debugging
    _old_hook = sys.excepthook
    def _hook(etype, value, tb):
        traceback.print_exception(etype, value, tb)
        _old_hook(etype, value, tb)
    sys.excepthook = _hook

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
