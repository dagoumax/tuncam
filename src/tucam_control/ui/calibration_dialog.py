# -*- coding: utf-8 -*-
"""Calibration dialog — manually map pixel columns to Raman shift."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..calibration import CalibrationPoint, detect_peaks, fit_calibration


class CalibrationDialog(QDialog):
    """Modal dialog for Raman shift calibration."""

    def __init__(self, spectra: np.ndarray, group_labels: list[str],
                 existing_coeffs: np.ndarray | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("拉曼位移校准 / Raman Shift Calibration")
        self.resize(650, 500)
        self._spectra = spectra
        self._group_labels = group_labels
        self.result_coeffs: np.ndarray | None = existing_coeffs
        self._peaks: list[int] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Row group selection
        row_gb = QGroupBox("选择行组 / Select Row Group")
        row_layout = QHBoxLayout(row_gb)
        row_layout.addWidget(QLabel("行组:"))
        self._group_combo = QComboBox()
        for i, lbl in enumerate(self._group_labels):
            self._group_combo.addItem(lbl, i)
        row_layout.addWidget(self._group_combo)
        row_layout.addStretch()
        layout.addWidget(row_gb)

        # Peak detection
        peak_gb = QGroupBox("自动寻峰 / Auto Detect Peaks")
        peak_layout = QHBoxLayout(peak_gb)
        peak_layout.addWidget(QLabel("高度比例:"))
        self._height_spin = QDoubleSpinBox()
        self._height_spin.setRange(0.05, 1.0)
        self._height_spin.setSingleStep(0.05)
        self._height_spin.setValue(0.3)
        peak_layout.addWidget(self._height_spin)

        peak_layout.addWidget(QLabel("最小距离:"))
        self._dist_spin = QSpinBox()
        self._dist_spin.setRange(1, 200)
        self._dist_spin.setValue(10)
        peak_layout.addWidget(self._dist_spin)

        self._detect_btn = QPushButton("寻峰 / Detect")
        self._detect_btn.clicked.connect(self._on_detect)
        peak_layout.addWidget(self._detect_btn)
        peak_layout.addStretch()
        layout.addWidget(peak_gb)

        # Peak table
        tbl_gb = QGroupBox("校正点 / Calibration Points (填入拉曼位移 cm⁻¹)")
        tbl_layout = QVBoxLayout(tbl_gb)
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["像素 / Pixel", "强度 / Intensity", "拉曼位移 / Shift (cm⁻¹)"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl_layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        self._btn_clear_pts = QPushButton("清空 / Clear")
        self._btn_clear_pts.clicked.connect(self._on_clear)
        btn_row.addWidget(self._btn_clear_pts)
        btn_row.addStretch()
        tbl_layout.addLayout(btn_row)
        layout.addWidget(tbl_gb)

        # Fit settings
        fit_gb = QGroupBox("拟合 / Fit")
        fit_layout = QHBoxLayout(fit_gb)
        fit_layout.addWidget(QLabel("多项式阶数:"))
        self._degree_spin = QSpinBox()
        self._degree_spin.setRange(1, 4)
        self._degree_spin.setValue(2)
        fit_layout.addWidget(self._degree_spin)

        self._fit_btn = QPushButton("执行校准 / Calibrate")
        self._fit_btn.clicked.connect(self._on_calibrate)
        fit_layout.addWidget(self._fit_btn)

        self._fit_label = QLabel("")
        fit_layout.addWidget(self._fit_label)
        fit_layout.addStretch()
        layout.addWidget(fit_gb)

        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _get_current_spectrum(self) -> np.ndarray | None:
        idx = self._group_combo.currentData()
        if idx is None or idx >= len(self._spectra):
            return None
        return self._spectra[idx]

    @Slot()
    def _on_detect(self) -> None:
        spec = self._get_current_spectrum()
        if spec is None:
            return
        self._peaks = detect_peaks(
            spec,
            height_ratio=self._height_spin.value(),
            distance=self._dist_spin.value(),
        )
        self._populate_table(spec)

    def _populate_table(self, spec: np.ndarray) -> None:
        self._table.setRowCount(len(self._peaks))
        for i, p in enumerate(self._peaks):
            self._table.setItem(i, 0, QTableWidgetItem(str(p)))
            self._table.setItem(i, 1, QTableWidgetItem(f"{spec[p]:.1f}"))
            # Keep existing shift values if they exist
            existing = self._table.item(i, 2)
            if existing is None or not existing.text().strip():
                self._table.setItem(i, 2, QTableWidgetItem(""))

    @Slot()
    def _on_clear(self) -> None:
        self._table.setRowCount(0)
        self._peaks = []

    @Slot()
    def _on_calibrate(self) -> None:
        points: list[CalibrationPoint] = []
        for row in range(self._table.rowCount()):
            pixel_item = self._table.item(row, 0)
            shift_item = self._table.item(row, 2)
            if pixel_item is None or shift_item is None:
                continue
            try:
                px = int(pixel_item.text().strip())
                rs = float(shift_item.text().strip())
                if rs == 0.0 and shift_item.text().strip() == "":
                    continue
                points.append(CalibrationPoint(pixel=px, raman_shift=rs))
            except ValueError:
                continue

        if len(points) < self._degree_spin.value() + 1:
            QMessageBox.warning(
                self, "校准失败 / Calibration Failed",
                f"至少需要 {self._degree_spin.value() + 1} 个有效的校正点。"
                f"\n当前: {len(points)} 个。",
            )
            return

        try:
            coeffs = fit_calibration(points, self._degree_spin.value())
            self.result_coeffs = coeffs
            # Show fit info
            p_str = " + ".join(f"{c:.4g}x^{i}" for i, c in enumerate(reversed(coeffs)) if abs(c) > 1e-10)
            self._fit_label.setText(f"已拟合: {p_str}")
            self._fit_label.setStyleSheet("color: green;")
        except Exception as exc:
            QMessageBox.critical(self, "拟合失败", str(exc))

    @Slot()
    def _on_accept(self) -> None:
        if self.result_coeffs is None:
            QMessageBox.warning(
                self, "未校准", "请先点击「执行校准」。\nPlease click Calibrate first."
            )
            return
        self.accept()
