# -*- coding: utf-8 -*-
"""Entry point for the Dhyana-95-V2 camera control application."""

from __future__ import annotations

import sys


class _StderrFilter:
    """Suppress libpng iCCP sRGB profile warnings from Qt PNG loader."""

    def __init__(self, original) -> None:
        self._orig = original

    def write(self, text: str) -> int:
        if isinstance(text, str) and ("iCCP" in text or "sRGB" in text):
            return 0
        return self._orig.write(text)

    def flush(self) -> None:
        self._orig.flush()

    def __getattr__(self, name: str):
        return getattr(self._orig, name)


if not isinstance(sys.stderr, _StderrFilter):
    sys.stderr = _StderrFilter(sys.stderr)

from PySide6.QtWidgets import QApplication

from tucam_control.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Dhyana-95-V2 Camera Control")
    app.setOrganizationName("TucamControl")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
