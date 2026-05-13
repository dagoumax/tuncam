# -*- coding: utf-8 -*-
"""Entry point for the Dhyana-95-V2 camera control application."""

import sys

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
