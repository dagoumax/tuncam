# -*- coding: utf-8 -*-
"""Concentration tab — gas concentration display and trend chart."""

from __future__ import annotations

import time
from collections import defaultdict

import matplotlib
import matplotlib.font_manager as fm
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
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


class ConcentrationTab(QWidget):
    """Fourth tab: current concentrations table + trend chart."""

    def __init__(self) -> None:
        super().__init__()
        self._gas_names: list[str] = []
        self._history: dict[str, tuple[list[float], list[float]]] = defaultdict(
            lambda: ([], [])
        )
        self._batch_idx: int = 0
        self._mode: str = "time"    # "time" or "index"
        self._start_time: float = time.time()
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
        self._btn_clear = QPushButton("清除历史 / Clear History")
        self._btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(self._btn_clear)
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
        """
        Add a new measurement point.

        *mode*: ``"time"`` = elapsed seconds (camera), ``"index"`` = frame number (batch).
        """
        self._mode = mode
        if mode == "index":
            t = float(self._batch_idx)
            self._batch_idx += 1
        else:
            t = time.time() - self._start_time
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
        self._ax.clear()

        selected = self._gas_combo.currentData()

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

        xlabel = "帧序号 / Frame Index" if self._mode == "index" else "时间 / Time (s)"
        self._ax.set_xlabel(xlabel)
        self._ax.set_ylabel("浓度 / Concentration (%)")
        self._ax.grid(True, alpha=0.3)
        if selected != "all" or len(self._gas_names) <= 5:
            self._ax.legend(loc="upper right", fontsize=8)
        self._canvas.draw_idle()

    def _on_clear(self) -> None:
        self.clear_history()
