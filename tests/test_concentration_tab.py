# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView

from tucam_control.ui.concentration_tab import ConcentrationTab
from tucam_control.ui.plot_style import COLORS
from tucam_control.gas_analyzer import GasResult


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _show(tab: ConcentrationTab) -> None:
    tab.show()
    _app().processEvents()


def test_frame_updates_preserve_group_and_gas_selection() -> None:
    _app()
    tab = ConcentrationTab()
    groups = ["行 1-10", "行 11-20"]
    gases = ["O2", "N2", "CO2"]

    tab.set_group_labels(groups)
    tab.set_gas_names(gases)
    tab._group_combo.setCurrentIndex(tab._group_combo.findData(groups[1]))
    tab._gas_combo.setCurrentIndex(tab._gas_combo.findData("N2"))
    tab._statistics_gas_combo.setCurrentIndex(
        tab._statistics_gas_combo.findData("CO2")
    )

    for _ in range(3):
        tab.set_group_labels(list(groups))
        tab.set_gas_names(list(gases))

    assert tab._group_combo.currentData() == groups[1]
    assert tab._gas_combo.currentData() == "N2"
    assert tab._statistics_gas_combo.currentData() == "CO2"


def test_sixteen_row_groups_are_available_in_selector() -> None:
    _app()
    tab = ConcentrationTab()
    groups = [f"行 {index * 10 + 1}-{index * 10 + 10}" for index in range(16)]

    tab.set_group_labels(groups)

    assert tab._group_combo.count() == 17
    assert tab._group_combo.maxVisibleItems() >= 16
    assert tab._group_combo.itemText(16) == groups[-1]


def test_group_identity_is_separate_from_display_label() -> None:
    _app()
    tab = ConcentrationTab()
    result = GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 1.0, 1.0, True)

    tab.add_data_point(
        [[result]],
        ["行 1-10"],
        group_ids=["rows:1:10"],
    )

    assert "rows:1:10" in tab._history
    assert "行 1-10" not in tab._history
    assert tab._group_combo.itemData(1) == "rows:1:10"
    assert tab._group_combo.itemText(1) == "行 1-10"


def test_group_selector_has_default_and_falls_back_when_selection_disappears() -> None:
    _app()
    tab = ConcentrationTab()

    tab.set_group_labels([])
    assert tab._group_combo.currentData() == "__all__"
    assert tab._group_combo.currentText() == "全部探头 / All Probes"

    tab.set_group_labels(["行 1-10", "行 11-20"])
    tab._group_combo.setCurrentIndex(tab._group_combo.findData("行 11-20"))
    tab.set_group_labels(["行 1-10"])

    assert tab._group_combo.currentData() == "__all__"
    assert tab._group_combo.currentIndex() == 0


def test_emergency_stop_button_emits_request() -> None:
    _app()
    tab = ConcentrationTab()
    emitted: list[bool] = []
    tab.emergency_stop_requested.connect(lambda: emitted.append(True))

    tab._btn_emergency_stop.click()

    assert emitted == [True]


def test_concentration_fps_overlay_can_be_toggled() -> None:
    _app()
    tab = ConcentrationTab()

    tab.set_fps_display_enabled(True)
    tab._fps_window_started -= 1.1
    tab._record_fps_frame()

    assert tab._fps_label.isHidden() is False
    assert tab._fps_label.text().startswith("FPS: ")

    tab.set_fps_display_enabled(False)
    assert tab._fps_label.isHidden() is True


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
    _show(tab)
    tab.set_alarm_thresholds({"halong": 10.0})
    result = GasResult("halong", 0, 0, 1.0, 1.0, 1.0, 0.12, 0.12, True)

    tab.add_data_point([[result]], ["行 1-10"])

    assert tab._statistics_model.rowCount() == 1
    assert tab._statistics_model.cell_text(0, 8) == "超限 / Above"
    background = tab._statistics_model.data(
        tab._statistics_model.index(0, 0),
        Qt.ItemDataRole.BackgroundRole,
    )
    assert background.name() == "#ffd6d6"


def test_threshold_statistics_model_reuses_model_and_clears_warning_style() -> None:
    _app()
    tab = ConcentrationTab()
    _show(tab)
    tab.set_alarm_thresholds({"halong": 10.0})
    above = GasResult("halong", 0, 0, 1.0, 1.0, 1.0, 0.12, 0.12, True)
    normal = GasResult("halong", 0, 0, 1.0, 1.0, 1.0, 0.08, 0.08, True)

    tab.add_data_point([[above]], ["行 1-10"])
    model = tab._statistics_table.model()
    tab.add_data_point([[normal]], ["行 1-10"])

    assert tab._statistics_table.model() is model
    assert tab._statistics_model.cell_text(0, 8) == "正常 / Normal"
    index = tab._statistics_model.index(0, 0)
    assert tab._statistics_model.data(index, Qt.ItemDataRole.BackgroundRole) is None
    assert tab._statistics_model.data(index, Qt.ItemDataRole.ForegroundRole) is None


