# -*- coding: utf-8 -*-

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tucam_control.camera_types import CameraInfo
from tucam_control.gas_analyzer import GasConfig
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
    tab._threshold_sigma_spin.setValue(3.0)
    tab._smooth_combo.setCurrentIndex(0)
    tab._export_sample_rate_spin.setValue(1000)
    tab._gas_emergency_stop_cb.setChecked(True)

    tab._on_apply()

    assert len(emitted) == 1
    updates = emitted[0]
    assert updates["exposure_time_ms"] == 1234.5
    assert updates["temperature_c"] == -12.0
    assert updates["fan_gear"] == 2
    assert updates["auto_save"] is True
    assert updates["save_dir"] == DEFAULT_SAVE_DIR
    assert updates["row_groups_text"] == "1-10, 20-30"
    assert updates["row_aggregation"] == "sum"
    assert updates["merge_factor"] == 2
    assert updates["detection_threshold_sigma"] == 3.0
    assert updates["concentration_smoothing"] == "off"
    assert updates["export_sample_rate_hz"] == 1000
    assert updates["gas_emergency_stop"] is True
    assert len(updates["gas_configs"]) >= 1


def test_device_status_hides_unsupported_zero_temperatures() -> None:
    _app()
    tab = SettingsTab()
    tab.update_device_status(CameraInfo(model="Dhyana", serial_number="S1"))

    assert tab._status_temp.text() == "N/A"


def test_persisted_settings_populate_editable_controls() -> None:
    _app()
    tab = SettingsTab()
    gases = [GasConfig("Test", 42, 8, 1.5, 123.0, 12.5, 2.25)]

    tab.load_settings(
        {
            "exposure_time_ms": 2222.0,
            "temperature_c": -15.0,
            "fan_gear": 1,
            "row_groups_text": "10-20",
            "row_aggregation": "mean",
            "merge_factor": 4,
            "detection_threshold_sigma": 1.75,
            "gas_emergency_stop": True,
        },
        gases,
    )

    assert tab._exp_spin.value() == 2222.0
    assert tab._temp_spin.value() == -15.0
    assert tab._fan_combo.currentData() == 1
    assert tab._row_groups_edit.text() == "10-20"
    assert tab._row_aggregation_combo.currentData() == "mean"
    assert tab._merge_spin.value() == 4
    assert tab._threshold_sigma_spin.value() == 1.75
    assert tab._gas_emergency_stop_cb.isChecked() is True
    assert tab._get_gas_configs() == gases
