# -*- coding: utf-8 -*-
"""Concentration tab — gas concentration display and trend chart."""

from __future__ import annotations

import csv
import time
from collections import defaultdict
from datetime import datetime, timedelta

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
    """Fourth tab: current concentrations table + trend chart."""

    def __init__(self) -> None:
        super().__init__()
        self._gas_names: list[str] = []
        self._history: dict[str, tuple[list[float], list[object]]] = defaultdict(
            lambda: ([], [])
        )
        self._batch_idx: int = 0
        self._mode: str = "time"
        self._start_time: float = time.time()
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
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("气体 / Gas:"))
        self._gas_combo = QComboBox()
        self._gas_combo.addItem("全部 / All", "all")
        self._gas_combo.currentIndexChanged.connect(self._redraw)
        ctrl_row.addWidget(self._gas_combo)
        ctrl_layout.addLayout(ctrl_row)

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
        self._gas_combo.blockSignals(True)
        self._gas_combo.clear()
        self._gas_combo.addItem("全部 / All", "all")
        for name in names:
            self._gas_combo.addItem(name, name)
        self._gas_combo.blockSignals(False)

    def add_data_point(self, gas_results: list, mode: str = "time") -> None:
        self._mode = mode
        if mode == "index":
            t = float(self._batch_idx)
            self._batch_idx += 1
        else:
            t = datetime.now()
        for r in gas_results:
            vals, times = self._history[r.name]
            vals.append(r.concentration * 100)
            times.append(t)

        self._update_table(gas_results)
        self._redraw()

    def clear_history(self) -> None:
        self._history.clear()
        self._batch_idx = 0
        self._start_time = time.time()
        self._table.setRowCount(0)
        self._total_label.setText("浓度总和 / Total: --")
        self._redraw()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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

        selected = self._gas_combo.currentData()
        is_time_mode = self._mode == "time"

        if selected == "all":
            for i, name in enumerate(self._gas_names):
                vals, times = self._history[name]
                if len(vals) == 0:
                    continue
                self._ax.plot(times, vals, color=_COLORS[i % len(_COLORS)],
                              linewidth=1.0, label=name, marker=".", markersize=2)
            self._ax.set_title("所有气体浓度变化 / All Gas Concentrations")
        elif selected in self._gas_names:
            vals, times = self._history[selected]
            if len(vals) > 0:
                color = _COLORS[self._gas_names.index(selected) % len(_COLORS)]
                self._ax.plot(times, vals, color=color, linewidth=1.2,
                              label=selected, marker=".", markersize=2)
            self._ax.set_title(f"气体浓度变化 / {selected} Concentration")

        total_pts = sum(len(v) for v, _ in self._history.values())
        self._pt_label.setText(f"数据点 / Points: {total_pts}")

        if is_time_mode:
            self._ax.set_xlabel("系统时间 / System Time")
            self._ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            self._fig.autofmt_xdate(rotation=30)
        else:
            self._ax.set_xlabel("帧序号 / Frame Index")

        if total_pts > _WINDOW_SIZE:
            if is_time_mode:
                all_times = []
                for _, times in self._history.values():
                    all_times.extend(times)
                all_times.sort()
                if len(all_times) >= _WINDOW_SIZE:
                    left_bound = all_times[-_WINDOW_SIZE]
                    right_bound = all_times[-1]
                    self._ax.set_xlim(left=left_bound, right=right_bound)
            else:
                self._ax.set_xlim(left=max(0, total_pts - _WINDOW_SIZE), right=total_pts - 0.5)

        self._ax.set_ylabel("浓度 / Concentration (%)")
        self._ax.grid(True, alpha=0.3)
        has_artists = len(self._ax.get_legend_handles_labels()[0]) > 0
        if has_artists and (selected != "all" or len(self._gas_names) <= 5):
            self._ax.legend(loc="upper right", fontsize=8)
        self._canvas.draw_idle()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            self._redraw()

    def _on_clear(self) -> None:
        self.clear_history()

    def _on_export(self) -> None:
        total_pts = sum(len(v) for v, _ in self._history.values())
        if not self._gas_names or total_pts == 0:
            QMessageBox.information(self, "导出 / Export", "没有数据可导出。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出浓度数据 / Export Concentration Data",
            self._last_export_dir or "concentration.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        self._last_export_dir = path

        try:
            is_time_mode = self._mode == "time"
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                header = ["时间 / Time" if is_time_mode else "帧序号 / Index"]
                header += self._gas_names
                writer.writerow(header)

                max_len = max((len(vals) for vals, _ in self._history.values()), default=0)
                for i in range(max_len):
                    row = []
                    # Grab time from the first gas that has this index
                    t_val = ""
                    for name in self._gas_names:
                        vals, times = self._history[name]
                        if i < len(times):
                            if is_time_mode:
                                t_val = times[i].strftime("%Y-%m-%d %H:%M:%S")
                            else:
                                t_val = str(int(times[i]))
                            break
                    row.append(t_val)
                    for name in self._gas_names:
                        vals, _ = self._history[name]
                        row.append(f"{vals[i]:.4f}" if i < len(vals) else "")
                    writer.writerow(row)

            QMessageBox.information(self, "导出成功 / Export OK", f"已保存至:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败 / Export Failed", str(exc))