def test_hidden_concentration_tab_defers_statistics_widget_refresh() -> None:
    app = _app()
    tab = ConcentrationTab()
    result = GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 0.2, 0.2, True)

    tab.add_data_point([[result]], ["行 1-10"])

    assert tab._statistics.snapshots()
    assert tab._statistics_model.rowCount() == 0
    assert tab._statistics_table_dirty is True

    tab.show()
    app.processEvents()
    assert tab._statistics_model.rowCount() == 1
    assert tab._statistics_model.cell_text(0, 1) == "O2"
    assert tab._statistics_table_dirty is False


def test_concentration_animation_uses_precise_timer() -> None:
    _app()
    tab = ConcentrationTab()

    assert tab._redraw_timer.timerType() == Qt.TimerType.PreciseTimer


def test_statistics_columns_do_not_resize_to_contents_on_every_value_change() -> None:
    _app()
    tab = ConcentrationTab()
    header = tab._statistics_table.horizontalHeader()

    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    assert header.sectionResizeMode(7) == QHeaderView.ResizeMode.Stretch


def test_threshold_statistics_gas_filter_is_independent_from_chart() -> None:
    _app()
    tab = ConcentrationTab()
    _show(tab)
    tab.set_gas_names(["O2", "N2"])
    results = [
        GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 0.2, 0.2, True),
        GasResult("N2", 0, 0, 1.0, 1.0, 1.0, 0.8, 0.8, True),
    ]
    tab.add_data_point([results], ["行 1-10"])

    tab._statistics_gas_combo.setCurrentIndex(
        tab._statistics_gas_combo.findData("N2")
    )

    assert tab._statistics_model.rowCount() == 1
    assert tab._statistics_model.cell_text(0, 1) == "N2"
    assert tab._gas_combo.currentData() == "all"


def test_threshold_summary_export_uses_selected_gas(tmp_path: Path) -> None:
    _app()
    tab = ConcentrationTab()
    tab.set_gas_names(["O2", "N2"])
    results = [
        GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 0.2, 0.2, True),
        GasResult("N2", 0, 0, 1.0, 1.0, 1.0, 0.8, 0.8, True),
    ]
    tab.add_data_point([results], ["行 1-10"])
    tab._statistics_gas_combo.setCurrentIndex(
        tab._statistics_gas_combo.findData("N2")
    )
    path = tmp_path / "filtered-summary.csv"

    tab._write_statistics_csv(
        str(path),
        tab._filtered_statistics_snapshots(),
    )

    text = path.read_text(encoding="utf-8-sig")
    assert ",N2," in text
    assert ",O2," not in text


def test_clear_history_resets_threshold_statistics() -> None:
    _app()
    tab = ConcentrationTab()
    result = GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 0.2, 0.2, True)
    tab.add_data_point([[result]], ["行 1-10"])

    tab.clear_history()

    assert tab._statistics.snapshots() == []
    assert tab._statistics_model.rowCount() == 0


def test_threshold_summary_csv_contains_mean_and_millisecond_time(tmp_path: Path) -> None:
    _app()
    tab = ConcentrationTab()
    tab.set_statistics_window_seconds(60)
    tab.set_alarm_thresholds({"halong": 10.0})
    result = GasResult("halong", 0, 0, 1.0, 1.0, 1.0, 0.12, 0.12, True)
    tab.add_data_point(
        [[result]],
        ["哈龙检测通道"],
        group_ids=["rows:1:10"],
    )
    path = tmp_path / "summary.csv"

    tab._write_statistics_csv(str(path), tab._statistics.snapshots())

    text = path.read_text(encoding="utf-8-sig")
    assert "连续超限 (s) / Continuous" in text
    assert "平均值 (%) / Mean" in text
    assert "标准差" not in text
    assert "哈龙检测通道,halong,12.000000,10.000000" in text
    assert "rows:1:10" not in text
    assert "起始行" not in text
    assert "结束行" not in text
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


