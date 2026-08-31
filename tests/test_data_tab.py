# -*- coding: utf-8 -*-

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tucam_control.ui.data_tab import DataTab


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_sixteen_row_groups_remain_visible_and_selected_between_frames() -> None:
    _app()
    tab = DataTab()
    labels = [f"行 {index * 10 + 1}-{index * 10 + 10}" for index in range(16)]
    spectra = np.zeros((16, 128), dtype=float)
    tab.set_row_labels(labels)
    tab.display_array(spectra)
    tab._group_combo.setCurrentIndex(12)

    tab.set_row_labels(list(labels))
    tab.display_array(spectra.copy())

    assert tab._group_combo.count() == 16
    assert tab._group_combo.maxVisibleItems() >= 16
    assert tab._group_combo.currentData() == 12
    assert tab._group_combo.itemText(15) == labels[-1]


def test_hidden_tab_does_not_keep_redraw_timer_running() -> None:
    _app()
    tab = DataTab()

    tab.display_array(np.zeros((15, 128), dtype=float))

    assert tab._dirty is True
    assert tab._redraw_timer.isActive() is False


def test_visible_tab_reuses_spectrum_lines_between_frames() -> None:
    app = _app()
    tab = DataTab()
    tab.show()
    app.processEvents()
    first = np.zeros((15, 128), dtype=float)
    tab.set_row_labels([f"group {i}" for i in range(15)])
    tab.display_array(first)
    tab._do_redraw()
    app.processEvents()
    line_ids = [id(line) for line in tab._data_lines]

    tab.display_array(first + 1)
    tab._do_redraw()
    app.processEvents()

    assert len(tab._data_lines) == 15
    assert [id(line) for line in tab._data_lines] == line_ids


def test_raman_view_uses_pyqtgraph_and_updates_curve_data() -> None:
    app = _app()
    tab = DataTab()
    tab.show()
    app.processEvents()
    spectra = np.arange(2 * 128, dtype=float).reshape(2, 128)

    tab.set_row_labels(["A", "B"])
    tab.display_array(spectra)
    tab._do_redraw()

    assert isinstance(tab._plot_widget, pg.PlotWidget)
    assert len(tab._data_lines) == 2
    x_data, y_data = tab._data_lines[1].getData()
    assert np.array_equal(x_data, tab._x_axis_values(128))
    assert np.array_equal(y_data, spectra[1])


def test_opengl_setup_failure_falls_back_without_crashing(monkeypatch) -> None:
    _app()
    tab = DataTab()
    failures: list[str] = []
    tab.opengl_failed.connect(failures.append)
    original = tab._plot_widget.useOpenGL

    def fail_when_enabled(enabled: bool) -> None:
        if enabled:
            raise RuntimeError("test driver failure")
        original(False)

    monkeypatch.setattr(tab._plot_widget, "useOpenGL", fail_when_enabled)

    assert tab.set_opengl_enabled(True) is False
    assert tab._opengl_enabled is False
    assert failures and "test driver failure" in failures[0]


def test_fps_overlay_can_be_enabled_and_updated() -> None:
    _app()
    tab = DataTab()

    tab.set_fps_display_enabled(True)
    tab._fps_window_started -= 1.1
    tab._record_fps_frame()

    assert tab._fps_label.isHidden() is False
    assert tab._fps_label.text().startswith("FPS: ")
    assert tab._fps_label.text() != "FPS: --"

    tab.set_fps_display_enabled(False)
    assert tab._fps_label.isHidden() is True


def test_baseline_and_keyboard_cursor_are_preserved_in_pyqtgraph_view() -> None:
    app = _app()
    tab = DataTab()
    tab.show()
    app.processEvents()
    spectra = np.ones((1, 64), dtype=float)
    baseline = np.full((1, 64), 0.25, dtype=float)
    tab.display_array(spectra)
    tab.set_baseline_data(baseline)
    tab._show_baseline_cb.setChecked(True)
    tab._cursor_toggle_cb.setChecked(True)
    tab._cursor_on = True
    tab._cursor_idx = 10
    tab._do_redraw()

    assert len(tab._baseline_lines) == 1
    assert tab._baseline_lines[0].isVisible()
    assert tab._cursor_vline.isVisible()
    assert tab._handle_cursor_key(Qt.Key.Key_Right) is True
    assert tab._cursor_idx == 11


def test_raman_controls_fit_a_1024_pixel_window() -> None:
    app = _app()
    tab = DataTab()
    tab.resize(1024, 768)
    tab.show()
    app.processEvents()

    assert tab.width() == 1024
    assert tab.minimumSizeHint().width() <= 1024
