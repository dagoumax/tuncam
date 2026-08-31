# -*- coding: utf-8 -*-

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableView

from tucam_control.ui.calibration_dialog import CalibrationDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_calibration_points_use_editable_model_view() -> None:
    _app()
    dialog = CalibrationDialog(np.zeros((1, 64)), ["group"], None)
    dialog._peaks = [10, 20]
    spectrum = np.arange(64, dtype=float)

    dialog._populate_table(spectrum)
    shift_index = dialog._peak_model.index(0, 2)

    assert isinstance(dialog._table, QTableView)
    assert dialog._peak_model.rowCount() == 2
    assert dialog._peak_model.cell_text(1, 1) == "20.0"
    assert dialog._peak_model.flags(shift_index) & Qt.ItemFlag.ItemIsEditable
    assert dialog._peak_model.setData(shift_index, "500.0") is True
    assert dialog._peak_model.cell_text(0, 2) == "500.0"
