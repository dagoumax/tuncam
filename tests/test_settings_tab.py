# -*- coding: utf-8 -*-

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tucam_control.camera import CameraInfo
from tucam_control.ui.settings_tab import DEFAULT_SAVE_DIR, SettingsTab


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_settings_apply_emits_normalized_values() -> None:
    _app()
    tab = SettingsTab()
    emitted: list[dict] = []
    tab.settings_changed.connect(emitted.append)

    tab._exp_spin.setValue(1234.5)
    tab._temp_spin.setValue(-12.0)
    tab._fan_combo.setCurrentIndex(2)
    tab._auto_save_cb.setChecked(True)
    tab._save_dir_edit.setText("")
    tab._row_groups_edit.setText("1-10, 20-30")
    tab._merge_spin.setValue(2)
    tab._smooth_combo.setCurrentIndex(0)

    tab._on_apply()

    assert len(emitted) == 1
    updates = emitted[0]
    assert updates["exposure_time_ms"] == 1234.5
    assert updates["temperature_c"] == -12.0
    assert updates["fan_gear"] == 3
    assert updates["auto_save"] is True
    assert updates["save_dir"] == DEFAULT_SAVE_DIR
    assert updates["row_groups_text"] == "1-10, 20-30"
    assert updates["merge_factor"] == 2
    assert updates["concentration_smoothing"] == "off"
    assert len(updates["gas_configs"]) >= 1


def test_device_status_hides_unsupported_zero_temperatures() -> None:
    _app()
    tab = SettingsTab()
    tab.update_device_status(CameraInfo(model="Dhyana", serial_number="S1"))

    assert tab._status_temp.text() == "N/A"
