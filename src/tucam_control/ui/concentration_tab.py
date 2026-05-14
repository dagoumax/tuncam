# -*- coding: utf-8 -*-
"""Concentration tab — gas concentration display and trend chart (multi-group)."""

from __future__ import annotations

import csv
import time
from collections import defaultdict
from datetime import datetime

import matplotlib
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
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

_CJK_FONTS = ["Microsoft YaHei", "SimHei", "SimSun", "WenQuanYi Micro Hei", "Noto Sans CJK SC"]
_available = {f.name for f in fm.fontManager.ttflist}
_cjk_font = None
for _f in _CJK_FONTS:
    if _f in _available:
        _cjk_font = _f
        break
if _cjk_font:
    matplotlib.rcParams["font.family"] = ["sans-serif"]
    matplotlib.rcParams["font.sans-serif"] = [_cjk_font, "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]

_WINDOW_SIZE = 100


class ConcentrationTab(QWidget):
    """Fourth tab: current concentrations table + trend chart (multi-group)."""

    def __init__(self) -> None:
        super().__init__()
        # _history[group_label][gas_name] = (vals, times)
        self._history: dict[str, dict[str, tuple[list[float], list[object]]]] = {}
        self._gas_names: list[str] = []
        self._group_labels: list[str] = []
        self._batch_idx: int = 0
        self._mode: str = "time"
        self._dirty: bool = False
        self._last_export_dir: str = ""
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
        self._group_combo.currentIndexChanged.connect(self._redraw)
        ctrl_layout.addWidget(self._group_combo)

        ctrl_layout.addWidget(QLabel("气体 / Gas:"))
        self._gas_combo = QComboBox()
        self._gas_combo.addItem("全部 / All", "all")
        self._gas_combo.currentIndexChanged.connect(self._redraw)
        ctrl_layout.addWidget(self._gas_combo)

        btn_row = QHBoxLayout()
        self._btn_clear = QPushButton("清除历史 / Clear")
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_export = QPushButton("导出 CSV / Export")
        self._btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(self._btn_clear)
        btn_row.addWidget(self._btn_export)
        ctrl_layout.addLayout(btn_row)

        self._pt_label = QLabel("数据点 / Points: 0")
        ctrl_layout.addWidget(self._pt_label)

        left.addWidget(gb_ctrl)
        left.addStretch()
        layout.addLayout(left)

        # -- Right: trend chart --
        right = QVBoxLayout()
        self._fig = Figure(figsize=(8, 6), dpi=100)
        self._fig.set_tight_layout(True)
        self._ax = self._fig.add_subplot(111)
        self._canvas = FigureCanvasQTAgg(self._fig)
        right.addWidget(self._canvas, 1)

        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        self._toolbar.setMaximumHeight(30)
        right.addWidget(self._toolbar)

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

    def add_data_point(self, all_group_results: list, group_labels: list[str],
                       mode: str = "time") -> None:
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

        for glabel, gas_results in zip(group_labels, all_group_results):
            if glabel not in self._history:
                self._history[glabel] = {}
            group_map = self._history[glabel]
            for r in gas_results:
                if r.name not in group_map:
                    group_map[r.name] = ([], [])
                vals, times = group_map[r.name]
                vals.append(r.concentration * 100)
                times.append(t)

        self.set_group_labels(group_labels)
        self.set_gas_names([r.name for r in all_group_results[0]])

        if all_group_results:
            self._update_table(all_group_results[0])
        self._redraw()

    def clear_history(self) -> None:
        self._history.clear()
        self._batch_idx = 0
        self._table.setRowCount(0)
        self._total_label.setText("浓度总和 / Total: --")
        self._redraw()

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

    def _redraw(self) -> None:
        self._dirty = True
        if not self.isVisible():
            return
        self._dirty = False
        self._ax.clear()

        glabel = self._group_combo.currentData()
        selected_gas = self._gas_combo.currentData()
        is_all_groups = (glabel == "__all__")

        if is_all_groups and selected_gas == "all":
            # All groups + all gases: each line labeled "行X-Y GasName"
            is_datetime = False
            total_pts = 0
            color_idx = 0
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
                    if not is_datetime and len(times) > 0:
                        is_datetime = isinstance(times[0], datetime)
                    color = _COLORS[color_idx % len(_COLORS)]
                    color_idx += 1
                    line_label = f"{lbl} {name}"
                    self._ax.plot(times, vals, color=color, linewidth=0.8,
                                  label=line_label, marker=".", markersize=1)
                    total_pts += len(vals)
            self._ax.set_title("浓度变化 [全部行组] / All Groups & Gases")
            self._pt_label.setText(f"数据点 / Points: {total_pts}")

        if not is_all_groups:
            # Single group mode
            group_data = self._selected_group_data()
            if not group_data:
                self._canvas.draw_idle()
                return
            is_datetime, total_pts = self._plot_group_data(group_data, selected_gas, glabel)
        else:
            # All groups, single gas mode
            is_datetime = False
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
                if not is_datetime and len(times) > 0:
                    is_datetime = isinstance(times[0], datetime)
                color = _COLORS[i % len(_COLORS)]
                self._ax.plot(times, vals, color=color, linewidth=1.0,
                              label=lbl, marker=".", markersize=2)
                total_pts += len(vals)
            self._ax.set_title(f"浓度变化 [全部行组] / {selected_gas}")
            self._pt_label.setText(f"数据点 / Points: {total_pts}")

        if is_datetime:
            self._ax.set_xlabel("系统时间 / System Time")
            self._ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            self._fig.autofmt_xdate(rotation=30)
        else:
            self._ax.set_xlabel("帧序号 / Frame Index")

        if total_pts > _WINDOW_SIZE:
            if is_datetime:
                all_t = []
                if not is_all_groups:
                    for _, (_, times) in group_data.items():
                        all_t.extend(times)
                else:
                    for lbl in self._group_labels:
                        if lbl in self._history and selected_gas in self._history[lbl]:
                            _, times = self._history[lbl][selected_gas]
                            all_t.extend(times)
                all_t.sort()
                if len(all_t) >= _WINDOW_SIZE:
                    self._ax.set_xlim(left=all_t[-_WINDOW_SIZE], right=all_t[-1])
            else:
                self._ax.set_xlim(left=max(0, total_pts - _WINDOW_SIZE), right=total_pts - 0.5)

        self._ax.set_ylabel("浓度 / Concentration (%)")
        self._ax.grid(True, alpha=0.3)
        for label in self._ax.get_xticklabels() + self._ax.get_yticklabels():
            label.set_family("DejaVu Sans")
        has_artists = len(self._ax.get_legend_handles_labels()[0]) > 0
        show_legend = has_artists and (
            is_all_groups or selected_gas != "all" or len(self._gas_names) <= 5
        )
        if show_legend:
            self._ax.legend(loc="upper right", fontsize=7)
        elif has_artists:
            self._ax.legend(loc="upper right", fontsize=7, ncol=2)
        self._canvas.draw_idle()

    def _plot_group_data(self, group_data: dict, selected_gas: str, glabel: str) -> tuple[bool, int]:
        """Plot data for a single group. Returns (is_datetime, total_pts)."""
        is_datetime = False
        for _, (_, times) in group_data.items():
            if len(times) > 0:
                is_datetime = isinstance(times[0], datetime)
                break
        total_pts = sum(len(v) for v, _ in group_data.values())
        self._pt_label.setText(f"数据点 / Points: {total_pts}")

        if selected_gas == "all":
            for i, name in enumerate(self._gas_names):
                if name not in group_data:
                    continue
                vals, times = group_data[name]
                if len(vals) == 0:
                    continue
                self._ax.plot(times, vals, color=_COLORS[i % len(_COLORS)],
                              linewidth=1.0, label=name, marker=".", markersize=2)
            self._ax.set_title(f"浓度变化 [{glabel}] / All Gases")
        else:
            if selected_gas in group_data:
                vals, times = group_data[selected_gas]
                if len(vals) > 0:
                    idx = self._gas_names.index(selected_gas) if selected_gas in self._gas_names else 0
                    color = _COLORS[idx % len(_COLORS)]
                    self._ax.plot(times, vals, color=color, linewidth=1.2,
                                  label=selected_gas, marker=".", markersize=2)
            self._ax.set_title(f"浓度变化 [{glabel}] / {selected_gas}")
        return is_datetime, total_pts

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            self._redraw()

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
            from datetime import datetime as dt_type
            gas_names = sorted(self._gas_names)
            if not is_all_groups:
                group_data = self._selected_group_data()
                self._write_csv(path, group_data, gas_names)
            else:
                if not self._group_labels or not self._history:
                    QMessageBox.information(self, "导出", "没有数据。")
                    return
                self._write_csv_all_groups(path, gas_names)

            QMessageBox.information(self, "导出成功 / Export OK", f"已保存至:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败 / Export Failed", str(exc))

    def _write_csv_all_groups(self, path: str, gas_names: list[str]) -> None:
        """Export all groups: columns = Time + GasName(GroupLabel) for each."""
        from datetime import datetime as dt_type
        is_datetime = False
        for lbl in self._group_labels:
            if lbl not in self._history:
                continue
            for _, (_, times) in self._history[lbl].items():
                if len(times) > 0:
                    is_datetime = isinstance(times[0], dt_type)
                    break

        columns: list[tuple[str, str, str]] = []  # (gas_name, group_label, header)
        for gas in gas_names:
            for lbl in self._group_labels:
                if lbl in self._history and gas in self._history[lbl]:
                    columns.append((gas, lbl, f"{gas}({lbl})"))

        max_len = 0
        for gas, lbl, _ in columns:
            vals, _ = self._history[lbl][gas]
            max_len = max(max_len, len(vals))

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            header = ["时间 / Time" if is_datetime else "帧序号 / Index"]
            header += [h for _, _, h in columns]
            writer.writerow(header)

            for i in range(max_len):
                row = []
                t_val = ""
                for gas, lbl, _ in columns:
                    _, times = self._history[lbl][gas]
                    if i < len(times):
                        if is_datetime:
                            t_val = times[i].strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            t_val = str(int(times[i]))
                        break
                row.append(t_val)
                for gas, lbl, _ in columns:
                    vals, _ = self._history[lbl][gas]
                    row.append(f"{vals[i]:.4f}" if i < len(vals) else "")
                writer.writerow(row)

    def _write_csv(self, path: str, group_data: dict, gas_names: list[str]) -> None:
        from datetime import datetime as dt_type
        is_datetime = False
        for _, (_, times) in group_data.items():
            if len(times) > 0:
                is_datetime = isinstance(times[0], dt_type)
                break
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            header = ["时间 / Time" if is_datetime else "帧序号 / Index"]
            header += gas_names
            writer.writerow(header)

            max_len = max((len(vals) for vals, _ in group_data.values()), default=0)
            for i in range(max_len):
                row = []
                t_val = ""
                for name in gas_names:
                    if name in group_data:
                        _, times = group_data[name]
                        if i < len(times):
                            if is_datetime:
                                t_val = times[i].strftime("%Y-%m-%d %H:%M:%S")
                            else:
                                t_val = str(int(times[i]))
                            break
                row.append(t_val)
                for name in gas_names:
                    if name in group_data:
                        vals, _ = group_data[name]
                        row.append(f"{vals[i]:.4f}" if i < len(vals) else "")
                    else:
                        row.append("")
                writer.writerow(row)
