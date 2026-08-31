# -*- coding: utf-8 -*-

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tucam_control.ui.table_models import TableDataModel


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_model_replaces_rows_and_exposes_highlight_roles() -> None:
    _app()
    model = TableDataModel(["A", "B"])

    model.replace_rows([("one", 1), ("two", 2)], highlighted_rows=(1,))

    assert model.rowCount() == 2
    assert model.cell_text(0, 1) == "1"
    assert (
        model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole).name()
        == "#ffd6d6"
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole) is None


def test_editable_model_updates_appends_and_removes_rows() -> None:
    _app()
    model = TableDataModel(["A", "B"], editable_columns=(1,))
    model.append_row(("first", "1"))
    editable = model.index(0, 1)

    assert model.setData(editable, "2") is True
    assert model.cell_text(0, 1) == "2"
    assert model.flags(editable) & Qt.ItemFlag.ItemIsEditable
    assert not model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable

    model.append_row(("second", "3"))
    assert model.remove_row(0) is True
    assert model.rows() == [["second", "3"]]
