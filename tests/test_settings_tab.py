# -*- coding: utf-8 -*-

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableView

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
    tab._set_row_groups(
        [(1, 10), (20, 30)],
        {
            "rows:1:10": "参考通道",
            "rows:20:30": "哈龙通道",
        },
    )
    tab._merge_spin.setValue(2)
    tab._threshold_sigma_spin.setValue(3.0)
    tab._smooth_combo.setCurrentIndex(0)
    tab._export_sample_rate_spin.setValue(1000)
    tab._plot_opengl_cb.setChecked(False)
    tab._show_plot_fps_cb.setChecked(True)
    tab._remote_enabled_cb.setChecked(True)
    tab._remote_port_spin.setValue(9876)
    tab._remote_allowed_ip_edit.setText("192.168.50.2")
    tab._remote_token_edit.setText("test-access-key")

    tab._on_apply()

    assert len(emitted) == 1
    updates = emitted[0]
    assert updates["exposure_time_ms"] == 1234.5
    assert updates["temperature_c"] == -12.0
    assert updates["fan_gear"] == 2
    assert updates["auto_save"] is True
    assert updates["save_dir"] == DEFAULT_SAVE_DIR
    assert updates["row_groups_text"] == "1-10 20-30"
    assert updates["row_group_names"] == {
        "rows:1:10": "参考通道",
        "rows:20:30": "哈龙通道",
    }
    assert updates["row_aggregation"] == "sum"
    assert updates["merge_factor"] == 2
    assert updates["detection_threshold_sigma"] == 3.0
    assert updates["concentration_smoothing"] == "off"
    assert updates["export_sample_rate_hz"] == 1000
    assert updates["plot_opengl_enabled"] is False
    assert updates["show_plot_fps"] is True
    assert updates["remote_enabled"] is True
    assert updates["remote_port"] == 9876
    assert updates["remote_allowed_ip"] == "192.168.50.2"
    assert updates["remote_token"] == "test-access-key"
    assert "statistics_window_seconds" not in updates
    assert "gas_emergency_stop" not in updates
    assert len(updates["gas_configs"]) >= 1


def test_device_status_hides_unsupported_zero_temperatures() -> None:
    _app()
    tab = SettingsTab()
    tab.update_device_status(CameraInfo(model="Dhyana", serial_number="S1"))

    assert tab._status_temp.text() == "N/A"


def test_settings_layout_is_scrollable_readable_and_two_column() -> None:
    app = _app()
    tab = SettingsTab()
    tab.resize(1400, 900)
    tab.show()
    app.processEvents()
    grid = tab._settings_scroll.widget().layout()

    assert tab._settings_scroll.widgetResizable() is True
    assert grid.columnCount() == 2
    assert grid.itemAtPosition(2, 0).widget() is tab._settings_sections[-1]
    assert tab._gas_table.minimumHeight() >= 240
    assert isinstance(tab._gas_table, QTableView)
    assert tab._btn_apply.minimumHeight() >= 40
    assert "font-size: 14px" in tab.styleSheet()

    tab.resize(1024, 768)
    app.processEvents()
    assert tab._compact_layout is True
    assert grid.itemAtPosition(4, 0).widget() is tab._settings_sections[-1]


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
            "row_group_names": {"rows:10:20": "校准通道"},
            "row_aggregation": "mean",
            "merge_factor": 4,
            "detection_threshold_sigma": 1.75,
            "plot_opengl_enabled": False,
            "show_plot_fps": True,
            "remote_enabled": True,
            "remote_port": 9123,
            "remote_allowed_ip": "10.10.10.2",
            "remote_token": "persisted-access-key",
        },
        gases,
    )

    assert tab._exp_spin.value() == 2222.0
    assert tab._temp_spin.value() == -15.0
    assert tab._fan_combo.currentData() == 1
    assert tab._row_groups == [(10, 20)]
    assert tab._row_group_names == {"rows:10:20": "校准通道"}
    assert tab._row_groups_summary.text() == "校准通道"
    assert tab._row_aggregation_combo.currentData() == "mean"
    assert tab._merge_spin.value() == 4
    assert tab._threshold_sigma_spin.value() == 1.75
    assert tab._plot_opengl_cb.isChecked() is False
    assert tab._show_plot_fps_cb.isChecked() is True
    assert tab._remote_enabled_cb.isChecked() is True
    assert tab._remote_port_spin.value() == 9123
    assert tab._remote_allowed_ip_edit.text() == "10.10.10.2"
    assert tab._remote_token_edit.text() == "persisted-access-key"
    assert tab._get_gas_configs() == gases


def test_many_row_groups_use_compact_manager_summary() -> None:
    _app()
    tab = SettingsTab()
    groups = " ".join(f"{start}-{start + 20}" for start in range(1, 301, 20))

    tab.load_settings({"row_groups_text": groups}, [])

    assert len(tab._row_groups) == 15
    assert tab._row_groups_summary.text().endswith("等 15 个")
    assert isinstance(tab._manage_row_groups_button, QPushButton)
