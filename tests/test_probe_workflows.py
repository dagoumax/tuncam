import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
from unittest.mock import Mock
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from tucam_control.row_group_io import read_groups_csv, write_groups_csv, detect_folder_groups, detect_profile_groups
from tucam_control.ui.data_tab import DataTab
from tucam_control.ui.main_window import MainWindow
from tucam_control.gas_analyzer import GasConfig


def test_cursor_survives_frames_and_clamps_to_new_width():
    app = QApplication.instance() or QApplication([])
    tab = DataTab()
    tab.show()
    app.processEvents()
    tab.display_array(np.ones((1, 100)))
    tab._cursor_toggle_cb.setChecked(True)
    tab._cursor_on = True
    tab._cursor_idx = 70
    tab.display_array(np.full((1, 100), 12))
    tab._do_redraw()
    assert tab._cursor_on and tab._cursor_idx == 70
    assert tab._cursor_vline.isVisible()
    assert tab._cursor_markers.getData()[1][0] == 12
    tab.display_array(np.ones((1, 40)))
    assert tab._cursor_idx == 39
    tab.close()


def test_probe_csv_roundtrip_and_validation(tmp_path):
    path = tmp_path / "probes.csv"
    rows = [("第一个探头", 10, 30), ("名称,含逗号", 70, 90)]
    write_groups_csv(path, rows)
    assert read_groups_csv(path) == rows
    with pytest.raises(ValueError):
        write_groups_csv(path, [("A", 1, 10), ("a", 11, 20)])
    assert read_groups_csv(path) == rows
    path.write_text("名称,起始行,结束行\n坏范围,20,10\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_groups_csv(path)


def test_detect_bands_rejects_noise_and_hot_pixel(tmp_path):
    rng = np.random.default_rng(5)
    image = rng.normal(100, 1, (240, 400))
    Image.fromarray(image.astype(np.float32)).save(tmp_path / "noise.tif")
    with pytest.raises(ValueError):
        detect_folder_groups(tmp_path)
    (tmp_path / "noise.tif").unlink()
    y, x = np.arange(240), np.arange(400)
    for center in (60, 170):
        image += 200 * np.exp(-((y[:, None] - center) / 9) ** 2) * np.exp(-((x[None, :] - 180) / 8) ** 2)
    image[115, 20] = 60000
    Image.fromarray(image.astype(np.float32)).save(tmp_path / "bands.tif")
    rows = detect_folder_groups(tmp_path)
    assert len(rows) == 2
    for (_, start, end), center in zip(rows, (61, 171)):
        assert start <= center <= end
    assert rows[0][0] == "第一个探头"


def test_dim_band_survives_bright_neighbour_and_adjacent_bands_share_edges():
    x = np.arange(600)
    profile = np.ones(600)
    profile[150:460] += 20
    for center, height in ((200, 100), (260, 8), (320, 40), (410, 1000)):
        profile += height * np.exp(-0.5 * ((x - center) / 8) ** 2)
    rows = detect_profile_groups(profile)
    assert len(rows) == 4
    for (_, start, end), center in zip(rows, (201, 261, 321, 411)):
        assert start <= center <= end
    for first, second in zip(rows, rows[1:]):
        assert first[2] + 1 == second[1]


def test_dark_gap_is_not_filled_between_probes():
    x = np.arange(300)
    profile = 1 + 50 * np.exp(-0.5 * ((x - 60) / 8) ** 2)
    profile += 40 * np.exp(-0.5 * ((x - 200) / 8) ** 2)
    rows = detect_profile_groups(profile)
    assert len(rows) == 2
    assert rows[0][2] < 100
    assert rows[1][1] > 160


@pytest.mark.parametrize("profile", [[], [1] * 6, [[1] * 20], [float("nan")] * 20])
def test_invalid_detection_profile_is_rejected(profile):
    with pytest.raises(ValueError):
        detect_profile_groups(profile)


@pytest.mark.parametrize("change,clear", [
    ({"show_plot_fps": True}, False),
    ({"concentration_smoothing": "off"}, False),
    ({"arpls_mode": "baseline"}, False),
    ({"row_group_names": {"rows:1:10": "新名字"}}, False),
    ({"row_groups_text": "2-12"}, True),
    ({"merge_factor": 2}, True),
    ({"alarm": 20}, False),
    ({"coefficient": 2}, True),
])
def test_settings_clear_only_calculation_changes(monkeypatch, change, clear):
    import tucam_control.ui.main_window as module
    monkeypatch.setattr(module, "save_user_settings", lambda *_: "settings.json")
    gas = GasConfig("N2", 100)
    settings = dict(row_groups_text="1-10", row_group_names={}, merge_factor=1,
                    concentration_smoothing="balanced", arpls_mode="corrected")
    window = SimpleNamespace(
        _settings=settings, _camera=SimpleNamespace(is_open=False),
        _processor=SimpleNamespace(row_groups=[(1, 10)]),
        _analyzer=SimpleNamespace(gases=[gas]), _processing_generation=0,
        _conc_tab=Mock(), _data_tab=Mock(), _settings_tab=Mock(),
        _batch_timer=Mock(), _concentration_smoother=Mock(), _raman_signal_monitor=Mock(),
        status_changed=Mock(), _gas_signature=MainWindow._gas_signature,
    )
    for name in ("_configure_fps_display", "_configure_plot_acceleration", "_clear_diagnostic_error",
                 "_set_diagnostic_error", "_update_diagnostics", "_reprocess_cached", "_configure_remote_server"):
        setattr(window, name, Mock())
    window._configure_concentration_smoothing = lambda: settings["concentration_smoothing"]
    updates = dict(change)
    if "alarm" in updates:
        updates["gas_configs"] = [replace(gas, alarm_concentration=updates.pop("alarm"))]
    if "coefficient" in updates:
        updates["gas_configs"] = [replace(gas, coefficient=updates.pop("coefficient"))]
    MainWindow._on_settings_changed(window, updates)
    assert window._conc_tab.clear_history.called is clear
