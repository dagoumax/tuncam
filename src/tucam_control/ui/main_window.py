# -*- coding: utf-8 -*-
"""Main window with tabbed layout for camera control application."""

from __future__ import annotations

import copy
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QStatusBar,
    QMessageBox,
    QFileDialog,
)

from ..camera import CameraController
from ..data_processor import DataProcessor
from ..debug_log import get_debug_logger
from ..gas_analyzer import GasAnalyzer
from .acquisition_tab import AcquisitionTab
from .settings_tab import SettingsTab
from .data_tab import DataTab
from .concentration_tab import ConcentrationTab


DEFAULT_SAVE_DIR = str(Path.home() / "Documents" / "tucam_data")
CAPTURE_POLL_TIMEOUT_MS = 50
log = get_debug_logger("ui.main_window")


class _ProcessingSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _ProcessingTask(QRunnable):
    def __init__(
        self,
        frame: np.ndarray,
        settings: dict,
        gas_configs: list,
        generation: int,
        batch_mode: bool,
    ) -> None:
        super().__init__()
        self.signals = _ProcessingSignals()
        self._frame = frame
        self._settings = settings
        self._gas_configs = gas_configs
        self._generation = generation
        self._batch_mode = batch_mode

    @Slot()
    def run(self) -> None:
        try:
            started = time.perf_counter()
            row_groups = DataProcessor.parse_groups(self._settings.get("row_groups_text", ""))
            log.debug(
                "Processing task started: frame_shape=%s groups=%s merge_factor=%s batch=%s",
                self._frame.shape,
                row_groups,
                self._settings.get("merge_factor", 1),
                self._batch_mode,
            )

            processor = DataProcessor()
            processor.row_groups = row_groups
            processor.merge_factor = self._settings.get("merge_factor", 1)
            processor.arPLS_enabled = self._settings.get("arpls_enabled", False)
            processor.baseline_mode = self._settings.get("arpls_mode", "raw")
            processor.arPLS_lam = self._settings.get("arpls_lam", 1e5)
            processor.arPLS_max_iter = self._settings.get("arpls_max_iter", 50)
            processor.arPLS_tol = self._settings.get("arpls_tol", 1e-6)

            analyzer = GasAnalyzer()
            analyzer.gases = self._gas_configs
            analyzer.merge_factor = processor.merge_factor

            result = processor.process(self._frame)
            labels = [
                f"行 {s}-{e}"
                for s, e in (row_groups if row_groups else [(1, self._frame.shape[0])])
            ]
            gas_names = [g.name for g in analyzer.gases]
            all_results = analyzer.analyze_groups(result) if result.shape[0] > 0 else []

            self.signals.finished.emit({
                "generation": self._generation,
                "duration_ms": (time.perf_counter() - started) * 1000,
                "result": result,
                "baseline": processor.last_baseline,
                "labels": labels,
                "gas_names": gas_names,
                "all_results": all_results,
                "mode": "index" if self._batch_mode else "time",
            })
        except Exception as exc:
            log.exception("Processing task failed")
            self.signals.failed.emit(str(exc))


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
            "working_mode": 0,
            "auto_save": False,
            "save_dir": DEFAULT_SAVE_DIR,
            "row_groups_text": "",
            "merge_factor": 1,
            "arpls_enabled": True,
            "arpls_mode": "corrected",
            "arpls_lam": 1e5,
            "arpls_max_iter": 50,
            "arpls_tol": 1e-6,
        }
        self._was_connected = False
        self._disconnect_warned = False
        self._last_frame: np.ndarray | None = None
        self._processing_busy = False
        self._pending_frame: np.ndarray | None = None
        self._processing_task: _ProcessingTask | None = None
        self._processing_generation = 0
        self._processing_pool = QThreadPool(self)
        self._processing_pool.setMaxThreadCount(1)

        self._setup_ui()
        self._connect_signals()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._on_refresh_info)
        self._refresh_timer.start()

        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(200)
        self._capture_timer.timeout.connect(self._on_capture_poll)

        self._batch_images: list[tuple[str, np.ndarray]] = []
        self._batch_idx: int = 0
        self._batch_timer = QTimer(self)
        self._batch_timer.setInterval(200)
        self._batch_timer.timeout.connect(self._on_batch_tick)

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
        self._tabs.addTab(self._data_tab, "拉曼光谱 / Raman")
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
        self._acq_tab.batch_load_requested.connect(self._on_batch_load)
        self._acq_tab.batch_stop_requested.connect(self._on_batch_stop)

        self._settings_tab.settings_changed.connect(self._on_settings_changed)

        self._acq_tab.frame_ready.connect(self._on_frame_ready)
        self._data_tab.calibration_changed.connect(self._on_calibration_changed)

    # ------------------------------------------------------------------
    # Camera management
    # ------------------------------------------------------------------

    def _try_connect(self) -> None:
        try:
            log.info("Trying to connect camera")
            count = self._camera.initialize()
            log.info("Camera initialize finished; count=%s", count)
            if count == 0:
                log.warning("No camera detected after TUCAM_Api_Init")
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
            self._settings_tab.update_device_status(info)
            status = self._camera.connection_status()
            log.info(
                "Camera connected: model=%r serial=%r connection_status=%s",
                info.model,
                info.serial_number,
                status,
            )
            if status is None:
                self.status_changed.emit(
                    f"已连接 / Connected: {info.model} (SDK 不支持断开状态检测)"
                )
            else:
                self.status_changed.emit(f"已连接 / Connected: {info.model}")
            self._was_connected = True
            self._disconnect_warned = False
        except Exception as exc:
            log.exception("Camera connection failed")
            self.status_changed.emit(f"连接失败 / Connection failed: {exc}")
            QMessageBox.critical(
                self,
                "连接失败 / Connection Failed",
                f"无法打开相机：\n{exc}\n\n"
                "请检查相机连接后点击「重新连接」。\n"
                "也可以点击「载入TIF」使用测试图片。",
            )
            self._settings_tab.update_device_status(None)
            self._was_connected = False

    def _apply_current_settings(self) -> None:
        s = self._settings
        try:
            self._camera.configure_scientific_frame_format()
        except Exception as exc:
            log.warning("Failed to configure scientific frame format: %s", exc)
        try:
            self._camera.set_exposure_time(s["exposure_time_ms"])
        except Exception as exc:
            log.warning("Failed to apply exposure_time_ms=%s: %s", s.get("exposure_time_ms"), exc)
        try:
            self._camera.set_temperature_target(s["temperature_c"])
        except Exception as exc:
            log.warning("Failed to apply temperature_c=%s: %s", s.get("temperature_c"), exc)
        try:
            self._camera.set_fan_gear(s["fan_gear"])
        except Exception as exc:
            log.warning("Failed to apply fan_gear=%s: %s", s.get("fan_gear"), exc)
        try:
            self._camera.set_working_mode(s.get("working_mode", 0))
        except Exception as exc:
            log.warning("Failed to apply working_mode=%s: %s", s.get("working_mode", 0), exc)

    @Slot()
    def _on_reconnect(self) -> None:
        log.info("Reconnect requested")
        self._capture_timer.stop()
        if self._camera.is_capturing:
            try:
                self._camera.stop_capture()
            except Exception as exc:
                log.warning("Failed to stop capture before reconnect: %s", exc)
            self._acq_tab.set_capturing_state(False)

        try:
            self._camera.close()
        except Exception as exc:
            log.warning("Failed to close camera before reconnect: %s", exc)
        try:
            self._camera.uninitialize()
        except Exception as exc:
            log.warning("Failed to uninitialize camera before reconnect: %s", exc)

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
    # Batch TIF testing
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_batch_load(self, folder: str) -> None:
        import glob
        folder_path = Path(folder)
        tif_files = sorted(
            glob.glob(str(folder_path / "*.tif"))
            + glob.glob(str(folder_path / "*.tiff"))
        )
        if not tif_files:
            QMessageBox.warning(
                self,
                "无 TIF 文件 / No TIF Files",
                f"文件夹内未找到 .tif 文件：\n{folder}",
            )
            return

        self._batch_images.clear()
        for f in tif_files:
            try:
                img = Image.open(f)
                arr = np.array(img, dtype=np.uint16)
                if arr.ndim == 2:
                    self._batch_images.append((f, arr))
            except Exception as exc:
                self.status_changed.emit(f"跳过 {Path(f).name}: {exc}")

        if not self._batch_images:
            QMessageBox.warning(self, "加载失败", "没有成功加载任何图像。")
            return

        self._batch_idx = 0
        self._conc_tab.clear_history()
        self._acq_tab.set_batch_state(True)
        self._batch_timer.start()
        self.status_changed.emit(f"批量测试: {len(self._batch_images)} 张图像")

    @Slot()
    def _on_batch_tick(self) -> None:
        if self._batch_idx >= len(self._batch_images):
            self._on_batch_stop()
            return
        path, arr = self._batch_images[self._batch_idx]
        self._batch_idx += 1
        self._acq_tab.display_frame(arr)
        self.status_changed.emit(f"Batch [{self._batch_idx}/{len(self._batch_images)}] {Path(path).name}")

    @Slot()
    def _on_batch_stop(self) -> None:
        self._batch_timer.stop()
        self._acq_tab.set_batch_state(False)
        self.status_changed.emit(f"批量测试结束 / Batch finished ({len(self._batch_images)} images)")

    # ------------------------------------------------------------------
    # Auto-save helper
    # ------------------------------------------------------------------

    def _ensure_save_dir(self) -> str | None:
        d = self._settings.get("save_dir", DEFAULT_SAVE_DIR)
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            return d
        except Exception as exc:
            QMessageBox.warning(self, "存储错误 / Save Error",
                                f"无法创建存储目录：\n{d}\n\n{exc}")
            return None

    def _auto_save_frame(self) -> None:
        if not self._settings.get("auto_save", False):
            return
        save_dir = self._ensure_save_dir()
        if save_dir is None:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = f"{save_dir}\\{ts}.tif"
        try:
            self._camera.save_image(path)
            self.status_changed.emit(f"已自动存储 / Auto saved: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "自动存储失败 / Auto Save Failed", str(exc))

    # ------------------------------------------------------------------
    # Acquisition callbacks
    # ------------------------------------------------------------------

    @Slot()
    def _on_start_single(self) -> None:
        if not self._camera.is_open:
            log.warning("Single capture requested while camera is not open")
            QMessageBox.warning(
                self,
                "相机未连接 / Camera Not Connected",
                "请先连接相机后再进行采集。\n也可以使用「载入TIF」测试。",
            )
            return
        try:
            log.info("Single capture requested")
            arr = self._camera.capture_single()
            if arr is not None:
                log.info("Single frame captured: shape=%s dtype=%s", arr.shape, arr.dtype)
                self._acq_tab.display_frame(arr)
                self._auto_save_frame()
                self.status_changed.emit("单帧采集完成 / Single frame captured")
            else:
                log.warning("Single capture timed out")
                QMessageBox.warning(
                    self,
                    "采集超时 / Capture Timeout",
                    "等待图像帧超时，请检查相机连接。",
                )
        except Exception as exc:
            log.exception("Single capture failed")
            QMessageBox.critical(
                self,
                "采集错误 / Capture Error",
                f"抓取图像时发生错误：\n{exc}",
            )

    @Slot()
    def _on_start_continuous(self) -> None:
        if not self._camera.is_open:
            log.warning("Continuous capture requested while camera is not open")
            QMessageBox.warning(
                self,
                "相机未连接 / Camera Not Connected",
                "请先连接相机后再进行采集。\n也可以使用「载入TIF」测试。",
            )
            return
        try:
            log.info("Continuous capture requested")
            self._camera.start_capture()
            self._acq_tab.set_capturing_state(True)
            self._capture_timer.start()
            log.info("Continuous capture timer started interval_ms=%s", self._capture_timer.interval())
            self.status_changed.emit("连续采集中 / Continuous capture running")
        except Exception as exc:
            log.exception("Continuous capture start failed")
            QMessageBox.critical(
                self,
                "启动采集失败 / Capture Start Failed",
                f"无法启动连续采集：\n{exc}",
            )

    @Slot()
    def _on_stop(self) -> None:
        log.info("Capture stop requested")
        self._capture_timer.stop()
        try:
            self._camera.stop_capture()
        except Exception as exc:
            log.warning("Failed to stop capture: %s", exc)
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
        arr = self._camera.wait_for_frame(timeout_ms=CAPTURE_POLL_TIMEOUT_MS)
        if arr is not None:
            log.debug("Continuous frame received: shape=%s dtype=%s", arr.shape, arr.dtype)
            self._acq_tab.display_frame(arr)
            self._auto_save_frame()
        else:
            status = self._camera.connection_status()
            if status is False:
                log.warning("Capture poll detected disconnected device")
                self._on_device_lost()
            elif status is None:
                log.debug("Capture poll got no frame; connection status unknown")

    @Slot()
    def _on_refresh_info(self) -> None:
        if not self._camera.is_open:
            return
        try:
            info = self._camera.get_device_info()
            self._acq_tab.update_telemetry(info)
            self._settings_tab.update_device_status(info)
        except Exception as exc:
            log.warning("Telemetry refresh failed: %s", exc)
            self.status_changed.emit(f"设备信息刷新失败 / Telemetry unavailable: {exc}")

        status = self._camera.connection_status()
        if self._was_connected and status is False:
            if not self._disconnect_warned:
                log.warning("Refresh timer detected disconnected device")
                self._on_device_lost()

    def _on_device_lost(self) -> None:
        log.warning("Device lost handler triggered")
        self._disconnect_warned = True
        self._was_connected = False
        self._capture_timer.stop()
        self._acq_tab.set_capturing_state(False)
        self._settings_tab.update_device_status(None)
        try:
            self._camera.stop_capture()
        except Exception as exc:
            log.warning("Failed to stop capture after device lost: %s", exc)
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
        self._processing_generation += 1
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
        self._analyzer.merge_factor = self._settings.get("merge_factor", 1)

        self._reprocess_cached()

        self.status_changed.emit("设置已应用 / Settings applied")

    # ------------------------------------------------------------------
    # Frame → data processing
    # ------------------------------------------------------------------

    def _on_frame_ready(self, arr: np.ndarray) -> None:
        self._last_frame = arr.copy()
        self._queue_frame_processing(arr)

    def _queue_frame_processing(self, arr: np.ndarray) -> None:
        if self._processing_busy:
            self._pending_frame = arr.copy()
            return

        self._processing_busy = True
        self._pending_frame = None
        task = _ProcessingTask(
            frame=arr.copy(),
            settings=copy.deepcopy(self._settings),
            gas_configs=copy.deepcopy(self._analyzer.gases),
            generation=self._processing_generation,
            batch_mode=self._batch_timer.isActive(),
        )
        task.signals.finished.connect(self._on_processing_finished)
        task.signals.failed.connect(self._on_processing_failed)
        self._processing_task = task
        self._processing_pool.start(task)

    @Slot(object)
    def _on_processing_finished(self, payload: dict) -> None:
        self._processing_busy = False
        self._processing_task = None
        if payload.get("generation") == self._processing_generation:
            self._data_tab.set_row_labels(payload["labels"])
            self._data_tab.display_array(payload["result"])
            self._data_tab.set_baseline_data(payload["baseline"])

            self._conc_tab.set_gas_names(payload["gas_names"])
            if payload["all_results"]:
                self._conc_tab.add_data_point(
                    payload["all_results"],
                    payload["labels"],
                    mode=payload["mode"],
                )
            self.status_changed.emit(
                f"处理完成 / Processed: {payload['duration_ms']:.0f} ms"
            )
        self._start_pending_processing()

    @Slot(str)
    def _on_processing_failed(self, message: str) -> None:
        self._processing_busy = False
        self._processing_task = None
        log.warning("Processing failed: %s", message)
        QMessageBox.warning(
            self,
            "处理错误 / Processing Error",
            f"数据处理失败：\n{message}",
        )
        self._start_pending_processing()

    def _start_pending_processing(self) -> None:
        if self._pending_frame is None:
            return
        frame = self._pending_frame
        self._pending_frame = None
        self._queue_frame_processing(frame)

    @Slot(object)
    def _on_calibration_changed(self, coeffs: np.ndarray | None) -> None:
        """When calibration changes, update gas pixel positions from Raman shifts."""
        if coeffs is None:
            return
        from ..calibration import pixel_from_raman
        for cfg in self._analyzer.gases:
            if cfg.raman_shift > 0:
                cfg.position = pixel_from_raman(cfg.raman_shift, coeffs)
        self._processing_generation += 1
        self._settings_tab.update_gas_table(self._analyzer.gases)
        self._reprocess_cached()

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

            # Gas analysis — per row group
            gas_names = [g.name for g in self._analyzer.gases]
            self._conc_tab.set_gas_names(gas_names)
            if result.shape[0] > 0:
                all_results = self._analyzer.analyze_groups(result)
                row_groups = self._processor.row_groups
                group_labels = [
                    f"行 {s}-{e}"
                    for s, e in (row_groups if row_groups else [(1, arr.shape[0])])
                ]
                mode = "index" if self._batch_timer.isActive() else "time"
                self._conc_tab.add_data_point(all_results, group_labels, mode=mode)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "处理错误 / Processing Error",
                f"数据处理失败：\n{exc}",
            )

    def _reprocess_cached(self) -> None:
        """Re-run full pipeline on cached image (for settings changes)."""
        if self._last_frame is not None:
            self._queue_frame_processing(self._last_frame)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        log.info("Application window closing")
        self._refresh_timer.stop()
        self._capture_timer.stop()
        self._batch_timer.stop()
        self._pending_frame = None
        self._processing_pool.waitForDone(1000)
        try:
            self._camera.uninitialize()
        except Exception as exc:
            log.warning("Failed to uninitialize camera on close: %s", exc)
        super().closeEvent(event)
