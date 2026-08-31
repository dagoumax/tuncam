# -*- coding: utf-8 -*-
"""Settings tab — exposure, temperature, fan, row groups, merge factor, gas config."""

from __future__ import annotations

import ipaddress

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..camera_process import ProcessCameraController
from ..camera_types import CameraInfo
from ..data_processor import DataProcessor
from ..gas_analyzer import GasAnalyzer, GasConfig
from ..row_groups import (
    MAX_ROW_GROUPS,
    describe_row_groups,
    normalize_row_group_names,
)
from ..remote_server import generate_remote_token
from .table_models import TableDataModel


DEFAULT_SAVE_DIR = "data"


class SettingsTab(QWidget):
    """Second tab: all configurable parameters for camera and data processing."""

    settings_changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._row_groups: list[tuple[int, int]] = []
        self._row_group_names: dict[str, str] = {}
        self._setup_ui()
        self._init_gas_table()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.setStyleSheet(
            """
            SettingsTab { font-size: 14px; }
            SettingsTab QGroupBox {
                font-size: 15px;
                font-weight: 600;
                border: 1px solid palette(mid);
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
            }
            SettingsTab QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            SettingsTab QLabel, SettingsTab QCheckBox { font-size: 14px; }
            SettingsTab QLineEdit, SettingsTab QPlainTextEdit, SettingsTab QComboBox,
            SettingsTab QSpinBox, SettingsTab QDoubleSpinBox {
                min-height: 32px;
                font-size: 14px;
                padding: 1px 6px;
            }
            SettingsTab QPushButton {
                min-height: 32px;
                font-size: 14px;
                padding: 3px 12px;
            }
            SettingsTab QTableView { font-size: 14px; }
            SettingsTab QHeaderView::section {
                min-height: 30px;
                font-size: 13px;
                font-weight: 600;
                padding: 5px;
            }
            """
        )

        self._settings_scroll = QScrollArea()
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_content = QWidget()
        settings_layout = QGridLayout(settings_content)
        settings_layout.setContentsMargins(2, 2, 8, 8)
        settings_layout.setHorizontalSpacing(14)
        settings_layout.setVerticalSpacing(14)
        settings_layout.setColumnStretch(0, 1)
        settings_layout.setColumnStretch(1, 1)
        self._settings_scroll.setWidget(settings_content)
        layout.addWidget(self._settings_scroll, 1)

        device_column = QWidget()
        device_column_layout = QVBoxLayout(device_column)
        device_column_layout.setContentsMargins(0, 0, 0, 0)
        device_column_layout.setSpacing(14)

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
        self._temp_spin.setKeyboardTracking(False)
        cam_form.addRow("目标温度 / Target Temperature:", self._temp_spin)

        self._fan_combo = QComboBox()
        self._fan_combo.addItem("高速 / High (默认)", 0)
        self._fan_combo.addItem("中速 / Medium", 1)
        self._fan_combo.addItem("低速 / Low", 2)
        self._fan_combo.setCurrentIndex(0)
        cam_form.addRow("风扇档位 / Fan Gear:", self._fan_combo)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("HDR (默认)", 0)
        self._mode_combo.addItem("Std_High (高灵敏度)", 1)
        self._mode_combo.addItem("Std_Low (高满阱)", 2)
        cam_form.addRow("工作模式 / Working Mode:", self._mode_combo)

        self._auto_save_cb = QCheckBox("采集后自动存储 / Auto Save After Capture")
        cam_form.addRow("", self._auto_save_cb)

        save_path_row = QHBoxLayout()
        self._save_dir_edit = QLineEdit(DEFAULT_SAVE_DIR)
        self._btn_browse = QPushButton("浏览...")
        self._btn_browse.clicked.connect(self._on_browse_save_dir)
        save_path_row.addWidget(self._save_dir_edit)
        save_path_row.addWidget(self._btn_browse)
        cam_form.addRow("存储路径 / Save Path:", save_path_row)

        settings_layout.addWidget(cam_gb, 0, 0)

        # ---- Data processing settings ----
        proc_gb = QGroupBox("数据处理 / Data Processing")
        proc_form = QFormLayout(proc_gb)

        row_group_controls = QHBoxLayout()
        self._row_groups_summary = QLineEdit()
        self._row_groups_summary.setReadOnly(True)
        self._row_groups_summary.setPlaceholderText("未配置，使用全部图像")
        self._manage_row_groups_button = QPushButton("管理行组...")
        self._manage_row_groups_button.clicked.connect(
            self._open_row_group_manager
        )
        row_group_controls.addWidget(self._row_groups_summary, 1)
        row_group_controls.addWidget(self._manage_row_groups_button)
        proc_form.addRow("行组配置 / Row Groups:", row_group_controls)

        self._row_aggregation_combo = QComboBox()
        self._row_aggregation_combo.addItem("求和 / Sum (默认)", DataProcessor.ROW_AGGREGATION_SUM)
        self._row_aggregation_combo.addItem("平均 / Mean", DataProcessor.ROW_AGGREGATION_MEAN)
        proc_form.addRow("行组计算 / Row Aggregation:", self._row_aggregation_combo)

        self._merge_spin = QSpinBox()
        self._merge_spin.setRange(1, 256)
        self._merge_spin.setValue(1)
        self._merge_spin.setToolTip("1 = 不合并, 2 = 每2列取平均, ...")
        proc_form.addRow("列合并因子 / Merge Factor:", self._merge_spin)

        self._threshold_sigma_spin = QDoubleSpinBox()
        self._threshold_sigma_spin.setRange(0.10, 10.00)
        self._threshold_sigma_spin.setDecimals(2)
        self._threshold_sigma_spin.setSingleStep(0.05)
        self._threshold_sigma_spin.setValue(3.0)
        self._threshold_sigma_spin.setToolTip(
            "检出阈值 = 此系数 × 排除已标记气体峰后的稳健噪声；"
            "数值越低越容易检出弱峰。"
        )
        proc_form.addRow("检出阈值系数 / Detection Threshold:", self._threshold_sigma_spin)

        self._smooth_combo = QComboBox()
        self._smooth_combo.addItem("关闭 / Off", "off")
        self._smooth_combo.addItem("更平滑 / Extra Smooth", "extra_smooth")
        self._smooth_combo.addItem("稳健 / Steady", "steady")
        self._smooth_combo.addItem("均衡 / Balanced (默认)", "balanced")
        self._smooth_combo.addItem("灵敏 / Responsive", "responsive")
        self._smooth_combo.setCurrentIndex(3)
        proc_form.addRow("浓度平滑 / Concentration Smoothing:", self._smooth_combo)

        self._batch_interval_spin = QSpinBox()
        self._batch_interval_spin.setRange(100, 60000)
        self._batch_interval_spin.setSingleStep(100)
        self._batch_interval_spin.setValue(1000)
        self._batch_interval_spin.setSuffix(" ms")
        proc_form.addRow("批量测试间隔 / Batch Interval:", self._batch_interval_spin)

        self._export_sample_rate_spin = QSpinBox()
        self._export_sample_rate_spin.setRange(1, 1000)
        self._export_sample_rate_spin.setValue(1000)
        self._export_sample_rate_spin.setSuffix(" Hz")
        proc_form.addRow("采样率 / Sample Rate:", self._export_sample_rate_spin)

        self._plot_opengl_cb = QCheckBox(
            "启用 OpenGL 绘图加速 / Enable OpenGL Rendering"
        )
        self._plot_opengl_cb.setChecked(True)
        self._plot_opengl_cb.setToolTip(
            "使用显卡加速拉曼和浓度曲线；如果驱动或远程桌面不兼容，"
            "程序会自动切回软件绘制。"
        )
        proc_form.addRow("绘图加速 / Plot Acceleration:", self._plot_opengl_cb)

        self._show_plot_fps_cb = QCheckBox(
            "显示实时绘图帧率 / Show Plot FPS"
        )
        self._show_plot_fps_cb.setChecked(False)
        self._show_plot_fps_cb.setToolTip(
            "在拉曼图和浓度图左上角显示最近一秒的实际绘图刷新率。"
        )
        proc_form.addRow("帧率显示 / FPS Display:", self._show_plot_fps_cb)

        settings_layout.addWidget(proc_gb, 0, 1)

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

        settings_layout.addWidget(arpls_gb, 1, 0)

        # ---- Gas configuration ----
        gas_gb = QGroupBox("气体配置 / Gas Configuration")
        gas_layout = QVBoxLayout(gas_gb)

        self._gas_table = QTableView()
        self._gas_model = TableDataModel([
            "名称 / Name",
            "位置 / Pos",
            "窗口 / Win",
            "系数 / Coeff",
            "拉曼位移 / Shift",
            "报警浓度 (%) / Alarm Conc",
            "检出阈值 / Detection Sigma",
        ], editable_columns=range(7), parent=self._gas_table)
        self._gas_table.setModel(self._gas_model)
        gas_header = self._gas_table.horizontalHeader()
        gas_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        gas_header.setMinimumSectionSize(90)
        for column, width in enumerate((150, 100, 100, 110, 150, 180, 190)):
            self._gas_table.setColumnWidth(column, width)
        self._gas_table.verticalHeader().setDefaultSectionSize(34)
        self._gas_table.setMinimumHeight(240)
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

        settings_layout.addWidget(gas_gb, 2, 0, 1, 2)

        # ---- Device status ----
        status_gb = QGroupBox("设备状态 / Device Status")
        status_layout = QFormLayout(status_gb)
        self._status_connect = QLabel("--")
        self._status_name = QLabel("--")
        self._status_temp = QLabel("--")
        status_layout.addRow("连接状态 / Connection:", self._status_connect)
        status_layout.addRow("设备名称 / Device:", self._status_name)
        status_layout.addRow("温度 / Temperature:", self._status_temp)
        device_column_layout.addWidget(status_gb)

        # ---- Info labels ----
        info_gb = QGroupBox("参数范围 / Property Ranges")
        info_form = QFormLayout(info_gb)
        self._exp_range_label = QLabel("N/A")
        self._temp_range_label = QLabel("N/A")
        info_form.addRow("曝光范围 / Exposure Range:", self._exp_range_label)
        info_form.addRow("温度范围 / Temperature Range:", self._temp_range_label)
        device_column_layout.addWidget(info_gb)

        # ---- Offline LAN remote access ----
        remote_gb = QGroupBox("局域网远程控制 / LAN Remote Control")
        remote_form = QFormLayout(remote_gb)
        self._remote_enabled_cb = QCheckBox("允许远程查看和控制 / Enable Remote Access")
        remote_form.addRow("", self._remote_enabled_cb)

        self._remote_port_spin = QSpinBox()
        self._remote_port_spin.setRange(1024, 65535)
        self._remote_port_spin.setValue(8765)
        remote_form.addRow("服务端口 / Port:", self._remote_port_spin)

        self._remote_allowed_ip_edit = QLineEdit()
        self._remote_allowed_ip_edit.setPlaceholderText("例如 192.168.50.3；留空允许局域网内任意电脑")
        remote_form.addRow("控制室 IP / Allowed IP:", self._remote_allowed_ip_edit)

        token_row = QHBoxLayout()
        self._remote_token_edit = QLineEdit(generate_remote_token())
        self._remote_token_edit.setMaxLength(128)
        self._remote_token_edit.setToolTip("控制室浏览器首次连接时需要输入此密钥。")
        self._remote_token_generate_button = QPushButton("重新生成")
        self._remote_token_generate_button.clicked.connect(
            lambda: self._remote_token_edit.setText(generate_remote_token())
        )
        token_row.addWidget(self._remote_token_edit, 1)
        token_row.addWidget(self._remote_token_generate_button)
        remote_form.addRow("访问密钥 / Access Key:", token_row)

        self._remote_status_label = QLabel("未启用 / Disabled")
        self._remote_status_label.setWordWrap(True)
        self._remote_status_label.setTextInteractionFlags(
            self._remote_status_label.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        remote_form.addRow("运行状态 / Status:", self._remote_status_label)
        device_column_layout.addWidget(remote_gb)
        device_column_layout.addStretch()
        settings_layout.addWidget(device_column, 1, 1)

        for form in (cam_form, proc_form, arpls_form, status_layout, info_form, remote_form):
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(10)

        # ---- Apply button ----
        btn_row = QHBoxLayout()
        self._btn_apply = QPushButton("应用设置 / Apply Settings")
        self._btn_apply.setMinimumSize(190, 42)
        self._btn_apply.clicked.connect(self._on_apply)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_apply)
        layout.addLayout(btn_row)

        self._settings_layout = settings_layout
        self._settings_sections = (cam_gb, proc_gb, arpls_gb, device_column, gas_gb)
        self._compact_layout: bool | None = None
        self._reflow_settings_layout(self.width() < 1180)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_settings_layout"):
            self._reflow_settings_layout(event.size().width() < 1180)

    def _reflow_settings_layout(self, compact: bool) -> None:
        if self._compact_layout == compact:
            return
        self._compact_layout = compact
        cam_gb, proc_gb, arpls_gb, device_column, gas_gb = self._settings_sections
        for section in self._settings_sections:
            self._settings_layout.removeWidget(section)

        if compact:
            for row, section in enumerate((cam_gb, proc_gb, arpls_gb, device_column)):
                self._settings_layout.addWidget(section, row, 0)
            self._settings_layout.addWidget(gas_gb, 4, 0)
            self._settings_layout.setColumnStretch(0, 1)
            self._settings_layout.setColumnStretch(1, 0)
        else:
            self._settings_layout.addWidget(cam_gb, 0, 0)
            self._settings_layout.addWidget(proc_gb, 0, 1)
            self._settings_layout.addWidget(arpls_gb, 1, 0)
            self._settings_layout.addWidget(device_column, 1, 1)
            self._settings_layout.addWidget(gas_gb, 2, 0, 1, 2)
            self._settings_layout.setColumnStretch(0, 1)
            self._settings_layout.setColumnStretch(1, 1)

    def _init_gas_table(self) -> None:
        configs = GasAnalyzer.default_gases()
        for cfg in configs:
            self._add_gas_row(
                cfg.name,
                cfg.position,
                cfg.window,
                cfg.coefficient,
                cfg.raman_shift,
                cfg.alarm_concentration,
                cfg.detection_sigma,
            )

    def _add_gas_row(self, name: str = "", pos: int = 0, window: int = 15,
                     coeff: float = 1.0, shift: float = 0.0,
                     alarm_concentration: float | None = None,
                     detection_sigma: float | None = None) -> None:
        self._gas_model.append_row(
            (
                name,
                pos,
                window,
                coeff,
                shift if shift else "",
                alarm_concentration if alarm_concentration is not None else "",
                detection_sigma if detection_sigma is not None else "",
            )
        )

    def _get_gas_configs(self) -> list[GasConfig]:
        configs = []
        for items in self._gas_model.rows():
            items = [value.strip() for value in items]
            if not items[0]:
                continue
            try:
                shift_text = items[4].strip()
                alarm_text = items[5].strip()
                detection_text = items[6].strip()
                configs.append(GasConfig(
                    name=items[0],
                    position=int(items[1]),
                    window=int(items[2]),
                    coefficient=float(items[3]),
                    raman_shift=float(shift_text) if shift_text else 0.0,
                    alarm_concentration=float(alarm_text) if alarm_text else None,
                    detection_sigma=float(detection_text) if detection_text else None,
                ))
            except (ValueError, IndexError):
                continue
        return configs

    def update_gas_table(self, configs: list[GasConfig]) -> None:
        self._gas_model.replace_rows([
            (
                cfg.name,
                cfg.position,
                cfg.window,
                cfg.coefficient,
                cfg.raman_shift if cfg.raman_shift else "",
                cfg.alarm_concentration if cfg.alarm_concentration is not None else "",
                cfg.detection_sigma if cfg.detection_sigma is not None else "",
            )
            for cfg in configs
        ])

    @staticmethod
    def _select_combo_data(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def load_settings(self, settings: dict, gas_configs: list[GasConfig]) -> None:
        """Populate all editable controls from persisted settings."""
        self._exp_spin.setValue(float(settings.get("exposure_time_ms", 1000.0)))
        self._temp_spin.setValue(float(settings.get("temperature_c", -10.0)))
        self._select_combo_data(self._fan_combo, settings.get("fan_gear", 0))
        self._select_combo_data(self._mode_combo, settings.get("working_mode", 0))
        self._auto_save_cb.setChecked(bool(settings.get("auto_save", False)))
        self._save_dir_edit.setText(str(settings.get("save_dir", DEFAULT_SAVE_DIR)))
        try:
            groups = DataProcessor.parse_groups(
                str(settings.get("row_groups_text", ""))
            )
        except ValueError:
            groups = []
        self._set_row_groups(
            groups,
            normalize_row_group_names(settings.get("row_group_names", {})),
        )
        self._select_combo_data(
            self._row_aggregation_combo,
            settings.get("row_aggregation", DataProcessor.ROW_AGGREGATION_SUM),
        )
        self._merge_spin.setValue(int(settings.get("merge_factor", 1)))
        self._threshold_sigma_spin.setValue(
            float(settings.get("detection_threshold_sigma", 3.0))
        )
        self._batch_interval_spin.setValue(int(settings.get("batch_interval_ms", 1000)))
        self._export_sample_rate_spin.setValue(int(settings.get("export_sample_rate_hz", 1000)))
        self._plot_opengl_cb.setChecked(
            bool(settings.get("plot_opengl_enabled", True))
        )
        self._show_plot_fps_cb.setChecked(
            bool(settings.get("show_plot_fps", False))
        )
        self._remote_enabled_cb.setChecked(
            bool(settings.get("remote_enabled", False))
        )
        self._remote_port_spin.setValue(int(settings.get("remote_port", 8765)))
        self._remote_allowed_ip_edit.setText(
            str(settings.get("remote_allowed_ip", ""))
        )
        remote_token = str(settings.get("remote_token", "")).strip()
        if remote_token:
            self._remote_token_edit.setText(remote_token)
        self._select_combo_data(
            self._smooth_combo,
            settings.get("concentration_smoothing", "balanced"),
        )
        self._arpls_enable_cb.setChecked(bool(settings.get("arpls_enabled", True)))
        self._select_combo_data(self._arpls_mode_combo, settings.get("arpls_mode", "corrected"))
        self._arpls_lam_spin.setValue(float(settings.get("arpls_lam", 1e5)))
        self._arpls_iter_spin.setValue(int(settings.get("arpls_max_iter", 50)))
        self._arpls_tol_spin.setValue(float(settings.get("arpls_tol", 1e-6)))
        if gas_configs:
            self.update_gas_table(gas_configs)

    def load_plot_opengl_enabled(self, enabled: bool) -> None:
        self._plot_opengl_cb.setChecked(bool(enabled))

    def update_remote_status(self, message: str, ok: bool = False) -> None:
        self._remote_status_label.setText(str(message))
        self._remote_status_label.setStyleSheet(
            "color: #176b3a;" if ok else "color: #8a3030;"
        )

    def _on_add_gas(self) -> None:
        self._add_gas_row("New", 0, 15, 1.0, 0.0)

    def _on_del_gas(self) -> None:
        row = self._gas_table.currentIndex().row()
        if row >= 0:
            self._gas_model.remove_row(row)
        else:
            QMessageBox.information(self, "提示 / Info", "请先点击选中要删除的行。")

    def _on_browse_save_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择存储文件夹 / Select Save Directory")
        if folder:
            self._save_dir_edit.setText(folder)

    def _set_row_groups(
        self,
        groups: list[tuple[int, int]],
        names: dict[str, str],
    ) -> None:
        self._row_groups = list(groups[:MAX_ROW_GROUPS])
        descriptors = describe_row_groups(
            self._row_groups,
            custom_names=names,
        )
        self._row_group_names = {
            descriptor.key: descriptor.label for descriptor in descriptors
        }
        if descriptors:
            labels = [descriptor.label for descriptor in descriptors]
            preview = "、".join(labels[:3])
            if len(labels) > 3:
                preview += f" 等 {len(labels)} 个"
            self._row_groups_summary.setText(preview)
        else:
            self._row_groups_summary.clear()

    def _open_row_group_manager(self) -> None:
        from .row_group_dialog import RowGroupDialog

        dialog = RowGroupDialog(
            self._row_groups,
            self._row_group_names,
            self,
        )
        if dialog.exec():
            groups, names = dialog.values()
            self._set_row_groups(groups, names)

    def update_device_status(self, info: CameraInfo | None) -> None:
        if info is None:
            self._status_connect.setText("未连接 / Disconnected")
            self._status_connect.setStyleSheet("color: red;")
            self._status_name.setText("--")
            self._status_temp.setText("--")
        else:
            self._status_connect.setText("已连接 / Connected")
            self._status_connect.setStyleSheet("color: green;")
            self._status_name.setText(info.model or "--")
            temp_parts = []
            if abs(info.fpga_temperature) > 0.01:
                temp_parts.append(f"FPGA {info.fpga_temperature:.1f} °C")
            if abs(info.pcba_temperature) > 0.01:
                temp_parts.append(f"PCB {info.pcba_temperature:.1f} °C")
            if abs(info.env_temperature) > 0.01:
                temp_parts.append(f"环境 {info.env_temperature:.1f} °C")
            self._status_temp.setText("  |  ".join(temp_parts) if temp_parts else "N/A")

    def update_ranges(self, camera: ProcessCameraController) -> None:
        try:
            mn, mx = camera.get_exposure_range()
            self._exp_range_label.setText(f"{mn:.2f} – {mx:.2f} ms")
            self._exp_spin.setRange(max(0.01, mn), mx)
        except Exception:
            self._exp_range_label.setText("N/A")
        try:
            mn, mx = camera.get_temperature_range()
            if mn < mx and -150.0 <= mn <= 150.0 and -150.0 <= mx <= 150.0:
                self._temp_range_label.setText(f"{mn:.1f} – {mx:.1f} °C")
                self._temp_spin.setRange(mn, mx)
            else:
                self._temp_range_label.setText(f"忽略异常范围: {mn:.1f} – {mx:.1f} °C")
                self._temp_spin.setRange(-50, 50)
        except Exception:
            self._temp_range_label.setText("N/A")
            self._temp_spin.setRange(-50, 50)

    @Slot()
    def _on_apply(self) -> None:
        raw_text = " ".join(
            f"{start}-{end}" for start, end in self._row_groups
        )

        gas_configs = self._get_gas_configs()
        if not gas_configs:
            QMessageBox.warning(
                self,
                "气体配置为空 / No Gas Configured",
                "请至少添加一种气体。",
            )
            return

        save_dir = self._save_dir_edit.text().strip() or DEFAULT_SAVE_DIR
        if save_dir != self._save_dir_edit.text():
            self._save_dir_edit.setText(save_dir)

        allowed_ip = self._remote_allowed_ip_edit.text().strip()
        if allowed_ip:
            try:
                ipaddress.ip_address(allowed_ip)
            except ValueError:
                QMessageBox.warning(
                    self,
                    "IP 地址无效 / Invalid IP",
                    "控制室 IP 无法识别，请输入类似 192.168.50.3 的地址，或留空。",
                )
                return
        remote_token = self._remote_token_edit.text().strip()
        if self._remote_enabled_cb.isChecked() and not remote_token:
            QMessageBox.warning(
                self,
                "访问密钥为空 / Missing Access Key",
                "启用远程控制前需要设置访问密钥。",
            )
            return

        updates = {
            "exposure_time_ms": self._exp_spin.value(),
            "temperature_c": self._temp_spin.value(),
            "fan_gear": self._fan_combo.currentData(),
            "working_mode": self._mode_combo.currentData(),
            "auto_save": self._auto_save_cb.isChecked(),
            "save_dir": save_dir,
            "row_groups_text": raw_text,
            "row_group_names": dict(self._row_group_names),
            "row_aggregation": self._row_aggregation_combo.currentData(),
            "merge_factor": self._merge_spin.value(),
            "detection_threshold_sigma": self._threshold_sigma_spin.value(),
            "batch_interval_ms": self._batch_interval_spin.value(),
            "export_sample_rate_hz": self._export_sample_rate_spin.value(),
            "plot_opengl_enabled": self._plot_opengl_cb.isChecked(),
            "show_plot_fps": self._show_plot_fps_cb.isChecked(),
            "remote_enabled": self._remote_enabled_cb.isChecked(),
            "remote_port": self._remote_port_spin.value(),
            "remote_allowed_ip": allowed_ip,
            "remote_token": remote_token,
            "concentration_smoothing": self._smooth_combo.currentData(),
            "arpls_enabled": self._arpls_enable_cb.isChecked(),
            "arpls_mode": self._arpls_mode_combo.currentData(),
            "arpls_lam": self._arpls_lam_spin.value(),
            "arpls_max_iter": self._arpls_iter_spin.value(),
            "arpls_tol": self._arpls_tol_spin.value(),
            "gas_configs": gas_configs,
        }
        self.settings_changed.emit(updates)
