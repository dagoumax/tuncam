# -*- coding: utf-8 -*-
"""Settings tab — exposure, temperature, fan, row groups, merge factor."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..camera import CameraController
from ..data_processor import DataProcessor


class SettingsTab(QWidget):
    """Second tab: all configurable parameters for camera and data processing."""

    settings_changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ---- Camera settings ----
        cam_gb = QGroupBox("相机设置 / Camera Settings")
        cam_form = QFormLayout(cam_gb)

        self._exp_spin = QDoubleSpinBox()
        self._exp_spin.setRange(0.01, 60000)
        self._exp_spin.setDecimals(2)
        self._exp_spin.setSuffix(" ms")
        self._exp_spin.setValue(1000.0)
        self._exp_spin.setSingleStep(100)
        cam_form.addRow("曝光时间 / Exposure Time:", self._exp_spin)

        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(-50, 50)
        self._temp_spin.setDecimals(1)
        self._temp_spin.setSuffix(" °C")
        self._temp_spin.setValue(-10.0)
        self._temp_spin.setSingleStep(1)
        cam_form.addRow("目标温度 / Target Temperature:", self._temp_spin)

        self._fan_combo = QComboBox()
        self._fan_combo.addItem("二档 / Gear 2 (默认)", 2)
        self._fan_combo.addItem("一档 / Gear 1", 1)
        self._fan_combo.addItem("三档 / Gear 3", 3)
        self._fan_combo.addItem("四档 / Gear 4", 4)
        self._fan_combo.setCurrentIndex(0)
        cam_form.addRow("风扇档位 / Fan Gear:", self._fan_combo)

        layout.addWidget(cam_gb)

        # ---- Data processing settings ----
        proc_gb = QGroupBox("数据处理 / Data Processing")
        proc_form = QFormLayout(proc_gb)

        self._row_groups_edit = QLineEdit()
        self._row_groups_edit.setPlaceholderText("e.g. 1-40, 91-130, 200-250")
        proc_form.addRow("行分组 / Row Groups:", self._row_groups_edit)

        self._merge_spin = QSpinBox()
        self._merge_spin.setRange(1, 256)
        self._merge_spin.setValue(1)
        self._merge_spin.setToolTip("1 = 不合并, 2 = 每2列取平均, ...")
        proc_form.addRow("列合并因子 / Merge Factor:", self._merge_spin)

        layout.addWidget(proc_gb)

        # ---- arPLS baseline correction ----
        arpls_gb = QGroupBox("基线校正 / Baseline Correction (arPLS)")
        arpls_form = QFormLayout(arpls_gb)

        self._arpls_enable_cb = QCheckBox("启用 / Enable")
        arpls_form.addRow("", self._arpls_enable_cb)

        self._arpls_mode_combo = QComboBox()
        self._arpls_mode_combo.addItem("原始数据 / Raw", "raw")
        self._arpls_mode_combo.addItem("校正后 / Corrected (data - baseline)", "corrected")
        self._arpls_mode_combo.addItem("仅基线 / Baseline Only", "baseline")
        arpls_form.addRow("输出模式 / Output Mode:", self._arpls_mode_combo)

        self._arpls_lam_spin = QDoubleSpinBox()
        self._arpls_lam_spin.setRange(1e2, 1e12)
        self._arpls_lam_spin.setDecimals(0)
        self._arpls_lam_spin.setValue(1e5)
        self._arpls_lam_spin.setSingleStep(1e5)
        self._arpls_lam_spin.setToolTip("越大基线越平滑")
        arpls_form.addRow("平滑参数 lam:", self._arpls_lam_spin)

        self._arpls_iter_spin = QSpinBox()
        self._arpls_iter_spin.setRange(1, 500)
        self._arpls_iter_spin.setValue(50)
        arpls_form.addRow("最大迭代 / max_iter:", self._arpls_iter_spin)

        self._arpls_tol_spin = QDoubleSpinBox()
        self._arpls_tol_spin.setRange(1e-12, 1e-2)
        self._arpls_tol_spin.setDecimals(10)
        self._arpls_tol_spin.setValue(1e-6)
        self._arpls_tol_spin.setSingleStep(1e-6)
        arpls_form.addRow("收敛容差 tol:", self._arpls_tol_spin)

        layout.addWidget(arpls_gb)

        # ---- Info labels ----
        info_gb = QGroupBox("参数范围 / Property Ranges")
        info_form = QFormLayout(info_gb)
        self._exp_range_label = QLabel("N/A")
        self._temp_range_label = QLabel("N/A")
        info_form.addRow("曝光范围 / Exposure Range:", self._exp_range_label)
        info_form.addRow("温度范围 / Temperature Range:", self._temp_range_label)
        layout.addWidget(info_gb)

        # ---- Apply button ----
        btn_row = QHBoxLayout()
        self._btn_apply = QPushButton("应用设置 / Apply Settings")
        self._btn_apply.setMinimumHeight(40)
        self._btn_apply.clicked.connect(self._on_apply)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_apply)
        layout.addLayout(btn_row)

        layout.addStretch()

    def update_ranges(self, camera: CameraController) -> None:
        try:
            mn, mx = camera.get_exposure_range()
            self._exp_range_label.setText(f"{mn:.2f} – {mx:.2f} ms")
            self._exp_spin.setRange(max(0.01, mn), mx)
        except Exception:
            self._exp_range_label.setText("N/A")
        try:
            mn, mx = camera.get_temperature_range()
            self._temp_range_label.setText(f"{mn:.1f} – {mx:.1f} °C")
            self._temp_spin.setRange(mn, mx)
        except Exception:
            self._temp_range_label.setText("N/A")

    @Slot()
    def _on_apply(self) -> None:
        raw_text = self._row_groups_edit.text().strip()
        if raw_text:
            groups = DataProcessor.parse_groups(raw_text)
            if not groups:
                QMessageBox.warning(
                    self,
                    "行分组格式错误 / Invalid Row Group Format",
                    f"无法解析：\n「{raw_text}」\n\n"
                    "请使用格式: 1-40, 91-130, 200-250\n"
                    "留空表示使用全部行。",
                )
                return
        else:
            groups = []

        updates = {
            "exposure_time_ms": self._exp_spin.value(),
            "temperature_c": self._temp_spin.value(),
            "fan_gear": self._fan_combo.currentData(),
            "row_groups_text": raw_text,
            "merge_factor": self._merge_spin.value(),
            "arpls_enabled": self._arpls_enable_cb.isChecked(),
            "arpls_mode": self._arpls_mode_combo.currentData(),
            "arpls_lam": self._arpls_lam_spin.value(),
            "arpls_max_iter": self._arpls_iter_spin.value(),
            "arpls_tol": self._arpls_tol_spin.value(),
        }
        self.settings_changed.emit(updates)
