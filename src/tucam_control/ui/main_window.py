# -*- coding: utf-8 -*-
"""Main window with tabbed layout for camera control application."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QStatusBar,
    QMessageBox,
    QFileDialog,
)

from ..camera import CameraController, CameraInfo
from ..data_processor import DataProcessor
from ..gas_analyzer import GasAnalyzer, GasConfig
from .acquisition_tab import AcquisitionTab
from .settings_tab import SettingsTab
from .data_tab import DataTab
from .concentration_tab import ConcentrationTab


class MainWindow(QMainWindow):
    """Top-level application window."""

    status_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Dhyana-95-V2 Camera Control")
        self.resize(1400, 900)

        self._camera = CameraController()
        self._processor = DataProcessor()
        self._analyzer = GasAnalyzer()
        self._analyzer.gases = GasAnalyzer.default_gases()
        self._settings: dict = {
            "exposure_time_ms": 1000.0,
            "temperature_c": -10.0,
            "fan_gear": 2,
            "row_groups_text": "",
            "merge_factor": 1,
            "arpls_enabled": False,
            "arpls_mode": "raw",
            "arpls_lam": 1e5,
            "arpls_max_iter": 50,
            "arpls_tol": 1e-6,
        }
        self._was_connected = False
        self._disconnect_warned = False

        self._setup_ui()
        self._connect_signals()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._on_refresh_info)
        self._refresh_timer.start()

        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(50)
        self._capture_timer.timeout.connect(self._on_capture_poll)

        self._try_connect()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._acq_tab = AcquisitionTab()
        self._settings_tab = SettingsTab()
        self._data_tab = DataTab()
        self._conc_tab = ConcentrationTab()

        self._tabs.addTab(self._acq_tab, "采集 / Acquisition")
        self._tabs.addTab(self._settings_tab, "设置 / Settings")
        self._tabs.addTab(self._data_tab, "图谱 / Spectrum")
        self._tabs.addTab(self._conc_tab, "浓度 / Concentration")

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self.status_changed.connect(self._status_bar.showMessage)

    def _connect_signals(self) -> None:
        self._acq_tab.start_single.connect(self._on_start_single)
        self._acq_tab.start_continuous.connect(self._on_start_continuous)
        self._acq_tab.stop_requested.connect(self._on_stop)
        self._acq_tab.save_requested.connect(self._on_save)
        self._acq_tab.connect_requested.connect(self._on_reconnect)
        self._acq_tab.load_tif_requested.connect(self._on_load_tif)

        self._settings_tab.settings_changed.connect(self._on_settings_changed)

        self._acq_tab.frame_ready.connect(self._on_frame_ready)

    # ------------------------------------------------------------------
    # Camera management
    # ------------------------------------------------------------------

    def _try_connect(self) -> None:
        try:
            count = self._camera.initialize()
            if count == 0:
                self.status_changed.emit("未检测到相机 / No camera detected")
                QMessageBox.warning(
                    self,
                    "相机未连接 / Camera Not Found",
                    "未检测到 Dhyana 系列相机。\n"
                    "请检查：\n"
                    "1. 相机是否正确连接并上电\n"
                    "2. 相机驱动是否已安装\n"
                    "3. 相机是否被其他程序占用\n\n"
                    "您可以点击「载入TIF」使用测试图片。",
                )
                self._was_connected = False
                return
            self._camera.open(0)
            self._apply_current_settings()
            info = self._camera.get_device_info()
            self._acq_tab.show_device_info(info)
            self._settings_tab.update_ranges(self._camera)
            self.status_changed.emit(f"已连接 / Connected: {info.model}")
            self._was_connected = True
            self._disconnect_warned = False
        except Exception as exc:
            self.status_changed.emit(f"连接失败 / Connection failed: {exc}")
            QMessageBox.critical(
                self,
                "连接失败 / Connection Failed",
                f"无法打开相机：\n{exc}\n\n"
                "请检查相机连接后点击「重新连接」。\n"
                "也可以点击「载入TIF」使用测试图片。",
            )
            self._was_connected = False

    def _apply_current_settings(self) -> None:
        s = self._settings
        try:
            self._camera.set_exposure_time(s["exposure_time_ms"])
        except Exception:
            pass
        try:
            self._camera.set_temperature_target(s["temperature_c"])
        except Exception:
            pass
        try:
            self._camera.set_fan_gear(s["fan_gear"])
        except Exception:
            pass

    @Slot()
    def _on_reconnect(self) -> None:
        self._capture_timer.stop()
        if self._camera.is_capturing:
            try:
                self._camera.stop_capture()
            except Exception:
                pass
            self._acq_tab.set_capturing_state(False)

        try:
            self._camera.close()
        except Exception:
            pass
        try:
            self._camera.uninitialize()
        except Exception:
            pass

        self._disconnect_warned = False
        self._try_connect()

    # ------------------------------------------------------------------
    # TIF loading (test mode)
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_load_tif(self, path: str) -> None:
        """Load a TIF image for testing data processing pipeline."""
        try:
            img = Image.open(path)
            arr = np.array(img, dtype=np.uint16)
            if arr.ndim != 2:
                QMessageBox.warning(
                    self,
                    "格式不支持 / Unsupported Format",
                    f"仅支持单通道灰度 TIF 图像。\n当前图像维度: {arr.ndim}",
                )
                return
            self._acq_tab.display_frame(arr)
            self.status_changed.emit(f"已载入 / Loaded: {Path(path).name}")
            self._tabs.setCurrentIndex(2)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "载入失败 / Load Failed",
                f"无法读取文件：\n{path}\n\n{exc}",
            )

    # ------------------------------------------------------------------
    # Acquisition callbacks
    # ------------------------------------------------------------------

    @Slot()
    def _on_start_single(self) -> None:
        if not self._camera.is_open:
            QMessageBox.warning(
                self,
                "相机未连接 / Camera Not Connected",
                "请先连接相机后再进行采集。\n也可以使用「载入TIF」测试。",
            )
            return
        try:
            arr = self._camera.capture_single()
            if arr is not None:
                self._acq_tab.display_frame(arr)
                self.status_changed.emit("单帧采集完成 / Single frame captured")
            else:
                QMessageBox.warning(
                    self,
                    "采集超时 / Capture Timeout",
                    "等待图像帧超时，请检查相机连接。",
                )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "采集错误 / Capture Error",
                f"抓取图像时发生错误：\n{exc}",
            )

    @Slot()
    def _on_start_continuous(self) -> None:
        if not self._camera.is_open:
            QMessageBox.warning(
                self,
                "相机未连接 / Camera Not Connected",
                "请先连接相机后再进行采集。\n也可以使用「载入TIF」测试。",
            )
            return
        try:
            self._camera.start_capture()
            self._acq_tab.set_capturing_state(True)
            self._capture_timer.start()
            self.status_changed.emit("连续采集中 / Continuous capture running")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "启动采集失败 / Capture Start Failed",
                f"无法启动连续采集：\n{exc}",
            )

    @Slot()
    def _on_stop(self) -> None:
        self._capture_timer.stop()
        try:
            self._camera.stop_capture()
        except Exception:
            pass
        self._acq_tab.set_capturing_state(False)
        self.status_changed.emit("采集已停止 / Capture stopped")

    @Slot()
    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存图片 / Save Image",
            "",
            "TIFF (*.tif *.tiff);;PNG (*.png);;JPEG (*.jpg)",
        )
        if not path:
            return
        if self._camera.is_open:
            try:
                self._camera.save_image(path)
                self.status_changed.emit(f"已保存 / Saved: {path}")
                return
            except Exception as exc:
                QMessageBox.warning(self, "保存失败 / Save Error", str(exc))
                return

        QMessageBox.warning(
            self,
            "相机未连接 / Camera Not Connected",
            "保存功能需要相机连接。\n测试模式下请使用「载入TIF」的文件本身。",
        )

    # ------------------------------------------------------------------
    # Continuous poll & refresh
    # ------------------------------------------------------------------

    @Slot()
    def _on_capture_poll(self) -> None:
        if not self._camera.is_capturing:
            return
        arr = self._camera.wait_for_frame(timeout_ms=500)
        if arr is not None:
            self._acq_tab.display_frame(arr)
        else:
            if not self._camera.is_connected():
                self._on_device_lost()

    @Slot()
    def _on_refresh_info(self) -> None:
        if not self._camera.is_open:
            return
        try:
            info = self._camera.get_device_info()
            self._acq_tab.update_telemetry(info)
        except Exception:
            if self._was_connected and not self._disconnect_warned:
                self._on_device_lost()

        if self._was_connected and not self._camera.is_connected():
            if not self._disconnect_warned:
                self._on_device_lost()

    def _on_device_lost(self) -> None:
        self._disconnect_warned = True
        self._was_connected = False
        self._capture_timer.stop()
        self._acq_tab.set_capturing_state(False)
        try:
            self._camera.stop_capture()
        except Exception:
            pass
        self.status_changed.emit("设备已断开！/ Device disconnected!")
        QMessageBox.warning(
            self,
            "设备已断开 / Device Disconnected",
            "检测到相机连接已断开！\n"
            "采集已自动停止。\n\n"
            "请检查 USB 连接后点击「重新连接」。",
        )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @Slot(dict)
    def _on_settings_changed(self, updates: dict) -> None:
        raw_text = updates.get("row_groups_text", "")
        groups = DataProcessor.parse_groups(raw_text)
        if raw_text.strip() and not groups:
            QMessageBox.warning(
                self,
                "行分组格式错误 / Invalid Row Group Format",
                f"无法解析行分组设置：\n「{raw_text}」\n\n"
                "请使用格式: 1-40, 91-130, 200-250\n"
                "留空表示使用全部行。",
            )
            return

        exp = updates.get("exposure_time_ms", 1000.0)
        temp = updates.get("temperature_c", -10.0)

        if self._camera.is_open:
            try:
                exp_range = self._camera.get_exposure_range()
                if exp < exp_range[0] or exp > exp_range[1]:
                    QMessageBox.warning(
                        self,
                        "曝光时间超出范围 / Exposure Out of Range",
                        f"曝光时间 {exp} ms 超出相机支持范围 "
                        f"({exp_range[0]:.2f} – {exp_range[1]:.2f} ms)。",
                    )
                    return
            except Exception:
                pass

            try:
                temp_range = self._camera.get_temperature_range()
                if temp < temp_range[0] or temp > temp_range[1]:
                    QMessageBox.warning(
                        self,
                        "温度超出范围 / Temperature Out of Range",
                        f"目标温度 {temp} °C 超出相机支持范围 "
                        f"({temp_range[0]:.1f} – {temp_range[1]:.1f} °C)。",
                    )
                    return
            except Exception:
                pass

        self._settings.update(updates)
        if self._camera.is_open:
            self._apply_current_settings()

        self._processor.row_groups = groups
        self._processor.merge_factor = self._settings.get("merge_factor", 1)
        self._processor.arPLS_enabled = self._settings.get("arpls_enabled", False)
        self._processor.baseline_mode = self._settings.get("arpls_mode", "raw")
        self._processor.arPLS_lam = self._settings.get("arpls_lam", 1e5)
        self._processor.arPLS_max_iter = self._settings.get("arpls_max_iter", 50)
        self._processor.arPLS_tol = self._settings.get("arpls_tol", 1e-6)

        gas_configs = updates.get("gas_configs")
        if gas_configs is not None:
            self._analyzer.gases = gas_configs

        self._reprocess_cached()

        self.status_changed.emit("设置已应用 / Settings applied")

    # ------------------------------------------------------------------
    # Frame → data processing
    # ------------------------------------------------------------------

    def _on_frame_ready(self, arr: np.ndarray) -> None:
        self._process_and_display(arr)

    def _process_and_display(self, arr: np.ndarray) -> None:
        try:
            result = self._processor.process(arr)
            row_groups = self._processor.row_groups
            labels = [
                f"行 {s}-{e}"
                for s, e in (row_groups if row_groups else [(1, arr.shape[0])])
            ]
            self._data_tab.set_row_labels(labels)
            self._data_tab.display_array(result)
            self._data_tab.set_baseline_data(self._processor.last_baseline)

            # Gas analysis on each row group's spectrum
            gas_names = [g.name for g in self._analyzer.gases]
            self._conc_tab.set_gas_names(gas_names)
            if result.shape[0] > 0:
                g_results = self._analyzer.analyze(result[0])
                self._conc_tab.add_data_point(g_results)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "处理错误 / Processing Error",
                f"数据处理失败：\n{exc}",
            )

    def _reprocess_cached(self) -> None:
        """Re-run full pipeline on cached image (for settings changes)."""
        result = self._processor.reprocess()
        if result is not None:
            row_groups = self._processor.row_groups
            labels = (
                [f"行 {s}-{e}" for s, e in row_groups]
                if row_groups
                else [f"全图 {result.shape[1]} 列"]
            )
            self._data_tab.set_row_labels(labels)
            self._data_tab.display_array(result)
            self._data_tab.set_baseline_data(self._processor.last_baseline)

            gas_names = [g.name for g in self._analyzer.gases]
            self._conc_tab.set_gas_names(gas_names)
            if result.shape[0] > 0:
                g_results = self._analyzer.analyze(result[0])
                self._conc_tab.add_data_point(g_results)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        self._capture_timer.stop()
        try:
            self._camera.uninitialize()
        except Exception:
            pass
        super().closeEvent(event)
