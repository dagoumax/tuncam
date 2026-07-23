# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from tucam_control.ui.concentration_tab import ConcentrationTab
from tucam_control.gas_analyzer import GasResult


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_frame_updates_preserve_group_and_gas_selection() -> None:
    _app()
    tab = ConcentrationTab()
    groups = ["行 1-10", "行 11-20"]
    gases = ["O2", "N2", "CO2"]

    tab.set_group_labels(groups)
    tab.set_gas_names(gases)
    tab._group_combo.setCurrentIndex(tab._group_combo.findData(groups[1]))
    tab._gas_combo.setCurrentIndex(tab._gas_combo.findData("N2"))

    for _ in range(3):
        tab.set_group_labels(list(groups))
        tab.set_gas_names(list(gases))

    assert tab._group_combo.currentData() == groups[1]
    assert tab._gas_combo.currentData() == "N2"


def test_emergency_stop_button_emits_request() -> None:
    _app()
    tab = ConcentrationTab()
    emitted: list[bool] = []
    tab.emergency_stop_requested.connect(lambda: emitted.append(True))

    tab._btn_emergency_stop.click()

    assert emitted == [True]


def test_all_measurement_sources_use_current_local_time() -> None:
    _app()
    tab = ConcentrationTab()
    before = datetime.now()
    result = GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 1.0, 1.0, True)

    tab.add_data_point([[result]], ["行 1-10"], mode="index")

    after = datetime.now()
    recorded = tab._history["行 1-10"]["O2"][1][0]
    assert before <= recorded <= after
    assert tab._mode == "time"


def test_threshold_statistics_table_highlights_above_limit() -> None:
    _app()
    tab = ConcentrationTab()
    tab.set_alarm_thresholds({"halong": 10.0})
    result = GasResult("halong", 0, 0, 1.0, 1.0, 1.0, 0.12, 0.12, True)

    tab.add_data_point([[result]], ["行 1-10"])

    assert tab._statistics_table.rowCount() == 1
    assert tab._statistics_table.item(0, 8).text() == "超限 / Above"
    assert tab._statistics_table.item(0, 0).background().color().name() == "#ffd6d6"


def test_clear_history_resets_threshold_statistics() -> None:
    _app()
    tab = ConcentrationTab()
    result = GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 0.2, 0.2, True)
    tab.add_data_point([[result]], ["行 1-10"])

    tab.clear_history()

    assert tab._statistics.snapshots() == []
    assert tab._statistics_table.rowCount() == 0


def test_threshold_summary_csv_contains_mean_and_millisecond_time(tmp_path: Path) -> None:
    _app()
    tab = ConcentrationTab()
    tab.set_statistics_window_seconds(60)
    tab.set_alarm_thresholds({"halong": 10.0})
    result = GasResult("halong", 0, 0, 1.0, 1.0, 1.0, 0.12, 0.12, True)
    tab.add_data_point([[result]], ["行 1-10"])
    path = tmp_path / "summary.csv"

    tab._write_statistics_csv(str(path), tab._statistics.snapshots())

    text = path.read_text(encoding="utf-8-sig")
    assert "连续超限 (s) / Continuous" in text
    assert "平均值 (%) / Mean" in text
    assert "标准差" not in text
    assert "行 1-10,halong,12.000000,10.000000" in text
    generated = text.splitlines()[1].split(",")[0]
    assert len(generated.rsplit(".", 1)[-1]) == 3


def test_statistics_window_is_changed_from_concentration_page() -> None:
    _app()
    tab = ConcentrationTab()
    emitted: list[int] = []
    tab.statistics_window_changed.connect(emitted.append)

    tab._statistics_window_spin.setValue(120)

    assert tab._statistics.window_seconds == 120
    assert emitted == [120]


def test_smoothed_export_is_resampled_to_1000_hz() -> None:
    _app()
    tab = ConcentrationTab()
    tab.set_export_sample_rate_hz(1000)
    start = datetime(2026, 7, 14, 10, 0, 0)

    values, times = tab._resampled_pairs(
        [0.2, 0.4],
        [start, start + timedelta(seconds=1)],
    )

    assert len(values) == 1001
    assert len(times) == 1001
    assert times[1] - times[0] == timedelta(milliseconds=1)
    assert values[0] == 0.2
    assert values[-1] == 0.4
    assert tab._format_export_time(times[1]) == "2026-07-14T10:00:00.001"


def test_smoothed_export_is_resampled_to_500_hz() -> None:
    _app()
    tab = ConcentrationTab()
    tab.set_export_sample_rate_hz(500)
    start = datetime(2026, 7, 14, 10, 0, 0)

    values, times = tab._resampled_pairs(
        [0.2, 0.4],
        [start, start + timedelta(seconds=1)],
    )

    assert len(values) == 501
    assert len(times) == 501
    assert times[1] - times[0] == timedelta(milliseconds=2)
    assert values[0] == 0.2
    assert values[-1] == 0.4
    assert tab._format_export_time(times[1]) == "2026-07-14T10:00:00.002"


def test_three_second_frames_use_three_second_curve_animation() -> None:
    _app()
    tab = ConcentrationTab()
    key = ("行 1-10", "halong")
    start = datetime(2026, 7, 15, 10, 0, 0)
    tab._history[key[0]] = {key[1]: ([1.9, 2.0], [start, start + timedelta(seconds=3)])}
    result = GasResult(key[1], 0, 0, 1.0, 1.0, 1.0, 0.02, 0.02, True)

    tab._update_display_animation([[result]], [key[0]])

    assert tab._display_animation[key]["duration"] == 3.0


def test_curve_tail_uses_cubic_smoothstep_not_linear_motion() -> None:
    values = ConcentrationTab._smoothstep(np.asarray([0.0, 0.25, 0.5, 0.75, 1.0]))

    assert values.tolist() == [0.0, 0.15625, 0.5, 0.84375, 1.0]
    assert values[1] != 0.25


def test_three_second_interval_resamples_to_requested_rates() -> None:
    _app()
    tab = ConcentrationTab()
    start = datetime(2026, 7, 15, 10, 0, 0)

    tab.set_export_sample_rate_hz(500)
    values_500, times_500 = tab._resampled_pairs(
        [1.9, 2.0], [start, start + timedelta(seconds=3)]
    )
    tab.set_export_sample_rate_hz(1000)
    values_1000, times_1000 = tab._resampled_pairs(
        [1.9, 2.0], [start, start + timedelta(seconds=3)]
    )

    assert len(values_500) == len(times_500) == 1501
    assert len(values_1000) == len(times_1000) == 3001
    assert times_500[1] - times_500[0] == timedelta(milliseconds=2)
    assert times_1000[1] - times_1000[0] == timedelta(milliseconds=1)
