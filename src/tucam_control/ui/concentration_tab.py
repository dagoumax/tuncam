# -*- coding: utf-8 -*-
"""Concentration tab — gas concentration display and trend chart (multi-group)."""

from __future__ import annotations

import csv
from datetime import datetime
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from ._mpl_style import COLORS, WINDOW_SIZE

MIN_TIME_SPAN_SECONDS = 30.0
MIN_INDEX_SPAN = 20.0
DISPLAY_ANIMATION_DURATION_S = 0.95
DISPLAY_ANIMATION_INTERVAL_MS = 33
DISPLAY_TAIL_SEGMENTS = 10


class ConcentrationTab(QWidget):
    """Fourth tab: current concentrations table + trend chart (multi-group)."""

    def __init__(self) -> None:
        super().__init__()
        # _history[group_label][gas_name] = (vals, times)
        self._history: dict[str, dict[str, tuple[list[float], list[object]]]] = {}
        self._raw_history: dict[str, dict[str, tuple[list[float], list[object]]]] = {}
        self._gas_names: list[str] = []
        self._group_labels: list[str] = []
        self._batch_idx: int = 0
        self._mode: str = "time"
        self._dirty: bool = False
        self._new_data: bool = False
        self._last_export_dir: str = ""
        self._display_y_range: tuple[float, float] | None = None
        self._export_smoothed: bool = True
        self._display_animation: dict[tuple[str, str], dict[str, float]] = {}

        self._redraw_timer = QTimer(self)
        self._redraw_timer.setInterval(DISPLAY_ANIMATION_INTERVAL_MS)
        self._redraw_timer.timeout.connect(self._tick_redraw)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)

        # -- Left: current concentrations --
        left = QVBoxLayout()

        gb_table = QGroupBox("当前浓度 / Current Concentration")
        tbl_layout = QVBoxLayout(gb_table)
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["气体 / Gas", "峰高 / Height", "浓度 / Conc"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumWidth(350)
        tbl_layout.addWidget(self._table)
        left.addWidget(gb_table)

        self._total_label = QLabel("浓度总和 / Total: --")
        left.addWidget(self._total_label)

        gb_ctrl = QGroupBox("图表控制 / Chart Control")
        ctrl_layout = QVBoxLayout(gb_ctrl)

        ctrl_layout.addWidget(QLabel("行组 / Row Group:"))
        self._group_combo = QComboBox()
        self._group_combo.currentIndexChanged.connect(self._do_redraw)
        ctrl_layout.addWidget(self._group_combo)

        ctrl_layout.addWidget(QLabel("气体 / Gas:"))
        self._gas_combo = QComboBox()
        self._gas_combo.addItem("全部 / All", "all")
        self._gas_combo.currentIndexChanged.connect(self._do_redraw)
        ctrl_layout.addWidget(self._gas_combo)

        ctrl_layout.addWidget(QLabel("显示范围 / Display Range:"))
        self._display_range_combo = QComboBox()
        self._display_range_combo.addItem("最近100点 / Last 100 points", "visible")
        self._display_range_combo.addItem("最近10分钟 / Last 10 min", 600)
        self._display_range_combo.addItem("最近1小时 / Last 1 hour", 3600)
        self._display_range_combo.addItem("全部历史 / All History", "all")
        self._display_range_combo.currentIndexChanged.connect(self._do_redraw)
        ctrl_layout.addWidget(self._display_range_combo)

        btn_row = QHBoxLayout()
        self._btn_clear = QPushButton("清除历史 / Clear")
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_export = QPushButton("导出 CSV / Export")
        self._btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(self._btn_clear)
        btn_row.addWidget(self._btn_export)
        ctrl_layout.addLayout(btn_row)

        ctrl_layout.addWidget(QLabel("导出范围 / Export Range:"))
        self._export_range_combo = QComboBox()
        self._export_range_combo.addItem("全部历史 / All History", "all")
        self._export_range_combo.addItem("最近10分钟 / Last 10 min", 600)
        self._export_range_combo.addItem("最近1小时 / Last 1 hour", 3600)
        self._export_range_combo.addItem("当前显示窗口 / Visible Window", "visible")
        ctrl_layout.addWidget(self._export_range_combo)

        self._pt_label = QLabel("数据点 / Points: 0")
        ctrl_layout.addWidget(self._pt_label)

        left.addWidget(gb_ctrl)
        left.addStretch()
        layout.addLayout(left)

        # -- Right: trend chart --
        right = QVBoxLayout()
        pg.setConfigOptions(antialias=True)
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground("w")
        self._plot_item = self._plot_widget.getPlotItem()
        self._plot_item.showGrid(x=True, y=True, alpha=0.25)
        self._plot_item.setLabel("left", "浓度 / Concentration (%)")
        self._plot_item.setLabel("bottom", "时间 / Time (s)")
        self._legend = self._plot_item.addLegend(offset=(-12, 12))
        right.addWidget(self._plot_widget, 1)

        layout.addLayout(right, 2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_gas_names(self, names: list[str]) -> None:
        self._gas_names = names
        self._update_gas_combo()

    def set_group_labels(self, labels: list[str]) -> None:
        self._group_labels = labels
        self._group_combo.blockSignals(True)
        current = self._group_combo.currentData()
        self._group_combo.clear()
        self._group_combo.addItem("全部行组 / All Groups", "__all__")
        for lbl in labels:
            self._group_combo.addItem(lbl, lbl)
        if current and self._group_combo.findData(current) >= 0:
            self._group_combo.setCurrentIndex(self._group_combo.findData(current))
        self._group_combo.blockSignals(False)

    def set_export_smoothed(self, enabled: bool) -> None:
        self._export_smoothed = enabled

    def add_data_point(
        self,
        all_group_results: list,
        group_labels: list[str],
        mode: str = "time",
        raw_group_results: list | None = None,
    ) -> None:
        """
        Add a measurement point for all row groups.

        *all_group_results*: list of list of GasResult (per group, per gas).
        *group_labels*: labels for each group.
        """
        self._mode = mode
        if mode == "index":
            t = float(self._batch_idx)
            self._batch_idx += 1
        else:
            t = datetime.now()

        self._append_results(self._history, all_group_results, group_labels, t)
        self._append_results(
            self._raw_history,
            raw_group_results if raw_group_results is not None else all_group_results,
            group_labels,
            t,
        )
        self._update_display_animation(all_group_results, group_labels)

        self.set_group_labels(group_labels)
        self.set_gas_names([r.name for r in all_group_results[0]])

        self._new_data = True
        if all_group_results:
            self._update_table(all_group_results[0])
        self._redraw()

    def clear_history(self) -> None:
        self._history.clear()
        self._raw_history.clear()
        self._display_animation.clear()
        self._batch_idx = 0
        self._display_y_range = None
        self._table.setRowCount(0)
        self._total_label.setText("浓度总和 / Total: --")
        self._do_redraw()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_gas_combo(self) -> None:
        self._gas_combo.blockSignals(True)
        self._gas_combo.clear()
        self._gas_combo.addItem("全部 / All", "all")
        for name in self._gas_names:
            self._gas_combo.addItem(name, name)
        self._gas_combo.blockSignals(False)

    def _selected_group_data(self) -> dict[str, tuple[list[float], list[object]]]:
        glabel = self._group_combo.currentData()
        if glabel == "__all__":
            return {}
        if glabel and glabel in self._history:
            return self._history[glabel]
        return {}

    def _update_table(self, gas_results: list) -> None:
        self._table.setRowCount(len(gas_results))
        total_conc = 0.0
        for i, r in enumerate(gas_results):
            total_conc += r.concentration
            detected_mark = "" if r.detected else " (未检出)"
            self._table.setItem(i, 0, QTableWidgetItem(f"{r.name}{detected_mark}"))
            self._table.setItem(i, 1, QTableWidgetItem(f"{r.peak_height:.1f}"))
            self._table.setItem(
                i, 2, QTableWidgetItem(f"{r.concentration * 100:.2f} %")
            )
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
        if not self._redraw_timer.isActive():
            self._redraw_timer.start()

    def _tick_redraw(self) -> None:
        """Periodic tick: redraw if dirty, stop timer if not."""
        if self._dirty or self._has_active_animation():
            self._do_redraw()
        else:
            self._redraw_timer.stop()

    def _do_redraw(self) -> None:
        if not self.isVisible():
            return
        self._dirty = False
        self._plot_item.clear()
        self._legend.clear()

        glabel = self._group_combo.currentData()
        selected_gas = self._gas_combo.currentData()
        is_all_groups = (glabel == "__all__")
        series: list[tuple[str, list[float], list[object], str, tuple[str, str]]] = []
        title = ""
        color_idx = 0

        if is_all_groups and selected_gas == "all":
            total_pts = 0
            for lbl in self._group_labels:
                if lbl not in self._history:
                    continue
                gdata = self._history[lbl]
                for name in self._gas_names:
                    if name not in gdata:
                        continue
                    vals, times = gdata[name]
                    if len(vals) == 0:
                        continue
                    color = COLORS[color_idx % len(COLORS)]
                    color_idx += 1
                    line_label = f"{lbl} {name}"
                    series.append((line_label, vals, times, color, (lbl, name)))
                    total_pts += len(vals)
            title = "浓度变化 [全部行组] / All Groups & Gases"
            self._pt_label.setText(f"数据点 / Points: {total_pts}")
        elif not is_all_groups:
            group_data = self._selected_group_data()
            if not group_data:
                self._plot_item.setTitle("")
                return
            series, total_pts, title = self._group_series(group_data, selected_gas, glabel)
            self._pt_label.setText(f"数据点 / Points: {total_pts}")
        else:
            total_pts = 0
            for i, lbl in enumerate(self._group_labels):
                if lbl not in self._history:
                    continue
                group_data = self._history[lbl]
                if selected_gas not in group_data:
                    continue
                vals, times = group_data[selected_gas]
                if len(vals) == 0:
                    continue
                color = COLORS[i % len(COLORS)]
                series.append((lbl, vals, times, color, (lbl, selected_gas)))
                total_pts += len(vals)
            title = f"浓度变化 [全部行组] / {selected_gas}"
            self._pt_label.setText(f"数据点 / Points: {total_pts}")

        self._new_data = False
        is_datetime = self._series_uses_datetime(series)
        self._plot_item.setTitle(title)
        self._plot_item.setLabel(
            "bottom",
            "时间 / Time (s)" if is_datetime else "帧序号 / Frame Index",
        )
        self._draw_series(series, is_datetime)

    def _group_series(
        self,
        group_data: dict,
        selected_gas: str,
        glabel: str,
    ) -> tuple[list[tuple[str, list[float], list[object], str, tuple[str, str]]], int, str]:
        """Build visible series for a single group."""
        series = []
        total_pts = sum(len(v) for v, _ in group_data.values())

        if selected_gas == "all":
            for i, name in enumerate(self._gas_names):
                if name not in group_data:
                    continue
                vals, times = group_data[name]
                if len(vals) == 0:
                    continue
                series.append((name, vals, times, COLORS[i % len(COLORS)], (glabel, name)))
            title = f"浓度变化 [{glabel}] / All Gases"
        else:
            if selected_gas in group_data:
                vals, times = group_data[selected_gas]
                if len(vals) > 0:
                    idx = self._gas_names.index(selected_gas) if selected_gas in self._gas_names else 0
                    color = COLORS[idx % len(COLORS)]
                    series.append((selected_gas, vals, times, color, (glabel, selected_gas)))
            title = f"浓度变化 [{glabel}] / {selected_gas}"
        return series, total_pts, title

    def _draw_series(
        self,
        series: list[tuple[str, list[float], list[object], str, tuple[str, str]]],
        is_datetime: bool,
    ) -> None:
        if not series:
            return

        time_origin = self._time_origin(series) if is_datetime else None
        all_x: list[float] = []
        all_y: list[float] = []
        show_legend = len(series) <= 24

        live_x_max = None

        for label, vals, times, color, series_key in series:
            clipped_vals, clipped_times = self._clip_for_display(vals, times)
            x_vals = self._x_values(clipped_times, is_datetime, time_origin)
            y_vals = [float(v) for v in clipped_vals]
            if not x_vals or not y_vals:
                continue

            if is_datetime and len(x_vals) >= 2:
                progress = self._time_aligned_display_progress(clipped_times)
                animated_last = self._current_display_value(series_key, y_vals[-1], progress)
                tail_count = max(3, DISPLAY_TAIL_SEGMENTS)
                tail_x_end = x_vals[-2] + (x_vals[-1] - x_vals[-2]) * progress
                tail_x = np.linspace(x_vals[-2], tail_x_end, tail_count).tolist()
                tail_y = np.linspace(y_vals[-2], animated_last, tail_count).tolist()
                x_vals = x_vals[:-2] + tail_x
                y_vals = y_vals[:-2] + tail_y
                live_x_max = tail_x_end if live_x_max is None else max(live_x_max, tail_x_end)
            elif is_datetime and len(x_vals) == 1:
                animated_last = self._current_display_value(series_key, y_vals[-1])
                y_vals[-1] = animated_last
                live_x_max = x_vals[-1] if live_x_max is None else max(live_x_max, x_vals[-1])

            all_x.extend(x_vals)
            all_y.extend(y_vals)
            pen = pg.mkPen(color=color, width=1.4)
            name = label if show_legend else None
            self._plot_item.plot(x_vals, y_vals, pen=pen, name=name)
            self._plot_item.plot(
                [x_vals[-1]],
                [y_vals[-1]],
                pen=None,
                symbol="o",
                symbolSize=6,
                symbolBrush=color,
                symbolPen=pg.mkPen(color=color),
            )

        self._apply_ranges(all_x, all_y, live_x_max)

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
                previous = float(vals[-2]) if len(vals) >= 2 else target
                start_value = self._current_display_value(key, previous)
                self._display_animation[key] = {
                    "from_y": start_value,
                    "to_y": target,
                    "start": now,
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
        if elapsed >= DISPLAY_ANIMATION_DURATION_S:
            return 1.0
        return elapsed / DISPLAY_ANIMATION_DURATION_S

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
            now - animation["start"] < DISPLAY_ANIMATION_DURATION_S
            for animation in self._display_animation.values()
        )

    @staticmethod
    def _x_values(times: list[object], is_datetime: bool,
                  origin: datetime | None) -> list[float]:
        if is_datetime and origin is not None:
            return [
                float((t - origin).total_seconds()) if isinstance(t, datetime) else float(t)
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
            target = (y_min - pad, y_max + pad)
        else:
            pad = max(1.0, (y_max - y_min) * 0.12)
            target = (max(0.0, y_min - pad), min(100.0, y_max + pad))

        if self._display_y_range is None:
            self._display_y_range = target
        else:
            old_min, old_max = self._display_y_range
            target_min, target_max = target
            alpha = 0.25
            self._display_y_range = (
                old_min + alpha * (target_min - old_min),
                old_max + alpha * (target_max - old_max),
            )
        self._plot_widget.setYRange(*self._display_y_range, padding=0.0)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            self._do_redraw()

    def _on_clear(self) -> None:
        self.clear_history()

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
                if not self._group_labels or not self._history:
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
        for lbl in self._group_labels:
            if lbl not in history:
                continue
            for _, (_, times) in history[lbl].items():
                if len(times) > 0:
                    is_datetime = isinstance(times[0], dt_type)
                    break

        columns: list[tuple[str, str, str]] = []  # (gas_name, group_label, header)
        for gas in gas_names:
            for lbl in self._group_labels:
                if lbl in history and gas in history[lbl]:
                    columns.append((gas, lbl, f"{gas}({lbl})"))

        max_len = 0
        for gas, lbl, _ in columns:
            vals, times = history[lbl][gas]
            filtered = self._filtered_pairs(vals, times, export_range)
            max_len = max(max_len, len(filtered[0]))

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
                prepared.append((export_vals, export_times))

            for i in range(max_len):
                row = []
                t_val = ""
                for _, times in prepared:
                    if i < len(times):
                        if is_datetime:
                            t_val = times[i].strftime("%Y-%m-%d %H:%M:%S")
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
                prepared.append((name, export_vals, export_times))

            max_len = max((len(vals) for _, vals, _ in prepared), default=0)
            for i in range(max_len):
                row = []
                t_val = ""
                for _, _, times in prepared:
                    if i < len(times):
                        if is_datetime:
                            t_val = times[i].strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            t_val = str(int(times[i]))
                        break
                row.append(t_val)
                for _, vals, _ in prepared:
                    row.append(f"{vals[i]:.4f}" if i < len(vals) else "")
                writer.writerow(row)

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
