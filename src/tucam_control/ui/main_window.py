# -*- coding: utf-8 -*-
"""Main window with tabbed layout for camera control application."""

from __future__ import annotations

import copy
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QStatusBar,
    QMessageBox,
    QFileDialog,
)

from ..camera import CameraController
from ..concentration_smoother import AdaptiveConcentrationSmoother
from ..data_processor import DataProcessor
from ..debug_log import get_debug_logger
from ..gas_analyzer import GasAnalyzer
from ..resources import project_root
from ..settings_store import load_user_settings, save_user_settings
from .acquisition_tab import AcquisitionTab
from .settings_tab import SettingsTab
from .data_tab import DataTab
from .concentration_tab import ConcentrationTab


DEFAULT_SAVE_DIR = "data"
CAPTURE_WAIT_TIMEOUT_MS = 500
log = get_debug_logger("ui.main_window")


class _ProcessingSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _CaptureWorker(QObject):
    frame_ready = Signal(int, object)
    telemetry_ready = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)

    def __init__(self, camera: CameraController, generation: int) -> None:
        super().__init__()
        self._camera = camera
        self._generation = generation
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    @Slot()
    def run(self) -> None:
        try:
            while not self._stop_requested and self._camera.is_capturing:
                arr = self._camera.wait_for_frame(timeout_ms=CAPTURE_WAIT_TIMEOUT_MS)
                if self._stop_requested or not self._camera.is_capturing:
                    break
                if arr is None:
                    if self._camera.last_frame_error:
                        self.failed.emit(self._generation, self._camera.last_frame_error)
                        break
                    if self._camera.connection_status() is False:
                        self.failed.emit(self._generation, "设备连接已断开")
                        break
                    continue
                self.frame_ready.emit(self._generation, arr)
                self.telemetry_ready.emit(self._generation, self._read_telemetry())
        except Exception as exc:
            log.exception("Capture worker failed")
            self.failed.emit(self._generation, str(exc))
        finally:
            self.finished.emit(self._generation)
            QThread.currentThread().quit()

    def _read_telemetry(self) -> dict:
        telemetry = {}
        readers = {
            "exposure_readback_ms": self._camera.get_exposure_time,
            "temperature_readback_c": self._camera.get_sensor_temperature,
            "fan_readback": self._camera.get_fan_gear,
            "bit_depth": self._camera.get_bit_depth,
            "working_mode": self._camera.get_working_mode,
        }
        for name, reader in readers.items():
            try:
                telemetry[name] = reader()
            except Exception as exc:
                log.debug("Capture telemetry %s failed: %s", name, exc)
        return telemetry


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
            processor.row_aggregation = self._settings.get("row_aggregation", DataProcessor.ROW_AGGREGATION_SUM)
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
        self._concentration_smoother = AdaptiveConcentrationSmoother()
        self._settings: dict = {
            "exposure_time_ms": 1000.0,
            "temperature_c": -10.0,
            "fan_gear": 0,
            "working_mode": 0,
            "auto_save": False,
            "save_dir": DEFAULT_SAVE_DIR,
            "row_groups_text": "",
            "row_aggregation": DataProcessor.ROW_AGGREGATION_SUM,
            "merge_factor": 1,
            "arpls_enabled": True,
            "arpls_mode": "corrected",
            "arpls_lam": 1e5,
            "arpls_max_iter": 50,
            "arpls_tol": 1e-6,
            "concentration_smoothing": "balanced",
            "batch_interval_ms": 1000,
        }
        try:
            persisted_settings, persisted_gases = load_user_settings()
            for key, default in tuple(self._settings.items()):
                if key not in persisted_settings:
                    continue
                value = persisted_settings[key]
                if isinstance(default, bool):
                    if isinstance(value, bool):
                        self._settings[key] = value
                elif isinstance(default, int):
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        self._settings[key] = int(value)
                elif isinstance(default, float):
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        self._settings[key] = float(value)
                elif isinstance(value, str):
                    self._settings[key] = value
            if self._settings["row_aggregation"] not in (
                DataProcessor.ROW_AGGREGATION_SUM,
                DataProcessor.ROW_AGGREGATION_MEAN,
            ):
                self._settings["row_aggregation"] = DataProcessor.ROW_AGGREGATION_SUM
            if persisted_gases:
                self._analyzer.gases = persisted_gases
            log.info("Loaded user settings: keys=%s gases=%s", sorted(persisted_settings), len(persisted_gases))
        except Exception as exc:
            log.warning("Could not load user settings; defaults will be used: %s", exc)
        self._was_connected = False
        self._disconnect_warned = False
        self._last_frame: np.ndarray | None = None
        self._processing_busy = False
        self._pending_frame: np.ndarray | None = None
        self._processing_task: _ProcessingTask | None = None
        self._processing_generation = 0
        self._frame_count = 0
        self._last_frame_perf: float | None = None
        self._processing_durations_ms: deque[float] = deque(maxlen=30)
        self._dropped_pending_frames = 0
        self._auto_save_error_reported = False
        self._capture_thread: QThread | None = None
        self._capture_worker: _CaptureWorker | None = None
        self._capture_generation = 0
        self._capture_stopping = False
        self._diagnostics: dict = {
            "connection": "未连接 / Disconnected",
            "frame_count": 0,
            "frame_interval_ms": "--",
            "shape": "--",
            "dtype": "",
            "min": "--",
            "max": "--",
            "mean": "--",
            "processing_ms": "--",
            "processing_avg_ms": "--",
            "processing_busy": False,
            "pending_frame": False,
            "dropped_frames": 0,
            "exposure_readback_ms": "--",
            "temperature_readback_c": "--",
            "fan_readback": "--",
            "data_format": "--",
            "bit_depth": "--",
            "working_mode": "--",
            "batch_interval_ms": 1000,
            "errors": [],
        }
        self._processing_pool = QThreadPool(self)
        self._processing_pool.setMaxThreadCount(1)

        self._setup_ui()
        self._settings_tab.load_settings(self._settings, self._analyzer.gases)
        self._connect_signals()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._on_refresh_info)
        self._refresh_timer.start()

        self._batch_images: list[tuple[str, np.ndarray]] = []
        self._batch_idx: int = 0
        self._batch_timer = QTimer(self)
        self._batch_timer.setInterval(self._settings["batch_interval_ms"])
        self._batch_timer.timeout.connect(self._on_batch_tick)

        QTimer.singleShot(0, self._try_connect)

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
                self._set_diagnostic_error("connection", "未检测到相机")
                self._update_diagnostics(connection="未检测到相机 / No camera detected")
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
            self._clear_diagnostic_error("connection")
            self._update_diagnostics(connection=f"已连接 / Connected: {info.model or '--'}")
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
            self._set_diagnostic_error("connection", f"连接失败: {exc}")
            self._update_diagnostics(connection=f"连接失败 / Failed: {exc}")
            self._was_connected = False

    def _apply_current_settings(self) -> None:
        s = self._settings
        errors: list[str] = []
        try:
            self._camera.configure_scientific_frame_format()
        except Exception as exc:
            log.warning("Failed to configure scientific frame format: %s", exc)
            errors.append(f"格式设置失败: {exc}")
        try:
            self._camera.set_exposure_time(s["exposure_time_ms"])
        except Exception as exc:
            log.warning("Failed to apply exposure_time_ms=%s: %s", s.get("exposure_time_ms"), exc)
            errors.append(f"曝光设置失败: {exc}")
        try:
            self._camera.set_temperature_target(s["temperature_c"])
        except Exception as exc:
            log.warning("Failed to apply temperature_c=%s: %s", s.get("temperature_c"), exc)
            errors.append(f"温度设置失败: {exc}")
        try:
            self._camera.set_fan_gear(s["fan_gear"])
        except Exception as exc:
            log.warning("Failed to apply fan_gear=%s: %s", s.get("fan_gear"), exc)
            errors.append(f"风扇设置失败: {exc}")
        try:
            self._camera.set_working_mode(s.get("working_mode", 0))
        except Exception as exc:
            log.warning("Failed to apply working_mode=%s: %s", s.get("working_mode", 0), exc)
            errors.append(f"模式设置失败: {exc}")
        if errors:
            self._set_diagnostic_error("settings", "；".join(errors))
        else:
            self._clear_diagnostic_error("settings")
        self._refresh_camera_readbacks()

    def _refresh_camera_readbacks(self) -> None:
        if not self._camera.is_open:
            return

        readback_errors: list[str] = []

        def _read(label: str, reader, formatter=str) -> str:
            try:
                return formatter(reader())
            except Exception as exc:
                log.debug("Readback %s failed: %s", label, exc)
                readback_errors.append(f"{label}: {exc}")
                return "N/A"

        self._update_diagnostics(
            exposure_readback_ms=_read("exposure", self._camera.get_exposure_time, lambda v: f"{v:.1f}"),
            temperature_readback_c=_read("sensor temperature", self._camera.get_sensor_temperature, lambda v: f"{v:.1f}"),
            fan_readback=_read("fan gear", self._camera.get_fan_gear),
            data_format=_read("data format", self._camera.get_data_format),
            bit_depth=_read("bit depth", self._camera.get_bit_depth),
            working_mode=_read("working mode", self._camera.get_working_mode),
        )
        if readback_errors:
            self._set_diagnostic_error("readback", "读回失败: " + "；".join(readback_errors))
        else:
            self._clear_diagnostic_error("readback")

    @Slot()
    def _on_reconnect(self) -> None:
        log.info("Reconnect requested")
        self._update_diagnostics(connection="正在重新连接 / Reconnecting")
        if not self._stop_continuous_capture("reconnect"):
            QMessageBox.warning(
                self,
                "无法重新连接 / Reconnect Blocked",
                "采集线程仍在运行，为避免 SDK 崩溃，本次重新连接已取消。",
            )
            return

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
        log.info("Batch load requested: folder=%s", folder)
        tif_files = sorted(
            glob.glob(str(folder_path / "*.tif"))
            + glob.glob(str(folder_path / "*.tiff"))
        )
        if not tif_files:
            log.warning("Batch load found no TIF files: folder=%s", folder)
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
                else:
                    log.warning("Batch skipped non-grayscale image: path=%s ndim=%s", f, arr.ndim)
            except Exception as exc:
                log.warning("Batch skipped unreadable image: path=%s error=%s", f, exc)
                self.status_changed.emit(f"跳过 {Path(f).name}: {exc}")

        if not self._batch_images:
            log.warning("Batch load failed: no usable images in folder=%s", folder)
            QMessageBox.warning(self, "加载失败", "没有成功加载任何图像。")
            return

        self._batch_idx = 0
        self._conc_tab.clear_history()
        self._acq_tab.set_batch_state(True)
        self._batch_timer.setInterval(self._settings.get("batch_interval_ms", 1000))
        self._update_diagnostics(batch_interval_ms=self._batch_timer.interval())
        self._batch_timer.start()
        log.info(
            "Batch test started: usable_images=%s total_tif_files=%s interval_ms=%s folder=%s",
            len(self._batch_images),
            len(tif_files),
            self._batch_timer.interval(),
            folder,
        )
        self.status_changed.emit(f"批量测试: {len(self._batch_images)} 张图像")

    @Slot()
    def _on_batch_tick(self) -> None:
        if self._processing_busy:
            return
        if self._batch_idx >= len(self._batch_images):
            self._on_batch_stop()
            return
        path, arr = self._batch_images[self._batch_idx]
        self._batch_idx += 1
        log.info(
            "Batch frame queued: index=%s total=%s path=%s shape=%s dtype=%s",
            self._batch_idx,
            len(self._batch_images),
            path,
            arr.shape,
            arr.dtype,
        )
        self._acq_tab.display_frame(arr)
        self.status_changed.emit(f"Batch [{self._batch_idx}/{len(self._batch_images)}] {Path(path).name}")

    @Slot()
    def _on_batch_stop(self) -> None:
        self._batch_timer.stop()
        self._acq_tab.set_batch_state(False)
        log.info(
            "Batch test stopped: processed_or_queued=%s total=%s",
            self._batch_idx,
            len(self._batch_images),
        )
        self.status_changed.emit(f"批量测试结束 / Batch finished ({len(self._batch_images)} images)")

    # ------------------------------------------------------------------
    # Auto-save helper
    # ------------------------------------------------------------------

    def _ensure_save_dir(self) -> str | None:
        d = str(self._settings.get("save_dir", DEFAULT_SAVE_DIR)).strip() or DEFAULT_SAVE_DIR
        path = Path(d).expanduser()
        if not path.is_absolute():
            path = project_root() / path
        try:
            path.mkdir(parents=True, exist_ok=True)
            return str(path)
        except Exception as exc:
            log.exception("Failed to create save directory: %s", path)
            self._set_diagnostic_error("save", f"存储目录创建失败: {path}: {exc}")
            return None

    def _save_array_image(self, arr: np.ndarray, path: str | Path) -> None:
        image = np.ascontiguousarray(arr)
        suffix = Path(path).suffix.lower()
        if suffix in {".jpg", ".jpeg"} and image.dtype != np.uint8:
            min_val = float(np.min(image))
            max_val = float(np.max(image))
            if max_val > min_val:
                image = ((image.astype(np.float32) - min_val) * (255.0 / (max_val - min_val))).astype(np.uint8)
            else:
                image = np.zeros(image.shape, dtype=np.uint8)
        Image.fromarray(image).save(path)

    def _auto_save_frame(self, arr: np.ndarray) -> bool:
        if not self._settings.get("auto_save", False):
            return True
        save_dir = self._ensure_save_dir()
        if save_dir is None:
            self._handle_auto_save_failure("无法创建存储目录", stop_capture=True)
            return False
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = Path(save_dir) / f"{ts}.tif"
        try:
            self._save_array_image(arr, path)
            self._clear_diagnostic_error("save")
            self._auto_save_error_reported = False
            self.status_changed.emit(f"已自动存储 / Auto saved: {path}")
            log.info("Auto saved frame via Pillow: %s", path)
            return True
        except Exception as exc:
            log.exception("Auto save failed: path=%s", path)
            self._set_diagnostic_error("save", f"自动存储失败: {path}: {exc}")
            self._handle_auto_save_failure(f"{path}\n\n{exc}", stop_capture=True)
            return False

    def _handle_auto_save_failure(self, message: str, stop_capture: bool = False) -> None:
        if stop_capture:
            self._stop_capture_due_to_save_error()
        if self._auto_save_error_reported:
            return
        self._auto_save_error_reported = True
        QMessageBox.warning(
            self,
            "自动存储失败 / Auto Save Failed",
            "自动存储失败，采集已停止。\n\n"
            f"{message}\n\n"
            "请检查存储路径是否存在、是否有权限，或路径中是否包含 SDK 不支持的字符。",
        )

    def _stop_capture_due_to_save_error(self) -> None:
        log.warning("Stopping capture because auto-save failed")
        self._batch_timer.stop()
        self._stop_continuous_capture("auto-save error")
        self._acq_tab.set_capturing_state(False)
        self._acq_tab.set_batch_state(False)
        self.status_changed.emit("自动存储失败，采集已停止 / Auto-save failed, capture stopped")
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
                self._auto_save_frame(arr)
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
            self._start_capture_worker()
            self._acq_tab.set_capturing_state(True)
            self._clear_diagnostic_error("capture")
            log.info("Continuous capture worker started")
            self.status_changed.emit("连续采集中 / Continuous capture running")
        except Exception as exc:
            log.exception("Continuous capture start failed")
            self._stop_continuous_capture("start failure")
            self._set_diagnostic_error("capture", f"启动采集失败: {exc}")
            QMessageBox.critical(
                self,
                "启动采集失败 / Capture Start Failed",
                f"无法启动连续采集：\n{exc}",
            )

    @Slot()
    def _on_stop(self) -> None:
        log.info("Capture stop requested")
        self._stop_continuous_capture("user request")
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
        if self._last_frame is not None:
            try:
                self._save_array_image(self._last_frame, path)
                self.status_changed.emit(f"已保存 / Saved: {path}")
                log.info("Saved current frame via Pillow: %s", path)
                return
            except Exception as exc:
                log.exception("Manual save failed: path=%s", path)
                self._set_diagnostic_error("save", f"手动保存失败: {path}: {exc}")
                QMessageBox.warning(self, "保存失败 / Save Error", str(exc))
                return

        QMessageBox.warning(
            self,
            "没有可保存图像 / No Image",
            "当前没有可保存的图像。\n请先采集或载入一张图像。",
        )

    # ------------------------------------------------------------------
    # Continuous capture worker & refresh
    # ------------------------------------------------------------------

    def _start_capture_worker(self) -> None:
        if self._capture_thread is not None and self._capture_thread.isRunning():
            raise RuntimeError("Capture worker is already running")
        self._capture_generation += 1
        generation = self._capture_generation
        thread = QThread(self)
        worker = _CaptureWorker(self._camera, generation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.frame_ready.connect(self._on_capture_worker_frame)
        worker.telemetry_ready.connect(self._on_capture_worker_telemetry)
        worker.failed.connect(self._on_capture_worker_failed)
        worker.finished.connect(self._on_capture_worker_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._capture_thread = thread
        self._capture_worker = worker
        thread.start()

    def _stop_continuous_capture(self, reason: str) -> bool:
        if self._capture_stopping:
            return False
        self._capture_stopping = True
        self._capture_generation += 1
        worker = self._capture_worker
        thread = self._capture_thread
        try:
            log.info("Stopping continuous capture: %s", reason)
            if worker is not None:
                worker.request_stop()
            if self._camera.is_capturing:
                self._camera.abort_wait()
            if thread is not None and thread.isRunning():
                if not thread.wait(2000):
                    log.error("Capture worker did not stop within 2000 ms")
                    self._set_diagnostic_error("capture", "采集线程未能及时停止")
                    return False
            if self._camera.is_capturing:
                self._camera.finish_stop_capture()
            self._capture_worker = None
            self._capture_thread = None
            return True
        except Exception as exc:
            log.warning("Failed to stop continuous capture (%s): %s", reason, exc)
            self._set_diagnostic_error("capture", f"停止采集失败: {exc}")
            return False
        finally:
            self._capture_stopping = False

    @Slot(int, object)
    def _on_capture_worker_frame(self, generation: int, arr: np.ndarray) -> None:
        if generation != self._capture_generation or not self._camera.is_capturing:
            return
        self._clear_diagnostic_error("capture")
        log.debug("Continuous frame received: shape=%s dtype=%s", arr.shape, arr.dtype)
        self._acq_tab.display_frame(arr)
        self._auto_save_frame(arr)

    @Slot(int, object)
    def _on_capture_worker_telemetry(self, generation: int, telemetry: dict) -> None:
        if generation != self._capture_generation:
            return
        formatted = dict(telemetry)
        if "exposure_readback_ms" in formatted:
            formatted["exposure_readback_ms"] = f"{formatted['exposure_readback_ms']:.1f}"
        if "temperature_readback_c" in formatted:
            formatted["temperature_readback_c"] = f"{formatted['temperature_readback_c']:.1f}"
        self._update_diagnostics(**formatted)

    @Slot(int, str)
    def _on_capture_worker_failed(self, generation: int, message: str) -> None:
        if generation != self._capture_generation:
            return
        log.warning("Capture worker reported failure: %s", message)
        self._set_diagnostic_error("capture", f"采集线程失败: {message}")
        if "断开" in message:
            self._on_device_lost()
            return
        self._stop_continuous_capture("worker failure")
        self._acq_tab.set_capturing_state(False)
        QMessageBox.warning(
            self,
            "采集已停止 / Capture Stopped",
            f"后台采集发生错误：\n{message}",
        )

    @Slot(int)
    def _on_capture_worker_finished(self, generation: int) -> None:
        if generation != self._capture_generation or self._capture_stopping:
            return
        log.warning("Capture worker exited unexpectedly")
        self._stop_continuous_capture("worker exited")
        self._acq_tab.set_capturing_state(False)

    @Slot()
    def _on_refresh_info(self) -> None:
        if not self._camera.is_open:
            return
        if self._camera.is_capturing:
            return
        try:
            info = self._camera.get_device_info()
            self._acq_tab.update_telemetry(info)
            self._settings_tab.update_device_status(info)
            self._refresh_camera_readbacks()
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
        self._acq_tab.set_capturing_state(False)
        self._settings_tab.update_device_status(None)
        self._update_diagnostics(connection="已断开 / Disconnected")
        self._set_diagnostic_error("connection", "设备连接已断开")
        self._stop_continuous_capture("device lost")
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

        old_gas_signature = self._gas_signature(self._analyzer.gases)
        new_gas_signature = self._gas_signature(updates.get("gas_configs", self._analyzer.gases))
        old_smoothing = self._settings.get("concentration_smoothing", "balanced")

        self._settings.update({key: value for key, value in updates.items() if key != "gas_configs"})
        self._batch_timer.setInterval(self._settings.get("batch_interval_ms", 1000))
        self._update_diagnostics(batch_interval_ms=self._batch_timer.interval())
        self._processing_generation += 1
        if self._camera.is_open:
            resume_capture = self._camera.is_capturing
            if resume_capture:
                log.info("Pausing capture to apply camera settings safely")
                self._stop_continuous_capture("apply settings")
                if self._camera.is_capturing:
                    self._set_diagnostic_error("settings", "无法安全停止采集，设置未应用")
                    return
            self._apply_current_settings()
            if resume_capture:
                try:
                    self._camera.start_capture()
                    self._start_capture_worker()
                    self._acq_tab.set_capturing_state(True)
                    log.info("Capture resumed after applying camera settings")
                except Exception as exc:
                    log.exception("Failed to resume capture after applying settings")
                    self._acq_tab.set_capturing_state(False)
                    self._set_diagnostic_error("capture", f"设置后恢复采集失败: {exc}")
                    QMessageBox.warning(
                        self,
                        "恢复采集失败 / Resume Failed",
                        f"设置已经应用，但连续采集未能恢复：\n{exc}",
                    )

        self._processor.row_groups = groups
        self._processor.row_aggregation = self._settings.get(
            "row_aggregation", DataProcessor.ROW_AGGREGATION_SUM
        )
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
        new_smoothing = self._settings.get("concentration_smoothing", "balanced")
        self._concentration_smoother.set_profile(new_smoothing)
        self._conc_tab.set_export_smoothed(new_smoothing != "off")

        if old_gas_signature != new_gas_signature:
            log.info(
                "Gas configuration changed; clearing concentration history: old=%s new=%s",
                old_gas_signature,
                new_gas_signature,
            )
            self._concentration_smoother.reset()
            self._conc_tab.clear_history()
            self._conc_tab.set_gas_names([g.name for g in self._analyzer.gases])
        elif old_smoothing != new_smoothing:
            log.info("Concentration smoothing changed: old=%s new=%s", old_smoothing, new_smoothing)
            self._conc_tab.clear_history()

        self._reprocess_cached()

        try:
            path = save_user_settings(self._settings, self._analyzer.gases)
            log.info("User settings saved: %s", path)
            self._clear_diagnostic_error("settings_save")
        except Exception as exc:
            log.exception("Failed to save user settings")
            self._set_diagnostic_error("settings_save", f"设置保存失败: {exc}")

        self.status_changed.emit("设置已应用 / Settings applied")

    # ------------------------------------------------------------------
    # Frame → data processing
    # ------------------------------------------------------------------

    def _on_frame_ready(self, arr: np.ndarray) -> None:
        self._last_frame = arr.copy()
        now = time.perf_counter()
        interval_ms = None
        if self._last_frame_perf is not None:
            interval_ms = (now - self._last_frame_perf) * 1000
        self._last_frame_perf = now
        self._frame_count += 1
        self._update_diagnostics(
            frame_count=self._frame_count,
            frame_interval_ms=f"{interval_ms:.0f}" if interval_ms is not None else "--",
            shape=f"{arr.shape[0]}x{arr.shape[1]}",
            dtype=str(arr.dtype),
            min=int(arr.min()) if arr.size else "--",
            max=int(arr.max()) if arr.size else "--",
            mean=f"{float(arr.mean()):.2f}" if arr.size else "--",
        )
        if arr.size and int(arr.max()) == 0:
            self._set_diagnostic_error("frame", "图像为纯黑: max=0，请检查曝光、触发、光路或数据格式")
        elif arr.size and float(arr.mean()) < 1.0:
            self._set_diagnostic_error("frame", f"图像信号很低: mean={float(arr.mean()):.2f}")
        else:
            self._clear_diagnostic_error("frame")
        self._queue_frame_processing(arr)

    def _queue_frame_processing(self, arr: np.ndarray) -> None:
        if self._processing_busy:
            if self._pending_frame is not None:
                self._dropped_pending_frames += 1
            self._pending_frame = arr.copy()
            self._set_diagnostic_error("queue", "后台处理忙，已覆盖旧的待处理帧")
            self._update_diagnostics(
                processing_busy=True,
                pending_frame=True,
                dropped_frames=self._dropped_pending_frames,
            )
            return

        self._processing_busy = True
        self._pending_frame = None
        self._update_diagnostics(processing_busy=True, pending_frame=False)
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
        duration_ms = float(payload.get("duration_ms", 0.0))
        self._processing_durations_ms.append(duration_ms)
        avg_ms = sum(self._processing_durations_ms) / len(self._processing_durations_ms)
        self._update_diagnostics(
            processing_ms=f"{duration_ms:.0f}",
            processing_avg_ms=f"{avg_ms:.0f}",
            processing_busy=False,
            pending_frame=self._pending_frame is not None,
        )
        if payload.get("generation") == self._processing_generation:
            self._clear_diagnostic_error("processing")
            self._data_tab.set_row_labels(payload["labels"])
            self._data_tab.display_array(payload["result"])
            self._data_tab.set_baseline_data(payload["baseline"])

            self._conc_tab.set_gas_names(payload["gas_names"])
            if payload["all_results"]:
                display_results = self._concentration_smoother.smooth_groups(
                    payload["all_results"],
                    payload["labels"],
                    payload["mode"],
                )
                self._conc_tab.add_data_point(
                    display_results,
                    payload["labels"],
                    mode=payload["mode"],
                    raw_group_results=payload["all_results"],
                )
            log.info(
                "Processing finished: duration_ms=%.1f result_shape=%s labels=%s mode=%s",
                payload["duration_ms"],
                payload["result"].shape,
                payload["labels"],
                payload["mode"],
            )
            self.status_changed.emit(
                f"处理完成 / Processed: {payload['duration_ms']:.0f} ms"
            )
        self._start_pending_processing()

    @staticmethod
    def _gas_signature(configs: list) -> tuple:
        return tuple(
            (
                cfg.name,
                int(cfg.position),
                int(cfg.window),
                round(float(cfg.coefficient), 12),
                round(float(cfg.raman_shift), 6),
            )
            for cfg in configs
        )

    @Slot(str)
    def _on_processing_failed(self, message: str) -> None:
        self._processing_busy = False
        self._processing_task = None
        log.warning("Processing failed: %s", message)
        self._set_diagnostic_error("processing", f"处理失败: {message}")
        self._update_diagnostics(processing_busy=False, pending_frame=self._pending_frame is not None)
        QMessageBox.warning(
            self,
            "处理错误 / Processing Error",
            f"数据处理失败：\n{message}",
        )
        self._start_pending_processing()

    def _start_pending_processing(self) -> None:
        if self._pending_frame is None:
            self._clear_diagnostic_error("queue")
            self._update_diagnostics(processing_busy=False, pending_frame=False)
            return
        frame = self._pending_frame
        self._pending_frame = None
        self._queue_frame_processing(frame)

    def _update_diagnostics(self, **updates) -> None:
        self._diagnostics.update(updates)
        if hasattr(self, "_acq_tab"):
            self._acq_tab.update_diagnostics(self._diagnostics)

    def _set_diagnostic_error(self, key: str, message: str) -> None:
        errors_by_key = dict(self._diagnostics.get("_errors_by_key", {}))
        errors_by_key[key] = message
        self._diagnostics["_errors_by_key"] = errors_by_key
        self._diagnostics["errors"] = list(errors_by_key.values())
        if hasattr(self, "_acq_tab"):
            self._acq_tab.update_diagnostics(self._diagnostics)

    def _clear_diagnostic_error(self, key: str) -> None:
        errors_by_key = dict(self._diagnostics.get("_errors_by_key", {}))
        if key not in errors_by_key:
            return
        del errors_by_key[key]
        self._diagnostics["_errors_by_key"] = errors_by_key
        self._diagnostics["errors"] = list(errors_by_key.values())
        if hasattr(self, "_acq_tab"):
            self._acq_tab.update_diagnostics(self._diagnostics)

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
        self._batch_timer.stop()
        if not self._stop_continuous_capture("application close"):
            self._refresh_timer.start()
            event.ignore()
            QMessageBox.warning(
                self,
                "暂时无法关闭 / Close Blocked",
                "采集线程未能安全退出。程序已保留相机资源，请稍后再次关闭并查看诊断日志。",
            )
            return
        self._pending_frame = None
        self._processing_pool.waitForDone(1000)
        try:
            self._camera.uninitialize()
        except Exception as exc:
            log.warning("Failed to uninitialize camera on close: %s", exc)
        super().closeEvent(event)
