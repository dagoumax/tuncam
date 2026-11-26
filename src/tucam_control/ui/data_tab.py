# -*- coding: utf-8 -*-
"""Processed Raman spectra displayed with PyQtGraph."""

from __future__ import annotations

import logging
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QTimer, Qt, Signal, Slot
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

from ..calibration import apply_calibration, pixel_from_raman
from .plot_style import COLORS


log = logging.getLogger(__name__)


class DataTab(QWidget):
    """Third tab: high-frequency Raman spectrum display and cursor readout."""

    calibration_changed = Signal(object)
    opengl_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._data: np.ndarray | None = None
        self._baseline: np.ndarray | None = None
        self._row_labels: list[str] = []
        self._cursor_on = False
        self._cursor_idx = 0
        self._calib_coeffs: np.ndarray | None = None
        self._dirty = False
        self._controls_dirty = False
        self._opengl_enabled = False
        self._opengl_validation_pending = False
        self._fps_display_enabled = False
        self._fps_frame_count = 0
        self._fps_window_started = time.monotonic()
        self._plot_signature: tuple | None = None
        self._data_lines: list[pg.PlotCurveItem] = []
        self._baseline_lines: list[pg.PlotCurveItem] = []
        self._legend_signature: tuple[str, ...] = ()
        self._style_signature: tuple | None = None
        self._cursor_display_signature: tuple | None = None

        self._redraw_timer = QTimer(self)
        self._redraw_timer.setInterval(100)
        self._redraw_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._redraw_timer.timeout.connect(self._tick_redraw)
        self._setup_ui()

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
                "Raman plot backend selected: requested_opengl=%s viewport=%s",
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
            log.warning("Raman plot OpenGL setup failed; using software: %s", exc)
            if requested:
                self.opengl_failed.emit(f"Raman plot: {exc}")
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
            log.warning("Raman plot OpenGL validation failed: %s", message)
            self.set_opengl_enabled(False)
            self.opengl_failed.emit(f"Raman plot: {message}")
            return
        surface_format = context.format()
        log.info(
            "Raman plot OpenGL active: viewport=%s version=%s.%s profile=%s",
            type(viewport).__name__,
            surface_format.majorVersion(),
            surface_format.minorVersion(),
            surface_format.profile(),
        )

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("显示模式 / Display Mode:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("全部叠加 / All Overlaid", "all")
        self._mode_combo.addItem("单独显示 / Single Group", "single")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        controls.addWidget(self._mode_combo)

        self._group_combo = QComboBox()
        self._group_combo.setMaxVisibleItems(16)
        self._group_combo.setMinimumContentsLength(10)
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)
        controls.addWidget(self._group_combo)

        self._show_baseline_cb = QCheckBox("显示基线 / Show Baseline")
        self._show_baseline_cb.stateChanged.connect(self._do_redraw)

        self._cursor_toggle_cb = QCheckBox("光标 / Cursor")
        self._cursor_toggle_cb.stateChanged.connect(self._on_cursor_toggle)
        controls.addStretch()
        layout.addLayout(controls)

        actions = QHBoxLayout()
        actions.addWidget(self._show_baseline_cb)
        actions.addWidget(self._cursor_toggle_cb)
        self._calib_btn = QPushButton("校准 / Calib")
        self._calib_btn.setMaximumWidth(90)
        self._calib_btn.clicked.connect(self._on_calibrate)
        actions.addWidget(self._calib_btn)

        self._auto_range_btn = QPushButton("自动范围 / Auto Range")
        self._auto_range_btn.clicked.connect(self._auto_range)
        actions.addWidget(self._auto_range_btn)

        self._shape_label = QLabel("Shape: --")
        actions.addWidget(self._shape_label)
        actions.addStretch()
        layout.addLayout(actions)

        self._cursor_label = QLabel(
            "光标：勾选后左键定位，右键取消，左右键移动"
        )
        self._cursor_label.setStyleSheet("color: #666;")
        layout.addWidget(self._cursor_label)

        self._plot_widget = pg.PlotWidget()
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
        self._plot_item.setLabel("left", "强度 / Intensity")
        self._plot_item.setLabel("bottom", "拉曼位移 / Raman Shift (cm⁻¹)")
        self._plot_item.setMenuEnabled(True)
        self._legend = self._plot_item.addLegend(offset=(-10, 10))
        self._plot_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._plot_widget.scene().sigMouseClicked.connect(self._on_scene_click)
        self._plot_widget.installEventFilter(self)
        layout.addWidget(self._plot_widget, 1)

        self._cursor_vline = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#d62728", width=1),
        )
        self._cursor_hline = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=pg.mkPen("#d62728", width=1, style=Qt.PenStyle.DashLine),
        )
        self._cursor_markers = pg.ScatterPlotItem(size=7, brush="#d62728", pen=None)
        for item in (self._cursor_vline, self._cursor_hline, self._cursor_markers):
            self._plot_item.addItem(item, ignoreBounds=True)
            item.setVisible(False)

    def display_array(self, arr: np.ndarray) -> None:
        previous_rows = None if self._data is None else self._data.shape[0]
        self._data = np.asarray(arr)
        if self._data.shape[1] == 0:
            self._cursor_on = False
        else:
            self._cursor_idx = min(self._cursor_idx, self._data.shape[1] - 1)
        if previous_rows != self._data.shape[0]:
            self._controls_dirty = True
            self._apply_pending_controls()
        self._redraw()

    def set_baseline_data(self, baseline: np.ndarray | None) -> None:
        self._baseline = None if baseline is None else np.asarray(baseline)
        self._controls_dirty = True
        if self.isVisible():
            self._apply_pending_controls()
        self._redraw()

    def set_row_labels(self, labels: list[str]) -> None:
        labels = list(labels)
        if labels == self._row_labels:
            return
        self._row_labels = labels
        self._controls_dirty = True
        self._apply_pending_controls()

    def _apply_pending_controls(self) -> None:
        if not self._controls_dirty:
            return
        self._controls_dirty = False
        self._update_group_combo()
        self._show_baseline_cb.setEnabled(self._baseline is not None)
        if self._baseline is None:
            self._show_baseline_cb.setChecked(False)

    def set_calibration(self, coeffs: np.ndarray | None) -> None:
        self._calib_coeffs = None if coeffs is None else np.asarray(coeffs)
        self._cursor_on = False
        self._redraw()

    @Slot()
    def _on_calibrate(self) -> None:
        if self._data is None or self._data.shape[0] == 0:
            QMessageBox.warning(
                self,
                "校准 / Calibrate",
                "请先采集或载入一张图片。",
            )
            return
        from .calibration_dialog import CalibrationDialog

        dialog = CalibrationDialog(
            self._data,
            self._row_labels,
            self._calib_coeffs,
            self,
        )
        if dialog.exec():
            self._calib_coeffs = dialog.result_coeffs
            self.calibration_changed.emit(self._calib_coeffs)
            self._do_redraw()

    def _x_axis_values(self, n_cols: int) -> np.ndarray:
        return apply_calibration(np.arange(n_cols), self._calib_coeffs)

    def _on_cursor_toggle(self) -> None:
        if not self._cursor_toggle_cb.isChecked():
            self._cursor_on = False
        self._do_redraw()

    def _on_scene_click(self, event) -> None:
        if self._data is None or not self._cursor_toggle_cb.isChecked():
            return
        if not self._plot_item.sceneBoundingRect().contains(event.scenePos()):
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._cursor_on = False
            self._do_redraw()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self._plot_item.vb.mapSceneToView(event.scenePos())
        pixel = pixel_from_raman(float(point.x()), self._calib_coeffs)
        self._cursor_idx = max(
            0,
            min(int(round(pixel)), self._data.shape[1] - 1),
        )
        self._cursor_on = True
        self._plot_widget.setFocus()
        self._do_redraw()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._plot_widget and event.type() == QEvent.Type.KeyPress:
            if self._handle_cursor_key(event.key()):
                return True
        return super().eventFilter(watched, event)

    def _handle_cursor_key(self, key: int) -> bool:
        if not self._cursor_on or self._data is None:
            return False
        if key == Qt.Key.Key_Left:
            self._cursor_idx = max(0, self._cursor_idx - 1)
        elif key == Qt.Key.Key_Right:
            self._cursor_idx = min(self._data.shape[1] - 1, self._cursor_idx + 1)
        elif key == Qt.Key.Key_Escape:
            self._cursor_on = False
        else:
            return False
        self._do_redraw()
        return True

    def _update_group_combo(self) -> None:
        self._group_combo.blockSignals(True)
        current = self._group_combo.currentData()
        self._group_combo.clear()
        if self._data is not None:
            for index in range(self._data.shape[0]):
                label = (
                    self._row_labels[index]
                    if index < len(self._row_labels)
                    else f"组 {index + 1}"
                )
                self._group_combo.addItem(label, index)
            selected = self._group_combo.findData(current)
            if selected >= 0:
                self._group_combo.setCurrentIndex(selected)
        self._group_combo.blockSignals(False)

    def _on_mode_changed(self) -> None:
        self._group_combo.setEnabled(self._mode_combo.currentData() == "single")
        self._cursor_on = False
        self._do_redraw()

    def _on_group_changed(self) -> None:
        self._cursor_on = False
        self._do_redraw()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_pending_controls()
        if self._opengl_validation_pending:
            QTimer.singleShot(0, self._validate_opengl_context)
        if self._dirty:
            QTimer.singleShot(0, self._do_redraw)

    def _redraw(self) -> None:
        self._dirty = True
        if not self.isVisible():
            self._redraw_timer.stop()
            return
        if not self._redraw_timer.isActive():
            self._redraw_timer.start()

    def _tick_redraw(self) -> None:
        if not self.isVisible():
            self._redraw_timer.stop()
            return
        if self._dirty:
            self._do_redraw()
        else:
            self._redraw_timer.stop()

    def _ensure_items(
        self,
        items: list[pg.PlotCurveItem],
        count: int,
    ) -> None:
        while len(items) < count:
            curve = pg.PlotCurveItem()
            curve.setSegmentedLineMode("on")
            self._plot_item.addItem(curve)
            items.append(curve)
        for index, item in enumerate(items):
            visible = index < count
            if item.isVisible() != visible:
                item.setVisible(visible)

    def _do_redraw(self) -> None:
        if not self.isVisible():
            self._redraw_timer.stop()
            return
        self._dirty = False
        self._record_fps_frame()
        if self._data is None or self._data.size == 0:
            self._ensure_items(self._data_lines, 0)
            self._ensure_items(self._baseline_lines, 0)
            self._shape_label.setText("Shape: --")
            self._update_cursor_items([], np.array([], dtype=float))
            return

        mode = self._mode_combo.currentData()
        selected = self._group_combo.currentData()
        if mode == "single":
            selected = 0 if selected is None else int(selected)
            selected = max(0, min(selected, self._data.shape[0] - 1))
            indices = [selected]
        else:
            indices = list(range(self._data.shape[0]))
        show_baseline = (
            self._show_baseline_cb.isChecked()
            and self._baseline is not None
        )
        x_values = self._x_axis_values(self._data.shape[1])

        self._ensure_items(self._data_lines, len(indices))
        self._ensure_items(
            self._baseline_lines,
            len(indices) if show_baseline else 0,
        )
        labels = []
        style_signature = (tuple(indices), bool(show_baseline))
        for line_index, group_index in enumerate(indices):
            color = COLORS[group_index % len(COLORS)]
            label = (
                self._row_labels[group_index]
                if group_index < len(self._row_labels)
                else f"组 {group_index + 1}"
            )
            labels.append(label)
            curve = self._data_lines[line_index]
            if style_signature != self._style_signature:
                curve.setPen(pg.mkPen(color=color, width=1))
            curve.setData(
                x_values,
                self._data[group_index],
                skipFiniteCheck=True,
            )
            if show_baseline and self._baseline is not None:
                baseline = self._baseline_lines[line_index]
                if style_signature != self._style_signature:
                    baseline.setPen(
                        pg.mkPen(
                            color=color,
                            width=1,
                            style=Qt.PenStyle.DashLine,
                        )
                    )
                baseline.setData(
                    x_values,
                    self._baseline[group_index],
                    skipFiniteCheck=True,
                )
        self._style_signature = style_signature

        signature = tuple(labels)
        signature_changed = signature != self._legend_signature
        if signature_changed:
            self._legend.clear()
            for curve, label in zip(self._data_lines, labels):
                self._legend.addItem(curve, label)
            self._legend_signature = signature

        title = labels[0] if mode == "single" else "全部行组 / All Row Groups"
        if signature_changed:
            self._plot_item.setTitle(title)
        shape_text = f"{self._data.shape[0]} groups x {self._data.shape[1]} cols"
        if self._shape_label.text() != shape_text:
            self._shape_label.setText(shape_text)
        self._plot_signature = (
            mode,
            selected,
            show_baseline,
            self._data.shape,
            tuple(self._row_labels),
        )
        self._update_cursor_items(indices, x_values)

    def _update_cursor_items(
        self,
        indices: list[int],
        x_values: np.ndarray,
    ) -> None:
        visible = (
            self._cursor_on
            and self._cursor_toggle_cb.isChecked()
            and self._data is not None
            and len(x_values) > self._cursor_idx
        )
        if self._cursor_vline.isVisible() != visible:
            self._cursor_vline.setVisible(visible)
        if self._cursor_hline.isVisible():
            self._cursor_hline.setVisible(False)
        if self._cursor_markers.isVisible() != visible:
            self._cursor_markers.setVisible(visible)
        if not visible:
            if self._cursor_display_signature != (False,):
                self._cursor_markers.setData([], [])
                self._cursor_label.setText("光标：已关闭 / Cursor off")
                self._cursor_display_signature = (False,)
            return

        x_value = float(x_values[self._cursor_idx])
        y_values = [
            float(self._data[group_index, self._cursor_idx])
            for group_index in indices
        ]
        self._cursor_vline.setValue(x_value)
        self._cursor_markers.setData(
            [x_value] * len(y_values),
            y_values,
            brush=[
                pg.mkBrush(COLORS[group_index % len(COLORS)])
                for group_index in indices
            ],
            pen=None,
        )
        if len(indices) == 1:
            self._cursor_hline.setValue(y_values[0])
            self._cursor_hline.setVisible(True)
            self._cursor_label.setText(
                f"{x_value:.1f} cm⁻¹，强度 {y_values[0]:.1f}"
            )
        else:
            self._cursor_label.setText(
                f"{x_value:.1f} cm⁻¹，{len(y_values)} 个行组"
            )
        self._cursor_display_signature = (
            True,
            self._cursor_idx,
            tuple(indices),
            tuple(y_values),
        )

    def _auto_range(self) -> None:
        self._plot_item.enableAutoRange()
        self._plot_item.autoRange()
