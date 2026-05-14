# -*- coding: utf-8 -*-
"""Data tab — matplotlib-based plotting of processed spectra with cursor readout."""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ._mpl_style import COLORS, fix_tick_labels
from ..calibration import apply_calibration, pixel_from_raman


class DataTab(QWidget):
    """Third tab: line plot of processed row-group spectra with cursor readout."""

    calibration_changed = Signal(object)  # emits np.ndarray | None

    def __init__(self) -> None:
        super().__init__()
        self._data: np.ndarray | None = None
        self._baseline: np.ndarray | None = None
        self._row_labels: list[str] = []
        self._cursor_on: bool = False
        self._cursor_idx: int = 0
        self._cursor_group: int = 0
        self._calib_coeffs: np.ndarray | None = None
        self._cursor_line = None
        self._cursor_annot = None
        self._dirty: bool = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("显示模式 / Display Mode:"))

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("全部叠加 / All Overlaid", "all")
        self._mode_combo.addItem("单独显示 / Single Group", "single")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        ctrl.addWidget(self._mode_combo)

        self._group_combo = QComboBox()
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)
        ctrl.addWidget(self._group_combo)

        self._show_baseline_cb = QCheckBox("显示基线 / Show Baseline")
        self._show_baseline_cb.setChecked(False)
        self._show_baseline_cb.stateChanged.connect(self._redraw)
        ctrl.addWidget(self._show_baseline_cb)

        self._cursor_toggle_cb = QCheckBox("光标 / Cursor")
        self._cursor_toggle_cb.setChecked(False)
        self._cursor_toggle_cb.stateChanged.connect(self._on_cursor_toggle)
        ctrl.addWidget(self._cursor_toggle_cb)

        ctrl.addWidget(QLabel("    "))
        self._calib_btn = QPushButton("校准 / Calib")
        self._calib_btn.setMaximumWidth(80)
        self._calib_btn.clicked.connect(self._on_calibrate)
        ctrl.addWidget(self._calib_btn)

        self._shape_label = QLabel("Shape: --")
        ctrl.addWidget(self._shape_label)

        self._cursor_label = QLabel("光标: 勾选「光标」后左键定位 / 右键取消 / ←→移动")
        self._cursor_label.setStyleSheet("color: #aaa;")
        ctrl.addWidget(self._cursor_label)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        self._fig = Figure(figsize=(10, 6), dpi=100)
        self._fig.set_tight_layout(True)
        self._ax = self._fig.add_subplot(111)
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self._canvas, 1)

        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        self._toolbar.setMaximumHeight(30)
        layout.addWidget(self._toolbar)

        self._canvas.mpl_connect("button_press_event", self._on_click)
        self._canvas.mpl_connect("key_press_event", self._on_key)

    def display_array(self, arr: np.ndarray) -> None:
        self._data = arr
        self._cursor_on = False
        self._update_group_combo()
        self._redraw()

    def set_baseline_data(self, baseline: np.ndarray | None) -> None:
        self._baseline = baseline
        self._show_baseline_cb.setEnabled(baseline is not None)
        if baseline is None:
            self._show_baseline_cb.setChecked(False)
        self._redraw()

    def set_row_labels(self, labels: list[str]) -> None:
        self._row_labels = labels
        self._update_group_combo()

    def set_calibration(self, coeffs: np.ndarray | None) -> None:
        self._calib_coeffs = coeffs
        self._cursor_on = False
        self._redraw()

    @Slot()
    def _on_calibrate(self) -> None:
        if self._data is None or self._data.shape[0] == 0:
            QMessageBox.warning(self, "校准 / Calibrate", "请先采集或载入一张图片。")
            return
        from .calibration_dialog import CalibrationDialog
        dlg = CalibrationDialog(self._data, self._row_labels, self._calib_coeffs, self)
        if dlg.exec():
            self._calib_coeffs = dlg.result_coeffs
            self.calibration_changed.emit(self._calib_coeffs)
            self._redraw()

    def _x_axis_values(self, n_cols: int) -> np.ndarray:
        pixels = np.arange(n_cols)
        return apply_calibration(pixels, self._calib_coeffs)

    def _x_axis_label(self) -> str:
        return "拉曼位移 / Raman Shift ($cm^{-1}$)"

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    def _on_cursor_toggle(self) -> None:
        if not self._cursor_toggle_cb.isChecked():
            self._cursor_on = False
        self._redraw()

    def _on_click(self, event) -> None:
        try:
            if event.inaxes != self._ax or self._data is None:
                return
            if self._toolbar.mode != "":
                return
            if not self._cursor_toggle_cb.isChecked():
                return
            if event.button == MouseButton.RIGHT:
                self._cursor_on = False
                self._cursor_label.setText("光标: 已关闭 / Cursor off")
                self._redraw()
                return
            if event.button == MouseButton.LEFT:
                if event.xdata is None:
                    return
                n_data = self._data.shape[1]
                px = pixel_from_raman(float(event.xdata), self._calib_coeffs)
                self._cursor_idx = max(0, min(int(round(px)), n_data - 1))
                self._cursor_on = True
                self._canvas.setFocus()
                self._redraw()
        except Exception:
            pass

    def _on_key(self, event) -> None:
        if not self._cursor_on or self._data is None:
            return
        n = self._data.shape[1]
        if event.key == "left":
            self._cursor_idx = max(0, self._cursor_idx - 1)
        elif event.key == "right":
            self._cursor_idx = min(n - 1, self._cursor_idx + 1)
        elif event.key == "escape":
            self._cursor_on = False
        else:
            return
        self._redraw()

    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------

    def _update_group_combo(self) -> None:
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        if self._data is None:
            self._group_combo.blockSignals(False)
            return
        for i in range(self._data.shape[0]):
            label = self._row_labels[i] if i < len(self._row_labels) else f"组 {i + 1}"
            self._group_combo.addItem(label, i)
        self._group_combo.blockSignals(False)

    def _on_mode_changed(self) -> None:
        self._group_combo.setEnabled(self._mode_combo.currentData() == "single")
        self._cursor_on = False
        self._redraw()

    def _on_group_changed(self) -> None:
        self._cursor_on = False
        self._redraw()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            self._redraw()

    def _redraw(self) -> None:
        self._dirty = True
        if not self.isVisible():
            return
        self._dirty = False
        self._ax.clear()

        if self._data is None:
            self._canvas.draw_idle()
            return

        mode = self._mode_combo.currentData()
        show_bl = self._show_baseline_cb.isChecked() and self._baseline is not None

        if mode == "single":
            idx = self._group_combo.currentData()
            if idx is None or idx < 0:
                idx = 0
            self._plot_single(idx, show_bl)
        else:
            self._plot_all(show_bl)

        self._ax.set_xlabel(self._x_axis_label())
        self._ax.set_ylabel("强度 / Intensity")
        handles, labels = self._ax.get_legend_handles_labels()
        if len(handles) > 0:
            self._ax.legend(loc="upper right", fontsize=8)
        self._ax.grid(True, alpha=0.3)
        fix_tick_labels(self._ax)

        self._shape_label.setText(
            f"{self._data.shape[0]} groups x {self._data.shape[1]} cols"
            if self._data is not None else "Shape: --"
        )

        self._draw_cursor()
        self._canvas.draw_idle()

    def _draw_cursor(self) -> None:
        if not self._cursor_on or self._data is None:
            self._cursor_label.setText("光标: 已关闭 / Cursor off")
            return

        x = self._cursor_idx
        n_data = self._data.shape[1]
        if x < 0 or x >= n_data:
            return

        x_val = self._x_axis_values(n_data)[x]
        x_str = f"{x_val:.1f} $cm^{{-1}}$"

        mode = self._mode_combo.currentData()

        if mode == "single":
            g = self._group_combo.currentData()
            if g is None or g < 0:
                g = 0
            yy = self._data[g, x]
            self._ax.axvline(x=x_val, color="red", linewidth=0.8, alpha=0.6)
            self._ax.axhline(y=yy, color="red", linewidth=0.6, alpha=0.4, linestyle="--")
            self._ax.plot(x_val, yy, "ro", markersize=5)
            self._ax.annotate(
                f"{x_str}  =  {yy:.1f}",
                xy=(0.02, 0.96),
                xycoords="axes fraction",
                color="red",
                fontsize=9,
                verticalalignment="top",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.85),
            )
            self._cursor_label.setText(f"{x_str}, 值 {yy:.1f}  (←→移动, 右键取消)")
        else:
            ys = [self._data[i, x] for i in range(self._data.shape[0])]
            self._ax.axvline(x=x_val, color="red", linewidth=0.8, alpha=0.6)
            for i, y in enumerate(ys):
                color = COLORS[i % len(COLORS)]
                self._ax.axhline(y=y, color=color, linewidth=0.5, alpha=0.3, linestyle="--")
            text_lines = [f"{x_str}:"]
            for i, y in enumerate(ys):
                label = self._row_labels[i] if i < len(self._row_labels) else f"G{i+1}"
                text_lines.append(f"  {label}: {y:.1f}")
            self._ax.annotate(
                "\n".join(text_lines),
                xy=(0.02, 0.96),
                xycoords="axes fraction",
                color="red",
                fontsize=8,
                verticalalignment="top",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.85),
            )
            self._cursor_label.setText(f"{x_str}  (←→移动, 右键取消)")

    def _plot_single(self, idx: int, show_baseline: bool) -> None:
        if idx >= self._data.shape[0]:
            return
        label = self._row_labels[idx] if idx < len(self._row_labels) else f"组 {idx + 1}"
        spectrum = self._data[idx]
        x = self._x_axis_values(len(spectrum))
        self._ax.plot(x, spectrum, color=COLORS[0], linewidth=0.8, label=f"{label} (data)")

        if show_baseline and self._baseline is not None and idx < self._baseline.shape[0]:
            self._ax.plot(
                x, self._baseline[idx],
                color=COLORS[1], linewidth=1.2, linestyle="--", label=f"{label} (baseline)",
            )

        self._ax.set_title(label)

    def _plot_all(self, show_baseline: bool) -> None:
        n_groups = self._data.shape[0]
        for i in range(n_groups):
            label = self._row_labels[i] if i < len(self._row_labels) else f"组 {i + 1}"
            color = COLORS[i % len(COLORS)]
            spectrum = self._data[i]
            x = self._x_axis_values(len(spectrum))
            self._ax.plot(x, spectrum, color=color, linewidth=0.8, label=f"{label}")

            if show_baseline and self._baseline is not None and i < self._baseline.shape[0]:
                self._ax.plot(
                    x, self._baseline[i],
                    color=color, linewidth=1.0, linestyle="--", alpha=0.6,
                )

        self._ax.set_title("全部行组 / All Row Groups")