def test_raman_signal_failure_is_shown_without_triggering_emergency_stop() -> None:
    _app()
    tab = ConcentrationTab()
    emergency_requests: list[bool] = []
    tab.emergency_stop_requested.connect(lambda: emergency_requests.append(True))
    status = SimpleNamespace(
        state="failed",
        message="所有行组连续 3 帧仅检测到噪声，疑似激光器、光路或标定位置异常",
        strongest_peak_snr=1.25,
    )

    tab.update_raman_signal_status(status)

    assert "疑似激光器" in tab._raman_signal_label.text()
    assert "SNR" not in tab._raman_signal_label.text()
    assert "1.25" not in tab._raman_signal_label.text()
    assert emergency_requests == []


def test_raman_signal_recovery_returns_hint_to_normal() -> None:
    _app()
    tab = ConcentrationTab()

    tab.update_raman_signal_status(
        SimpleNamespace(
            state="healthy",
            message="拉曼信号已恢复",
            strongest_peak_snr=18.4,
        )
    )

    assert "拉曼信号已恢复" in tab._raman_signal_label.text()
    assert "#e7f5ea" in tab._raman_signal_label.styleSheet()


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


def test_many_series_are_batched_into_few_plot_items() -> None:
    app = _app()
    tab = ConcentrationTab()
    groups = [f"行 {index * 10 + 1}-{index * 10 + 10}" for index in range(15)]
    gases = ["O2", "N2", "CO2", "halong"]
    tab.set_group_labels(groups)
    tab.set_gas_names(gases)
    results = [
        [
            GasResult(name, 0, 0, 1.0, 1.0, 1.0, 0.25, 0.25, True)
            for name in gases
        ]
        for _ in groups
    ]
    tab.add_data_point(results, groups)
    tab.resize(1200, 800)
    tab.show()
    app.processEvents()

    tab._do_redraw()

    dense_keys = [
        key for key, curve in tab._curve_items.items()
        if key[0] == "__dense__" and curve.isVisible()
    ]
    assert len(dense_keys) <= len(COLORS)
    assert len(dense_keys) < len(groups) * len(gases)
    assert all(
        not marker.isVisible()
        for marker in tab._marker_items.values()
    )


def test_switching_from_dense_view_restores_individual_group_curves() -> None:
    app = _app()
    tab = ConcentrationTab()
    groups = [f"行 {index * 10 + 1}-{index * 10 + 10}" for index in range(15)]
    gases = ["O2", "N2", "CO2", "halong"]
    results = [
        [
            GasResult(name, 0, 0, 1.0, 1.0, 1.0, 0.25, 0.25, True)
            for name in gases
        ]
        for _ in groups
    ]
    tab.add_data_point(results, groups)
    tab.resize(1200, 800)
    tab.show()
    app.processEvents()
    tab._do_redraw()

    tab._group_combo.setCurrentIndex(tab._group_combo.findData(groups[0]))
    tab._do_redraw()

    visible_individual = [
        key for key, curve in tab._curve_items.items()
        if key[0] != "__dense__" and curve.isVisible()
    ]
    assert len(visible_individual) == len(gases)


def test_curve_tail_uses_cubic_smoothstep_not_linear_motion() -> None:
    values = ConcentrationTab._smoothstep(np.asarray([0.0, 0.25, 0.5, 0.75, 1.0]))

    assert values.tolist() == [0.0, 0.15625, 0.5, 0.84375, 1.0]
    assert values[1] != 0.25


def test_y_axis_keeps_a_hundred_percent_curve_inside_plot() -> None:
    _app()
    tab = ConcentrationTab()
    tab._display_y_range = (0.0, 50.0)

    tab._apply_ranges([0.0, 1.0], [20.0, 100.0])

    assert tab._display_y_range[1] >= 102.0
    assert tab._display_y_range[1] > 100.0


def test_animation_tail_update_does_not_rescan_full_history(monkeypatch) -> None:
    _app()
    tab = ConcentrationTab()
    group = "行 1-10"
    gas = "O2"
    start = datetime.now() - timedelta(seconds=1)
    tab.set_group_labels([group])
    tab.set_gas_names([gas])
    tab._history[group] = {
        gas: ([20.0, 21.0], [start, start + timedelta(seconds=1)])
    }
    tab._display_animation[(group, gas)] = {
        "from_y": 20.0,
        "to_y": 21.0,
        "start": 0.0,
        "duration": 1.0,
    }
    _show(tab)
    tab._do_redraw()
    assert tab._animation_tail_cache

    monkeypatch.setattr(
        tab,
        "_clip_for_display",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("animation tick rescanned full history")
        ),
    )

    tab._update_animation_tail()


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
