# -*- coding: utf-8 -*-
"""Settings tab — exposure, temperature, fan, row groups, merge factor, gas config."""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..camera import CameraController
from ..data_processor import DataProcessor
from ..gas_analyzer import GasAnalyzer, GasConfig


class SettingsTab(QWidget):
    """Second tab: all configurable parameters for camera and data processing."""

    settings_changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._setup_ui()
        self._init_gas_table()

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
        self._arpls_enable_cb.setChecked(True)
        arpls_form.addRow("", self._arpls_enable_cb)

        self._arpls_mode_combo = QComboBox()
        self._arpls_mode_combo.addItem("原始数据 / Raw", "raw")
        self._arpls_mode_combo.addItem("校正后 / Corrected", "corrected")
        self._arpls_mode_combo.addItem("仅基线 / Baseline Only", "baseline")
        self._arpls_mode_combo.setCurrentIndex(1)
        arpls_form.addRow("输出模式 / Output Mode:", self._arpls_mode_combo)

        self._arpls_lam_spin = QDoubleSpinBox()
        self._arpls_lam_spin.setRange(1e2, 1e12)
        self._arpls_lam_spin.setDecimals(0)
        self._arpls_lam_spin.setValue(1e5)
        self._arpls_lam_spin.setSingleStep(1e5)
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

        # ---- Gas configuration ----
        gas_gb = QGroupBox("气体配置 / Gas Configuration")
        gas_layout = QVBoxLayout(gas_gb)

        self._gas_table = QTableWidget()
        self._gas_table.setColumnCount(5)
        self._gas_table.setHorizontalHeaderLabels(["名称 / Name", "位置 / Pos", "窗口 / Win", "系数 / Coeff", "拉曼位移 / Shift"])
        self._gas_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._gas_table.setMinimumHeight(120)
        gas_layout.addWidget(self._gas_table)

        gas_btn_row = QHBoxLayout()
        self._btn_add_gas = QPushButton("添加气体 / Add Gas")
        self._btn_del_gas = QPushButton("删除选中 / Delete Selected")
        self._btn_add_gas.clicked.connect(self._on_add_gas)
        self._btn_del_gas.clicked.connect(self._on_del_gas)
        gas_btn_row.addWidget(self._btn_add_gas)
        gas_btn_row.addWidget(self._btn_del_gas)
        gas_btn_row.addStretch()
        gas_layout.addLayout(gas_btn_row)

        layout.addWidget(gas_gb)

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

    def _init_gas_table(self) -> None:
        configs = GasAnalyzer.default_gases()
        for cfg in configs:
            self._add_gas_row(cfg.name, cfg.position, cfg.window, cfg.coefficient, cfg.raman_shift)

    def _add_gas_row(self, name: str = "", pos: int = 0, window: int = 15,
                     coeff: float = 1.0, shift: float = 0.0) -> None:
        row = self._gas_table.rowCount()
        self._gas_table.insertRow(row)
        self._gas_table.setItem(row, 0, QTableWidgetItem(name))
        self._gas_table.setItem(row, 1, QTableWidgetItem(str(pos)))
        self._gas_table.setItem(row, 2, QTableWidgetItem(str(window)))
        self._gas_table.setItem(row, 3, QTableWidgetItem(str(coeff)))
        self._gas_table.setItem(row, 4, QTableWidgetItem(str(shift) if shift else ""))

    def _get_gas_configs(self) -> list[GasConfig]:
        configs = []
        for row in range(self._gas_table.rowCount()):
            items = [
                (self._gas_table.item(row, c).text().strip() if self._gas_table.item(row, c) else "")
                for c in range(5)
            ]
            if not items[0]:
                continue
            try:
                shift_text = items[4].strip()
                configs.append(GasConfig(
                    name=items[0],
                    position=int(items[1]),
                    window=int(items[2]),
                    coefficient=float(items[3]),
                    raman_shift=float(shift_text) if shift_text else 0.0,
                ))
            except (ValueError, IndexError):
                continue
        return configs

    def update_gas_table(self, configs: list[GasConfig]) -> None:
        self._gas_table.setRowCount(0)
        for cfg in configs:
            self._add_gas_row(cfg.name, cfg.position, cfg.window, cfg.coefficient, cfg.raman_shift)

    def _on_add_gas(self) -> None:
        self._add_gas_row("New", 0, 15, 1.0, 0.0)

    def _on_del_gas(self) -> None:
        row = self._gas_table.currentRow()
        if row >= 0:
            self._gas_table.removeRow(row)
        else:
            QMessageBox.information(self, "提示 / Info", "请先点击选中要删除的行。")

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

        gas_configs = self._get_gas_configs()
        if not gas_configs:
            QMessageBox.warning(
                self,
                "气体配置为空 / No Gas Configured",
                "请至少添加一种气体。",
            )
            return

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
            "gas_configs": gas_configs,
        }
        self.settings_changed.emit(updates)
