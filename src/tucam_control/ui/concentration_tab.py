# -*- coding: utf-8 -*-
"""Concentration tab — gas concentration display and trend chart (multi-group)."""

from __future__ import annotations

import csv
from collections import deque
from datetime import datetime
import logging
import time

import numpy as np
import pyqtgraph as pg
from scipy.interpolate import PchipInterpolator
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from ..threshold_statistics import ThresholdStatisticsTracker
from .plot_style import COLORS, WINDOW_SIZE
from .table_models import TableDataModel

MIN_TIME_SPAN_SECONDS = 30.0
MIN_INDEX_SPAN = 20.0
DISPLAY_ANIMATION_DURATION_S = 0.95
DISPLAY_ANIMATION_INTERVAL_MS = 33
DISPLAY_TAIL_SEGMENTS = 10
DENSE_SERIES_THRESHOLD = 24
PERFORMANCE_LOG_INTERVAL_S = 10.0
CONCENTRATION_UPPER_BOUND = 100.0
Y_AXIS_TOP_HEADROOM = 2.0

log = logging.getLogger(__name__)


class LocalTimeAxis(pg.AxisItem):
    """Bottom axis that shows local clock time for timestamp values."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802 - Qt override name
        labels = []
        for value in values:
            try:
                if value > 946684800:
                    labels.append(datetime.fromtimestamp(value).strftime("%H:%M:%S"))
                else:
                    labels.append(f"{value:g}")
            except Exception:
                labels.append("")
        return labels


class ConcentrationTab(QWidget):
    """Fourth tab: current concentrations table + trend chart (multi-group)."""

    emergency_stop_requested = Signal()
    statistics_window_changed = Signal(int)
    opengl_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        # _history[group_label][gas_name] = (vals, times)
        self._history: dict[str, dict[str, tuple[list[float], list[object]]]] = {}
        self._raw_history: dict[str, dict[str, tuple[list[float], list[object]]]] = {}
        self._gas_names: list[str] = []
        self._group_ids: list[str] = []
        self._group_labels: list[str] = []
        self._group_label_by_id: dict[str, str] = {}
        self._batch_idx: int = 0
        self._mode: str = "time"
        self._dirty: bool = False
        self._new_data: bool = False
        self._last_export_dir: str = ""
        self._display_y_range: tuple[float, float] | None = None
        self._export_smoothed: bool = True
        self._export_sample_rate_hz: int = 1000
        self._statistics = ThresholdStatisticsTracker(window_seconds=60)
        self._display_animation: dict[tuple[str, str], dict[str, float]] = {}
        self._curve_items: dict[tuple[str, str], pg.PlotDataItem] = {}
        self._tail_curve_items: dict[tuple[str, str], pg.PlotDataItem] = {}
        self._marker_items: dict[tuple[str, str], pg.ScatterPlotItem] = {}
        self._animation_tail_cache: dict[tuple[str, str], dict[str, object]] = {}
        self._animation_dense_mode = False
        self._animation_x_min: float | None = None
        self._legend_signature: tuple[tuple[tuple[str, str], str], ...] = ()
        self._statistics_table_dirty = False
        self._last_measurement_monotonic: float | None = None
        self._measurement_intervals_ms: deque[float] = deque(maxlen=120)
        self._statistics_refresh_ms: deque[float] = deque(maxlen=120)
        self._redraw_durations_ms: deque[float] = deque(maxlen=600)
        self._animation_tick_count = 0
        self._performance_window_started = time.monotonic()
        self._opengl_enabled = False
        self._opengl_validation_pending = False
        self._fps_display_enabled = False
        self._fps_frame_count = 0
        self._fps_window_started = time.monotonic()

        self._redraw_timer = QTimer(self)
        self._redraw_timer.setInterval(DISPLAY_ANIMATION_INTERVAL_MS)
        self._redraw_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._redraw_timer.timeout.connect(self._tick_redraw)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)

        # -- Left: current concentrations --
        left_widget = QWidget()
        left_widget.setMinimumWidth(330)
        left_widget.setMaximumWidth(420)
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)

        gb_table = QGroupBox("当前浓度 / Current Concentration")
        tbl_layout = QVBoxLayout(gb_table)
        self._table = QTableView()
        self._current_model = TableDataModel(
            ["气体 / Gas", "峰高 / Height", "浓度 / Conc"],
            parent=self._table,
        )
        self._table.setModel(self._current_model)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.setMinimumHeight(155)
        tbl_layout.addWidget(self._table)
        left.addWidget(gb_table)

        self._total_label = QLabel("浓度总和 / Total: --")
        left.addWidget(self._total_label)

        gb_ctrl = QGroupBox("图表控制 / Chart Control")
        ctrl_layout = QVBoxLayout(gb_ctrl)
        ctrl_layout.setSpacing(6)
        control_form = QFormLayout()
        control_form.setHorizontalSpacing(8)
        control_form.setVerticalSpacing(6)

        self._group_combo = QComboBox()
        self._group_combo.setMaxVisibleItems(16)
        self._group_combo.setMinimumContentsLength(12)
        self._group_combo.addItem("全部探头 / All Probes", "__all__")
        self._group_combo.currentIndexChanged.connect(self._do_redraw)
        control_form.addRow("探头 / Probe:", self._group_combo)

        self._gas_combo = QComboBox()
        self._gas_combo.addItem("全部 / All", "all")
        self._gas_combo.currentIndexChanged.connect(self._do_redraw)
        control_form.addRow("气体 / Gas:", self._gas_combo)

        self._display_range_combo = QComboBox()
        self._display_range_combo.addItem("最近100点 / Last 100 points", "visible")
        self._display_range_combo.addItem("最近10分钟 / Last 10 min", 600)
        self._display_range_combo.addItem("最近1小时 / Last 1 hour", 3600)
        self._display_range_combo.addItem("全部历史 / All History", "all")
        self._display_range_combo.currentIndexChanged.connect(self._do_redraw)
        control_form.addRow("显示范围 / Range:", self._display_range_combo)

        self._export_range_combo = QComboBox()
        self._export_range_combo.addItem("全部历史 / All History", "all")
        self._export_range_combo.addItem("最近10分钟 / Last 10 min", 600)
        self._export_range_combo.addItem("最近1小时 / Last 1 hour", 3600)
        self._export_range_combo.addItem("当前显示窗口 / Visible Window", "visible")
        control_form.addRow("导出范围 / Export:", self._export_range_combo)
        ctrl_layout.addLayout(control_form)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_clear = QPushButton("清除历史 / Clear")
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_export = QPushButton("导出 CSV / Export")
        self._btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(self._btn_clear)
        btn_row.addWidget(self._btn_export)
        ctrl_layout.addLayout(btn_row)

        self._btn_emergency_stop = QPushButton("急停 / Emergency Stop")
        self._btn_emergency_stop.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; font-weight: bold; "
            "min-height: 34px; } QPushButton:hover { background-color: #b71c1c; }"
        )
        self._btn_emergency_stop.clicked.connect(self.emergency_stop_requested.emit)
        ctrl_layout.addWidget(self._btn_emergency_stop)

        self._pt_label = QLabel("数据点 / Points: 0")
        ctrl_layout.addWidget(self._pt_label)

        left.addWidget(gb_ctrl)
        left.addStretch()
        top_layout.addWidget(left_widget)

        # -- Right: trend chart --
        right = QVBoxLayout()
        pg.setConfigOptions(antialias=True)
        self._plot_widget = pg.PlotWidget(axisItems={"bottom": LocalTimeAxis(orientation="bottom")})
        self._fps_label = QLabel("FPS: --", self._plot_widget)
        self._fps_label.setStyleSheet(
            "QLabel { background: rgba(25, 25, 25, 185); color: white; "
            "border-radius: 3px; padding: 3px 7px; font-weight: 600; }"
        )
        self._fps_label.move(8, 8)
        self._fps_label.adjustSize()
        self._fps_label.hide()
        self._plot_widget.setBackground("w")
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.showGrid(x=True, y=True, alpha=0.25)
        self._plot_item.setLabel("left", "浓度 / Concentration (%)")
        self._plot_item.setLabel("bottom", "本地时间 / Local Time")
        self._legend = self._plot_item.addLegend(offset=(-12, 12))
        right.addWidget(self._plot_widget, 1)

        top_layout.addLayout(right, 2)
        layout.addLayout(top_layout, 4)

        self._raman_signal_label = QLabel(
            "拉曼信号 / Raman Signal: 等待数据 / Waiting for data"
        )
        self._raman_signal_label.setWordWrap(True)
        self._raman_signal_label.setMinimumHeight(30)
        self._raman_signal_label.setStyleSheet(
            "QLabel { background: #f2f3f5; color: #50545a; "
            "border: 1px solid #c9ccd1; border-radius: 3px; padding: 4px 9px; }"
        )
        layout.addWidget(self._raman_signal_label)

        stats_group = QGroupBox("阈值统计 / Threshold Statistics")
        stats_layout = QVBoxLayout(stats_group)
        self._statistics_table = QTableView()
        self._statistics_model = TableDataModel([
            "探头 / Probe",
            "气体 / Gas",
            "当前 (%)",
            "阈值 (%)",
            "连续 (s)",
            "累计 (s)",
            "N秒点数",
            "N秒均值 (%)",
            "状态 / Status",
        ], parent=self._statistics_table)
        self._statistics_table.setModel(self._statistics_model)
        stats_header = self._statistics_table.horizontalHeader()
        stats_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        stats_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((125, 90, 90, 90, 90, 90, 80, 120, 115)):
            if column != 7:
                self._statistics_table.setColumnWidth(column, width)
        self._statistics_table.verticalHeader().setDefaultSectionSize(30)
        self._statistics_table.setMinimumHeight(170)
        stats_layout.addWidget(self._statistics_table)

        stats_actions = QHBoxLayout()
        stats_actions.setSpacing(6)
        stats_actions.addWidget(QLabel("气体 / Gas:"))
        self._statistics_gas_combo = QComboBox()
        self._statistics_gas_combo.addItem("全部 / All", "all")
        self._statistics_gas_combo.setMinimumWidth(130)
        self._statistics_gas_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_statistics_table()
        )
        stats_actions.addWidget(self._statistics_gas_combo)
        stats_actions.addSpacing(10)
        stats_actions.addWidget(QLabel("统计窗口 / Window:"))
        self._statistics_window_spin = QSpinBox()
        self._statistics_window_spin.setRange(1, 86400)
        self._statistics_window_spin.setValue(60)
        self._statistics_window_spin.setSingleStep(10)
        self._statistics_window_spin.setSuffix(" s")
        self._statistics_window_spin.setMinimumWidth(120)
        self._statistics_window_spin.valueChanged.connect(
            self._on_statistics_window_changed
        )
        self._btn_export_statistics = QPushButton("导出统计摘要 / Export Summary")
        self._btn_export_statistics.clicked.connect(self._on_export_statistics)
        stats_actions.addWidget(self._statistics_window_spin)
        stats_actions.addStretch()
        stats_actions.addWidget(self._btn_export_statistics)
        stats_layout.addLayout(stats_actions)
        layout.addWidget(stats_group, 1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_opengl_enabled(self, enabled: bool) -> bool:
        requested = bool(enabled)
        try:
            self._plot_widget.useOpenGL(requested)
            viewport_name = type(self._plot_widget.viewport()).__name__
            self._opengl_enabled = requested
            self._opengl_validation_pending = requested
            if self._fps_display_enabled:
                self._fps_label.raise_()
            log.info(
                "Concentration plot backend selected: "
                "requested_opengl=%s viewport=%s",
                requested,
                viewport_name,
            )
            return self._opengl_enabled
        except Exception as exc:
            self._opengl_enabled = False
            self._opengl_validation_pending = False
            try:
                self._plot_widget.useOpenGL(False)
            except Exception:
                pass
            log.warning(
                "Concentration plot OpenGL setup failed; using software: %s",
                exc,
            )
            if requested:
                self.opengl_failed.emit(f"Concentration plot: {exc}")
            return False

    def set_fps_display_enabled(self, enabled: bool) -> None:
        self._fps_display_enabled = bool(enabled)
        self._fps_frame_count = 0
        self._fps_window_started = time.monotonic()
        self._fps_label.setText("FPS: --")
        self._fps_label.adjustSize()
        self._fps_label.setVisible(self._fps_display_enabled)
        if self._fps_display_enabled:
            self._fps_label.raise_()

    def _record_fps_frame(self) -> None:
        if not self._fps_display_enabled:
            return
        self._fps_frame_count += 1
        now = time.monotonic()
        elapsed = now - self._fps_window_started
        if elapsed < 1.0:
            return
        self._fps_label.setText(f"FPS: {self._fps_frame_count / elapsed:.1f}")
        self._fps_label.adjustSize()
        self._fps_label.raise_()
        self._fps_frame_count = 0
        self._fps_window_started = now

    def _validate_opengl_context(self) -> None:
        if not self._opengl_enabled or not self._opengl_validation_pending:
            return
        self._opengl_validation_pending = False
        viewport = self._plot_widget.viewport()
        context_getter = getattr(viewport, "context", None)
        context = context_getter() if callable(context_getter) else None
        if context is None or not context.isValid():
            message = f"invalid context ({type(viewport).__name__})"
            log.warning(
                "Concentration plot OpenGL validation failed: %s",
                message,
            )
            self.set_opengl_enabled(False)
            self.opengl_failed.emit(f"Concentration plot: {message}")
            return
        surface_format = context.format()
        log.info(
            "Concentration plot OpenGL active: "
            "viewport=%s version=%s.%s profile=%s",
            type(viewport).__name__,
            surface_format.majorVersion(),
            surface_format.minorVersion(),
            surface_format.profile(),
        )

    def set_gas_names(self, names: list[str]) -> None:
        names = list(names)
        expected = ["all", *names]
        if (
            names == self._gas_names
            and self._combo_data(self._gas_combo) == expected
            and self._combo_data(self._statistics_gas_combo) == expected
        ):
            return
        self._gas_names = names
        self._update_gas_combo()
        self._update_statistics_gas_combo()

    def set_group_labels(
        self,
        labels: list[str],
        group_ids: list[str] | None = None,
    ) -> None:
        labels = list(labels)
        ids = list(group_ids) if group_ids is not None else list(labels)
        if len(ids) != len(labels):
            raise ValueError("group_ids and labels must have the same length")
        if (
            labels == self._group_labels
            and ids == self._group_ids
            and self._combo_data(self._group_combo) == ["__all__", *ids]
        ):
            return
        self._group_ids = ids
        self._group_labels = labels
        self._group_label_by_id = dict(zip(ids, labels))
        self._group_combo.blockSignals(True)
        current = self._group_combo.currentData()
        self._group_combo.clear()
        self._group_combo.addItem("全部探头 / All Probes", "__all__")
        for group_id, label in zip(ids, labels):
            self._group_combo.addItem(label, group_id)
        index = self._group_combo.findData(current)
        self._group_combo.setCurrentIndex(index if index >= 0 else 0)
        self._group_combo.blockSignals(False)

    def set_export_smoothed(self, enabled: bool) -> None:
        self._export_smoothed = enabled

    def set_export_sample_rate_hz(self, sample_rate_hz: int) -> None:
        self._export_sample_rate_hz = max(1, min(1000, int(sample_rate_hz)))

    def set_statistics_window_seconds(self, window_seconds: int) -> None:
        normalized = max(1, min(86400, int(window_seconds)))
        self._statistics_window_spin.blockSignals(True)
        self._statistics_window_spin.setValue(normalized)
        self._statistics_window_spin.blockSignals(False)
        self._statistics.set_window_seconds(window_seconds)
        self._refresh_statistics_table()

    def _on_statistics_window_changed(self, window_seconds: int) -> None:
        self._statistics.set_window_seconds(window_seconds)
        self._refresh_statistics_table()
        self.statistics_window_changed.emit(self._statistics.window_seconds)

    def set_alarm_thresholds(self, thresholds: dict[str, float | None]) -> None:
        self._statistics.set_thresholds(thresholds)
        self._refresh_statistics_table()

    def mark_history_gap(self) -> None:
        self._statistics.mark_gap()
        self._refresh_statistics_table()

    def update_raman_signal_status(self, status) -> None:
        state = str(getattr(status, "state", "unavailable"))
        message = str(getattr(status, "message", "等待数据"))
        palettes = {
            "healthy": ("#e7f5ea", "#146c2e", "#87c796"),
            "suspect": ("#fff4cc", "#805500", "#d9b84c"),
            "recovering": ("#fff4cc", "#805500", "#d9b84c"),
            "degraded": ("#ffe2e2", "#971d1d", "#d98c8c"),
            "failed": ("#ffe2e2", "#971d1d", "#d98c8c"),
            "unavailable": ("#f2f3f5", "#50545a", "#c9ccd1"),
        }
        background, foreground, border = palettes.get(state, palettes["unavailable"])
        self._raman_signal_label.setText(
            f"拉曼信号 / Raman Signal: {message}"
        )
        self._raman_signal_label.setStyleSheet(
            f"QLabel {{ background: {background}; color: {foreground}; "
            f"border: 1px solid {border}; border-radius: 3px; "
            "padding: 4px 9px; font-weight: 600; }"
        )

    def add_data_point(
        self,
        all_group_results: list,
        group_labels: list[str],
        mode: str = "time",
        raw_group_results: list | None = None,
        group_ids: list[str] | None = None,
        measurement_time: datetime | None = None,
    ) -> None:
        """
        Add a measurement point for all row groups.

        *all_group_results*: list of list of GasResult (per group, per gas).
        *group_labels*: labels for each group.
        """
        measurement_now = time.monotonic()
        if self._last_measurement_monotonic is not None:
            self._measurement_intervals_ms.append(
                (measurement_now - self._last_measurement_monotonic) * 1000.0
            )
        self._last_measurement_monotonic = measurement_now

        # Every source uses the same local system clock and chart animation.
        self._mode = "time"
        t = measurement_time if measurement_time is not None else datetime.now()

        group_keys = list(group_ids) if group_ids is not None else list(group_labels)
        if len(group_keys) != len(group_labels):
            raise ValueError("group_ids and group_labels must have the same length")

        self._append_results(self._history, all_group_results, group_keys, t)
        self._append_results(
            self._raw_history,
            raw_group_results if raw_group_results is not None else all_group_results,
            group_keys,
            t,
        )
        self._statistics.update(all_group_results, group_keys, t)
        self._update_display_animation(all_group_results, group_keys)

        self.set_group_labels(group_labels, group_keys)
        self.set_gas_names([r.name for r in all_group_results[0]])

        self._new_data = True
        if all_group_results:
            self._update_table(all_group_results[0])
        if self.isVisible():
            self._refresh_statistics_table()
        else:
            self._statistics_table_dirty = True
        self._redraw()

    def clear_history(self) -> None:
        self._history.clear()
        self._raw_history.clear()
        self._statistics.reset()
        self._display_animation.clear()
        self._animation_tail_cache.clear()
        self._animation_x_min = None
        self._batch_idx = 0
        self._display_y_range = None
        self._current_model.clear()
        self._hide_inactive_plot_items(set())
        self._total_label.setText("浓度总和 / Total: --")
        self._statistics_model.clear()
        self.update_raman_signal_status(None)
        self._do_redraw()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _combo_data(combo: QComboBox) -> list[object]:
        return [combo.itemData(index) for index in range(combo.count())]

    def _update_gas_combo(self) -> None:
        self._gas_combo.blockSignals(True)
        current = self._gas_combo.currentData()
        self._gas_combo.clear()
        self._gas_combo.addItem("全部 / All", "all")
        for name in self._gas_names:
            self._gas_combo.addItem(name, name)
        index = self._gas_combo.findData(current)
        if index >= 0:
            self._gas_combo.setCurrentIndex(index)
        self._gas_combo.blockSignals(False)

    def _update_statistics_gas_combo(self) -> None:
        self._statistics_gas_combo.blockSignals(True)
        current = self._statistics_gas_combo.currentData()
        self._statistics_gas_combo.clear()
        self._statistics_gas_combo.addItem("全部 / All", "all")
        for name in self._gas_names:
            self._statistics_gas_combo.addItem(name, name)
        index = self._statistics_gas_combo.findData(current)
        self._statistics_gas_combo.setCurrentIndex(index if index >= 0 else 0)
        self._statistics_gas_combo.blockSignals(False)
        self._refresh_statistics_table()

    def _filtered_statistics_snapshots(self) -> list:
        snapshots = self._statistics.snapshots()
        selected_gas = self._statistics_gas_combo.currentData()
        if selected_gas in (None, "all"):
            return snapshots
        return [
            snapshot for snapshot in snapshots
            if snapshot.gas_name == selected_gas
        ]

    def _selected_group_data(self) -> dict[str, tuple[list[float], list[object]]]:
        glabel = self._group_combo.currentData()
        if glabel == "__all__":
            return {}
        if glabel and glabel in self._history:
            return self._history[glabel]
        return {}

    def _update_table(self, gas_results: list) -> None:
        total_conc = 0.0
        rows = []
        for i, r in enumerate(gas_results):
            total_conc += r.concentration
            detected_mark = "" if r.detected else " (未检出)"
            rows.append(
                (
                    f"{r.name}{detected_mark}",
                    f"{r.peak_height:.1f}",
                    f"{r.concentration * 100:.2f} %",
                )
            )
        self._current_model.replace_rows(rows)
        self._total_label.setText(f"浓度总和 / Total: {total_conc * 100:.2f} %")

    @staticmethod
    def _append_results(history: dict, all_group_results: list, group_labels: list[str],
                        t: object) -> None:
        for glabel, gas_results in zip(group_labels, all_group_results):
            if glabel not in history:
                history[glabel] = {}
            group_map = history[glabel]
            for r in gas_results:
                if r.name not in group_map:
                    group_map[r.name] = ([], [])
                vals, times = group_map[r.name]
                vals.append(r.concentration * 100)
                times.append(t)

    def _redraw(self) -> None:
        """Request a redraw (periodic — starts timer if not running)."""
        self._dirty = True
        if not self.isVisible():
            self._redraw_timer.stop()
            return
        if not self._redraw_timer.isActive():
            self._redraw_timer.start()

    def _tick_redraw(self) -> None:
        """Periodic tick: redraw if dirty, stop timer if not."""
        if not self.isVisible():
            self._redraw_timer.stop()
            return
        self._animation_tick_count += 1
        self._record_fps_frame()
        if self._dirty:
            self._do_redraw()
        elif self._has_active_animation():
            redraw_started = time.perf_counter()
            self._update_animation_tail()
            self._record_redraw_duration(redraw_started)
        elif self._animation_tail_cache:
            redraw_started = time.perf_counter()
            self._update_animation_tail(force_complete=True)
            self._record_redraw_duration(redraw_started)
            self._animation_tail_cache.clear()
            self._redraw_timer.stop()
        else:
            self._redraw_timer.stop()
        self._maybe_log_performance()

    def _do_redraw(self) -> None:
        if not self.isVisible():
            self._redraw_timer.stop()
            return
        redraw_started = time.perf_counter()
        self._dirty = False

        glabel = self._group_combo.currentData()
        selected_gas = self._gas_combo.currentData()
        is_all_groups = (glabel == "__all__")
        series: list[tuple[str, list[float], list[object], str, tuple[str, str]]] = []
        title = ""
        color_idx = 0

        if is_all_groups and selected_gas == "all":
            total_pts = 0
            for group_id in self._group_ids:
                if group_id not in self._history:
                    continue
                gdata = self._history[group_id]
                for name in self._gas_names:
                    if name not in gdata:
                        continue
                    vals, times = gdata[name]
                    if len(vals) == 0:
                        continue
                    color = COLORS[color_idx % len(COLORS)]
                    color_idx += 1
                    display_label = self._group_label_by_id.get(group_id, group_id)
                    line_label = f"{display_label} {name}"
                    series.append(
                        (line_label, vals, times, color, (group_id, name))
                    )
                    total_pts += len(vals)
            title = "浓度变化 [全部探头] / All Probes & Gases"
            self._pt_label.setText(f"数据点 / Points: {total_pts}")
        elif not is_all_groups:
            group_data = self._selected_group_data()
            if not group_data:
                self._hide_inactive_plot_items(set())
                self._plot_item.setTitle("")
                self._record_redraw_duration(redraw_started)
                return
            series, total_pts, title = self._group_series(group_data, selected_gas, glabel)
            self._pt_label.setText(f"数据点 / Points: {total_pts}")
        else:
            total_pts = 0
            for i, group_id in enumerate(self._group_ids):
                if group_id not in self._history:
                    continue
                group_data = self._history[group_id]
                if selected_gas not in group_data:
                    continue
                vals, times = group_data[selected_gas]
                if len(vals) == 0:
                    continue
                color = COLORS[i % len(COLORS)]
                display_label = self._group_label_by_id.get(group_id, group_id)
                series.append(
                    (
                        display_label,
                        vals,
                        times,
                        color,
                        (group_id, selected_gas),
                    )
                )
                total_pts += len(vals)
            title = f"浓度变化 [全部探头] / {selected_gas}"
            self._pt_label.setText(f"数据点 / Points: {total_pts}")

        self._new_data = False
        is_datetime = self._series_uses_datetime(series)
        self._plot_item.setTitle(title)
        self._plot_item.setLabel(
            "bottom",
            "本地时间 / Local Time" if is_datetime else "帧序号 / Frame Index",
        )
        self._draw_series(series, is_datetime)
        self._record_redraw_duration(redraw_started)

    def _group_series(
        self,
        group_data: dict,
        selected_gas: str,
        glabel: str,
    ) -> tuple[list[tuple[str, list[float], list[object], str, tuple[str, str]]], int, str]:
        """Build visible series for a single group."""
        series = []
        total_pts = sum(len(v) for v, _ in group_data.values())

        display_group = self._group_label_by_id.get(glabel, glabel)
        if selected_gas == "all":
            for i, name in enumerate(self._gas_names):
                if name not in group_data:
                    continue
                vals, times = group_data[name]
                if len(vals) == 0:
                    continue
                series.append((name, vals, times, COLORS[i % len(COLORS)], (glabel, name)))
            title = f"浓度变化 [{display_group}] / All Gases"
        else:
            if selected_gas in group_data:
                vals, times = group_data[selected_gas]
                if len(vals) > 0:
                    idx = self._gas_names.index(selected_gas) if selected_gas in self._gas_names else 0
                    color = COLORS[idx % len(COLORS)]
                    series.append((selected_gas, vals, times, color, (glabel, selected_gas)))
            title = f"浓度变化 [{display_group}] / {selected_gas}"
        return series, total_pts, title

    def _draw_series(
        self,
        series: list[tuple[str, list[float], list[object], str, tuple[str, str]]],
        is_datetime: bool,
    ) -> None:
        if not series:
            self._animation_tail_cache.clear()
            self._hide_inactive_plot_items(set())
            return

        time_origin = None
        axis_x: list[float] = []
        all_y: list[float] = []
        show_legend = len(series) <= 24
        dense_mode = len(series) > DENSE_SERIES_THRESHOLD
        dense_batches: dict[str, tuple[list[float], list[float]]] = {}
        active_keys: set[tuple[str, str]] = set()
        legend_entries: list[tuple[tuple[str, str], str]] = []
        self._animation_tail_cache.clear()
        self._animation_dense_mode = dense_mode
        live_x_max = None

        for label, vals, times, color, series_key in series:
            clipped_vals, clipped_times = self._clip_for_display(vals, times)
            x_vals = self._x_values(clipped_times, is_datetime, time_origin)
            y_vals = [float(v) for v in clipped_vals]
            if not x_vals or not y_vals:
                continue

            static_x = x_vals
            static_y = y_vals
            if is_datetime and len(x_vals) >= 2:
                progress = self._time_aligned_display_progress(clipped_times)
                tail_x_end = x_vals[-2] + (x_vals[-1] - x_vals[-2]) * progress
                animation = self._display_animation.get(series_key, {})
                from_y = float(animation.get("from_y", y_vals[-2]))
                to_y = float(animation.get("to_y", y_vals[-1]))
                static_x = x_vals[:-1]
                static_y = y_vals[:-1]
                self._animation_tail_cache[series_key] = {
                    "x0": float(x_vals[-2]),
                    "x1": float(x_vals[-1]),
                    "from_y": from_y,
                    "to_y": to_y,
                    "previous_time": clipped_times[-2],
                    "target_time": clipped_times[-1],
                    "color": color,
                }
                live_x_max = tail_x_end if live_x_max is None else max(live_x_max, tail_x_end)

            axis_x.extend(static_x)
            all_y.extend(y_vals)
            if dense_mode:
                batch_x, batch_y = dense_batches.setdefault(color, ([], []))
                if batch_x:
                    batch_x.append(float("nan"))
                    batch_y.append(float("nan"))
                batch_x.extend(static_x)
                batch_y.extend(static_y)
                continue

            pen = pg.mkPen(color=color, width=1.4)
            curve = self._curve_items.get(series_key)
            marker = self._marker_items.get(series_key)
            if curve is None:
                curve = pg.PlotDataItem()
                marker = pg.ScatterPlotItem(size=6)
                self._plot_item.addItem(curve)
                self._plot_item.addItem(marker)
                self._curve_items[series_key] = curve
                self._marker_items[series_key] = marker
            curve.setPen(pen)
            curve.setData(static_x, static_y)
            curve.setVisible(True)
            if series_key not in self._animation_tail_cache:
                marker.setData(
                    [x_vals[-1]],
                    [y_vals[-1]],
                    brush=color,
                    pen=pg.mkPen(color=color),
                )
                marker.setVisible(True)
            active_keys.add(series_key)
            if show_legend:
                legend_entries.append((series_key, label))

        if dense_mode:
            for color, (batch_x, batch_y) in dense_batches.items():
                batch_key = ("__dense__", str(color))
                curve = self._curve_items.get(batch_key)
                if curve is None:
                    curve = pg.PlotDataItem()
                    self._plot_item.addItem(curve)
                    self._curve_items[batch_key] = curve
                curve.setPen(pg.mkPen(color=color, width=1.2))
                curve.setData(batch_x, batch_y, connect="finite")
                curve.setVisible(True)
                active_keys.add(batch_key)

        self._hide_inactive_plot_items(active_keys)
        self._update_legend(tuple(legend_entries))
        self._apply_ranges(axis_x, all_y, live_x_max)
        self._update_animation_tail()

    def _update_animation_tail(self, force_complete: bool = False) -> None:
        """Update only the short animated tail, never the full history."""
        if not self._animation_tail_cache:
            return

        tail_count = max(3, DISPLAY_TAIL_SEGMENTS)
        dense_batches: dict[str, tuple[list[float], list[float]]] = {}
        active_tail_keys: set[tuple[str, str]] = set()
        live_x_max: float | None = None

        for series_key, tail in self._animation_tail_cache.items():
            if force_complete:
                progress = 1.0
            else:
                progress = self._time_aligned_display_progress(
                    [tail["previous_time"], tail["target_time"]]
                )
            x0 = float(tail["x0"])
            x1 = float(tail["x1"])
            from_y = float(tail["from_y"])
            to_y = float(tail["to_y"])
            color = str(tail["color"])
            x_end = x0 + (x1 - x0) * progress
            tail_x = np.linspace(x0, x_end, tail_count)
            phase = np.linspace(0.0, progress, tail_count)
            tail_y = from_y + (to_y - from_y) * self._smoothstep(phase)
            live_x_max = x_end if live_x_max is None else max(live_x_max, x_end)

            if self._animation_dense_mode:
                batch_x, batch_y = dense_batches.setdefault(color, ([], []))
                if batch_x:
                    batch_x.append(float("nan"))
                    batch_y.append(float("nan"))
                batch_x.extend(tail_x.tolist())
                batch_y.extend(tail_y.tolist())
                continue

            tail_curve = self._tail_curve_items.get(series_key)
            if tail_curve is None:
                tail_curve = pg.PlotDataItem()
                self._plot_item.addItem(tail_curve)
                self._tail_curve_items[series_key] = tail_curve
            tail_curve.setPen(pg.mkPen(color=color, width=1.4))
            tail_curve.setData(tail_x, tail_y)
            tail_curve.setVisible(True)
            active_tail_keys.add(series_key)

            marker = self._marker_items.get(series_key)
            if marker is not None:
                marker.setData(
                    [x_end],
                    [float(tail_y[-1])],
                    brush=color,
                    pen=pg.mkPen(color=color),
                )
                marker.setVisible(True)

        if self._animation_dense_mode:
            for color, (batch_x, batch_y) in dense_batches.items():
                batch_key = ("__dense__", str(color))
                tail_curve = self._tail_curve_items.get(batch_key)
                if tail_curve is None:
                    tail_curve = pg.PlotDataItem()
                    self._plot_item.addItem(tail_curve)
                    self._tail_curve_items[batch_key] = tail_curve
                tail_curve.setPen(pg.mkPen(color=color, width=1.2))
                tail_curve.setData(batch_x, batch_y, connect="finite")
                tail_curve.setVisible(True)
                active_tail_keys.add(batch_key)

        for key, tail_curve in self._tail_curve_items.items():
            tail_curve.setVisible(key in active_tail_keys)
        self._update_live_x_range(live_x_max)

    @staticmethod
    def _smoothstep(value):
        value = np.clip(value, 0.0, 1.0)
        return value * value * (3.0 - 2.0 * value)

    def _hide_inactive_plot_items(self, active_keys: set[tuple[str, str]]) -> None:
        for key, curve in self._curve_items.items():
            visible = key in active_keys
            curve.setVisible(visible)
            tail_curve = self._tail_curve_items.get(key)
            if tail_curve is not None:
                tail_curve.setVisible(visible)
            marker = self._marker_items.get(key)
            if marker is not None:
                marker.setVisible(visible)

    def _update_legend(
        self,
        signature: tuple[tuple[tuple[str, str], str], ...],
    ) -> None:
        if signature == self._legend_signature:
            return
        self._legend.clear()
        for key, label in signature:
            self._legend.addItem(self._curve_items[key], label)
        self._legend_signature = signature

    @staticmethod
    def _series_uses_datetime(
        series: list[tuple[str, list[float], list[object], str, tuple[str, str]]]
    ) -> bool:
        for _, _, times, _, _ in series:
            if times:
                return isinstance(times[0], datetime)
        return False

    def _time_origin(
        self,
        series: list[tuple[str, list[float], list[object], str, tuple[str, str]]],
    ) -> datetime | None:
        first_times = []
        for _, vals, times, _, _ in series:
            _, clipped_times = self._clip_for_display(vals, times)
            if clipped_times and isinstance(clipped_times[0], datetime):
                first_times.append(clipped_times[0])
        return min(first_times) if first_times else None

    def _update_display_animation(self, all_group_results: list, group_labels: list[str]) -> None:
        if self._mode != "time":
            self._display_animation.clear()
            return

        now = time.monotonic()
        for glabel, gas_results in zip(group_labels, all_group_results):
            for result in gas_results:
                key = (glabel, result.name)
                target = float(result.concentration * 100)
                vals = self._history.get(glabel, {}).get(result.name, ([], []))[0]
                times = self._history.get(glabel, {}).get(result.name, ([], []))[1]
                previous = float(vals[-2]) if len(vals) >= 2 else target
                start_value = self._current_display_value(key, previous)
                duration = DISPLAY_ANIMATION_DURATION_S
                if (
                    len(times) >= 2
                    and isinstance(times[-2], datetime)
                    and isinstance(times[-1], datetime)
                ):
                    duration = max(
                        0.2,
                        min(10.0, (times[-1] - times[-2]).total_seconds()),
                    )
                self._display_animation[key] = {
                    "from_y": start_value,
                    "to_y": target,
                    "start": now,
                    "duration": duration,
                }

    def _current_display_value(
        self,
        key: tuple[str, str],
        default: float,
        progress: float | None = None,
    ) -> float:
        animation = self._display_animation.get(key)
        if not animation or self._mode != "time":
            return default

        progress = self._current_display_progress(key) if progress is None else progress
        if progress >= 1.0:
            return animation["to_y"]

        eased = 1.0 - (1.0 - progress) ** 3
        return animation["from_y"] + (animation["to_y"] - animation["from_y"]) * eased

    def _current_display_progress(self, key: tuple[str, str]) -> float:
        animation = self._display_animation.get(key)
        if not animation or self._mode != "time":
            return 1.0

        elapsed = max(0.0, time.monotonic() - animation["start"])
        duration = animation.get("duration", DISPLAY_ANIMATION_DURATION_S)
        if elapsed >= duration:
            return 1.0
        return elapsed / duration

    @staticmethod
    def _time_aligned_display_progress(times: list[object]) -> float:
        if len(times) < 2:
            return 1.0

        prev_time = times[-2]
        target_time = times[-1]
        if not isinstance(prev_time, datetime) or not isinstance(target_time, datetime):
            return 1.0

        frame_seconds = max(0.001, (target_time - prev_time).total_seconds())
        display_time = datetime.now().timestamp() - frame_seconds
        progress = (display_time - prev_time.timestamp()) / frame_seconds
        return max(0.0, min(1.0, progress))

    def _has_active_animation(self) -> bool:
        if self._mode != "time" or not self._display_animation:
            return False

        now = time.monotonic()
        return any(
            now - animation["start"]
            < animation.get("duration", DISPLAY_ANIMATION_DURATION_S)
            for animation in self._display_animation.values()
        )

    @staticmethod
    def _x_values(times: list[object], is_datetime: bool,
                  origin: datetime | None) -> list[float]:
        if is_datetime:
            return [
                float(t.timestamp()) if isinstance(t, datetime) else float(t)
                for t in times
            ]
        return [float(t) for t in times]

    def _clip_for_display(self, vals: list[float],
                          times: list[object]) -> tuple[list[float], list[object]]:
        display_range = self._display_range_combo.currentData()
        if display_range == "all":
            return vals, times
        if isinstance(display_range, int) and times and isinstance(times[-1], datetime):
            cutoff = times[-1].timestamp() - display_range
            pairs = [
                (v, t)
                for v, t in zip(vals, times)
                if isinstance(t, datetime) and t.timestamp() >= cutoff
            ]
            if not pairs:
                return [], []
            out_vals, out_times = zip(*pairs)
            return list(out_vals), list(out_times)
        return vals[-WINDOW_SIZE:], times[-WINDOW_SIZE:]

    def _apply_ranges(
        self,
        x_vals: list[float],
        y_vals: list[float],
        live_x_max: float | None = None,
    ) -> None:
        if not x_vals or not y_vals:
            return
        x_min = min(x_vals)
        self._animation_x_min = x_min
        x_max = max(x_vals)
        if live_x_max is not None:
            x_max = max(x_max, live_x_max)
        min_span = MIN_TIME_SPAN_SECONDS if self._mode == "time" else MIN_INDEX_SPAN
        if x_max <= x_min:
            x_max = x_min + min_span
        current_span = x_max - x_min
        if current_span < min_span:
            x_min = max(0.0, x_max - min_span)
            x_max = x_min + min_span
        self._plot_widget.setXRange(x_min, x_max, padding=0.01)

        y_min = min(y_vals)
        y_max = max(y_vals)
        if y_max <= y_min:
            pad = max(1.0, abs(y_max) * 0.1)
        else:
            pad = max(1.0, (y_max - y_min) * 0.12)
        target_min = max(0.0, y_min - pad)
        target_max = y_max + pad
        if y_max >= CONCENTRATION_UPPER_BOUND:
            target_max = max(
                target_max,
                CONCENTRATION_UPPER_BOUND + Y_AXIS_TOP_HEADROOM,
            )
        target = (target_min, target_max)

        if self._display_y_range is None:
            self._display_y_range = target
        else:
            old_min, old_max = self._display_y_range
            target_min, target_max = target
            alpha = 0.25
            self._display_y_range = (
                (
                    target_min
                    if target_min < old_min
                    else old_min + alpha * (target_min - old_min)
                ),
                (
                    target_max
                    if target_max > old_max
                    else old_max + alpha * (target_max - old_max)
                ),
            )
        self._plot_widget.setYRange(*self._display_y_range, padding=0.0)

    def _update_live_x_range(self, live_x_max: float | None) -> None:
        """Advance the time axis with the animated tail using O(1) work."""
        if live_x_max is None or self._animation_x_min is None:
            return
        x_min = self._animation_x_min
        x_max = live_x_max
        min_span = MIN_TIME_SPAN_SECONDS if self._mode == "time" else MIN_INDEX_SPAN
        if x_max <= x_min:
            x_max = x_min + min_span
        if x_max - x_min < min_span:
            x_min = max(0.0, x_max - min_span)
            x_max = x_min + min_span
        self._plot_widget.setXRange(x_min, x_max, padding=0.01)

    def _record_redraw_duration(self, started: float) -> None:
        self._redraw_durations_ms.append(
            (time.perf_counter() - started) * 1000.0
        )

    @staticmethod
    def _performance_summary(values: deque[float]) -> tuple[float, float]:
        if not values:
            return 0.0, 0.0
        return sum(values) / len(values), max(values)

    def _maybe_log_performance(self) -> None:
        now = time.monotonic()
        elapsed = now - self._performance_window_started
        if elapsed < PERFORMANCE_LOG_INTERVAL_S:
            return

        sample_avg, sample_max = self._performance_summary(
            self._measurement_intervals_ms
        )
        table_avg, table_max = self._performance_summary(
            self._statistics_refresh_ms
        )
        redraw_avg, redraw_max = self._performance_summary(
            self._redraw_durations_ms
        )
        log.info(
            "Concentration UI performance: window_s=%.1f "
            "sample_interval_ms_avg=%.1f sample_interval_ms_max=%.1f "
            "statistics_refresh_ms_avg=%.2f statistics_refresh_ms_max=%.2f "
            "redraw_ms_avg=%.2f redraw_ms_max=%.2f animation_ticks=%d "
            "animation_fps=%.1f",
            elapsed,
            sample_avg,
            sample_max,
            table_avg,
            table_max,
            redraw_avg,
            redraw_max,
            self._animation_tick_count,
            self._animation_tick_count / elapsed,
        )
        self._measurement_intervals_ms.clear()
        self._statistics_refresh_ms.clear()
        self._redraw_durations_ms.clear()
        self._animation_tick_count = 0
        self._performance_window_started = now

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._opengl_validation_pending:
            QTimer.singleShot(0, self._validate_opengl_context)
        if self._statistics_table_dirty:
            self._refresh_statistics_table()
        if self._dirty:
            self._do_redraw()
        if self._has_active_animation() and not self._redraw_timer.isActive():
            self._redraw_timer.start()

    def _on_clear(self) -> None:
        self.clear_history()

    def _refresh_statistics_table(self) -> None:
        if not self.isVisible():
            self._statistics_table_dirty = True
            return

        refresh_started = time.perf_counter()
        snapshots = self._filtered_statistics_snapshots()
        rows = []
        highlighted_rows = []
        for row, snapshot in enumerate(snapshots):
            if snapshot.threshold_percent is None:
                threshold = "--"
                continuous = "--"
                cumulative = "--"
                status = "未配置阈值 / Not Set"
            else:
                threshold = f"{snapshot.threshold_percent:.3f}"
                continuous = f"{snapshot.continuous_seconds:.1f}"
                cumulative = f"{snapshot.cumulative_seconds:.1f}"
                status = "超限 / Above" if snapshot.is_above else "正常 / Normal"
            rows.append(
                (
                    self._group_label_by_id.get(
                        snapshot.group_label,
                        snapshot.group_label,
                    ),
                    snapshot.gas_name,
                    f"{snapshot.current_percent:.3f}",
                    threshold,
                    continuous,
                    cumulative,
                    str(snapshot.sample_count),
                    f"{snapshot.mean_percent:.3f}",
                    status,
                )
            )
            if snapshot.is_above:
                highlighted_rows.append(row)
        self._statistics_model.replace_rows(
            rows,
            highlighted_rows=highlighted_rows,
        )

        self._statistics_table_dirty = False
        self._statistics_refresh_ms.append(
            (time.perf_counter() - refresh_started) * 1000.0
        )
        self._maybe_log_performance()

    def _on_export_statistics(self) -> None:
        snapshots = self._filtered_statistics_snapshots()
        if not snapshots:
            QMessageBox.information(self, "导出 / Export", "没有统计数据可导出。")
            return

        ts = datetime.now().strftime("%Y-%m-%d-%H-%M")
        default_name = f"threshold_statistics_{ts}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出阈值统计摘要 / Export Threshold Statistics",
            self._last_export_dir or default_name,
            "CSV (*.csv)",
        )
        if not path:
            return
        self._last_export_dir = path

        try:
            self._write_statistics_csv(path, snapshots)
            QMessageBox.information(self, "导出成功 / Export OK", f"已保存至:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败 / Export Failed", str(exc))

    def _write_statistics_csv(self, path: str, snapshots: list) -> None:
        generated_at = self._format_export_time(datetime.now())
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "生成时间 / Generated At",
                "探头 / Probe",
                "气体 / Gas",
                "当前浓度 (%) / Current",
                "报警浓度 (%) / Threshold",
                "连续超限 (s) / Continuous",
                "累计超限 (s) / Cumulative",
                "统计窗口 (s) / Window",
                "样本数 / Samples",
                "平均值 (%) / Mean",
                "状态 / Status",
            ])
            for snapshot in snapshots:
                configured = snapshot.threshold_percent is not None
                writer.writerow([
                    generated_at,
                    self._group_label_by_id.get(
                        snapshot.group_label,
                        snapshot.group_label,
                    ),
                    snapshot.gas_name,
                    f"{snapshot.current_percent:.6f}",
                    f"{snapshot.threshold_percent:.6f}" if configured else "",
                    f"{snapshot.continuous_seconds:.3f}" if configured else "",
                    f"{snapshot.cumulative_seconds:.3f}" if configured else "",
                    self._statistics.window_seconds,
                    snapshot.sample_count,
                    f"{snapshot.mean_percent:.6f}",
                    (
                        "超限 / Above"
                        if snapshot.is_above
                        else "正常 / Normal" if configured
                        else "未配置阈值 / Not Set"
                    ),
                ])

    def _on_export(self) -> None:
        glabel = self._group_combo.currentData()
        is_all_groups = (glabel == "__all__")

        if is_all_groups:
            if not self._history:
                QMessageBox.information(self, "导出 / Export", "没有数据可导出。")
                return
        else:
            group_data = self._selected_group_data()
            if not group_data:
                QMessageBox.information(self, "导出 / Export", "没有数据可导出。")
                return

        ts = datetime.now().strftime("%Y-%m-%d-%H-%M")
        default_name = f"concentration_{ts}.csv"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出浓度数据 / Export Concentration Data",
            self._last_export_dir or default_name,
            "CSV (*.csv)",
        )
        if not path:
            return
        self._last_export_dir = path

        try:
            gas_names = sorted(self._gas_names)
            export_range = self._export_range_combo.currentData()
            if not is_all_groups:
                group_data = self._selected_group_data()
                raw_group_data = self._raw_history.get(glabel, {})
                export_data = group_data if self._export_smoothed else raw_group_data
                self._write_csv(path, export_data, gas_names, export_range)
            else:
                if not self._group_ids or not self._history:
                    QMessageBox.information(self, "导出", "没有数据。")
                    return
                export_history = self._history if self._export_smoothed else self._raw_history
                self._write_csv_all_groups(path, export_history, gas_names, export_range)

            QMessageBox.information(self, "导出成功 / Export OK", f"已保存至:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败 / Export Failed", str(exc))

    def _write_csv_all_groups(self, path: str, history: dict, gas_names: list[str],
                              export_range: object) -> None:
        """Export all groups using either smoothed or raw concentration history."""
        from datetime import datetime as dt_type
        is_datetime = False
        for group_id in self._group_ids:
            if group_id not in history:
                continue
            for _, (_, times) in history[group_id].items():
                if len(times) > 0:
                    is_datetime = isinstance(times[0], dt_type)
                    break

        columns: list[tuple[str, str, str]] = []  # (gas_name, group_label, header)
        for gas in gas_names:
            for group_id in self._group_ids:
                if group_id in history and gas in history[group_id]:
                    label = self._group_label_by_id.get(group_id, group_id)
                    columns.append((gas, group_id, f"{gas}({label})"))

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            header = ["时间 / Time" if is_datetime else "帧序号 / Index"]
            for _, _, h in columns:
                header.append(h)
            writer.writerow(header)

            prepared = []
            for gas, lbl, _ in columns:
                vals, times = history[lbl][gas]
                export_vals, export_times = self._filtered_pairs(vals, times, export_range)
                export_vals, export_times = self._resampled_pairs(export_vals, export_times)
                prepared.append((export_vals, export_times))

            max_len = max((len(vals) for vals, _ in prepared), default=0)
            for i in range(max_len):
                row = []
                t_val = ""
                for _, times in prepared:
                    if i < len(times):
                        if is_datetime:
                            t_val = self._format_export_time(times[i])
                        else:
                            t_val = str(int(times[i]))
                        break
                row.append(t_val)
                for vals, _ in prepared:
                    row.append(f"{vals[i]:.4f}" if i < len(vals) else "")
                writer.writerow(row)

    def _write_csv(self, path: str, group_data: dict, gas_names: list[str],
                   export_range: object) -> None:
        from datetime import datetime as dt_type
        is_datetime = False
        for _, (_, times) in group_data.items():
            if len(times) > 0:
                is_datetime = isinstance(times[0], dt_type)
                break
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            header = ["时间 / Time" if is_datetime else "帧序号 / Index"]
            for name in gas_names:
                header.append(name)
            writer.writerow(header)

            prepared = []
            for name in gas_names:
                export_vals, export_times = self._filtered_pairs(
                    *group_data.get(name, ([], [])),
                    export_range,
                )
                export_vals, export_times = self._resampled_pairs(export_vals, export_times)
                prepared.append((name, export_vals, export_times))

            max_len = max((len(vals) for _, vals, _ in prepared), default=0)
            for i in range(max_len):
                row = []
                t_val = ""
                for _, _, times in prepared:
                    if i < len(times):
                        if is_datetime:
                            t_val = self._format_export_time(times[i])
                        else:
                            t_val = str(int(times[i]))
                        break
                row.append(t_val)
                for _, vals, _ in prepared:
                    row.append(f"{vals[i]:.4f}" if i < len(vals) else "")
                writer.writerow(row)

    def _resampled_pairs(
        self,
        vals: list[float],
        times: list[object],
    ) -> tuple[list[float], list[object]]:
        if len(vals) < 2 or len(times) < 2 or not isinstance(times[0], datetime):
            return vals, times

        pairs = [(t.timestamp(), value) for value, t in zip(vals, times) if isinstance(t, datetime)]
        x = np.asarray([pair[0] for pair in pairs], dtype=float)
        y = np.asarray([pair[1] for pair in pairs], dtype=float)
        if len(x) < 2:
            return vals, times

        unique_x, unique_indices = np.unique(x, return_index=True)
        y = y[unique_indices]
        if len(unique_x) < 2 or unique_x[-1] <= unique_x[0]:
            return vals, times

        step = 1.0 / self._export_sample_rate_hz
        sample_count = int(np.floor((unique_x[-1] - unique_x[0]) / step)) + 1
        target_x = unique_x[0] + np.arange(sample_count, dtype=float) * step
        target_x = target_x[target_x <= unique_x[-1] + step * 1e-6]
        interpolator = PchipInterpolator(unique_x, y, extrapolate=False)
        target_y = np.asarray(interpolator(target_x), dtype=float)
        target_times = [datetime.fromtimestamp(value) for value in target_x]
        return target_y.tolist(), target_times

    @staticmethod
    def _format_export_time(value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    @staticmethod
    def _filtered_pairs(vals: list[float], times: list[object],
                        export_range: object) -> tuple[list[float], list[object]]:
        if export_range == "visible":
            return vals[-WINDOW_SIZE:], times[-WINDOW_SIZE:]
        if isinstance(export_range, int) and times and isinstance(times[-1], datetime):
            cutoff = times[-1].timestamp() - export_range
            pairs = [
                (v, t)
                for v, t in zip(vals, times)
                if isinstance(t, datetime) and t.timestamp() >= cutoff
            ]
            if not pairs:
                return [], []
            out_vals, out_times = zip(*pairs)
            return list(out_vals), list(out_times)
        return vals, times
