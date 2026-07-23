# -*- coding: utf-8 -*-
"""Crash-isolated process proxy for all TUCam SDK operations."""

from __future__ import annotations

import multiprocessing as mp
import logging
import os
import queue
import threading
import time
from typing import Any

from .camera_types import CameraInfo
log = logging.getLogger("tucam_control.camera_process")


def _put_latest(frame_queue, item) -> None:
    try:
        frame_queue.put_nowait(item)
    except queue.Full:
        try:
            frame_queue.get_nowait()
        except queue.Empty:
            pass
        frame_queue.put_nowait(item)


def _sdk_process_main(connection, frame_queue) -> None:
    os.environ["TUCAM_LOG_FILE"] = "tucam_sdk_process.log"
    from .camera import CameraController

    camera = CameraController()
    capture_stop = threading.Event()
    capture_thread: threading.Thread | None = None

    def capture_loop() -> None:
        while not capture_stop.is_set() and camera.is_capturing:
            arr = camera.wait_for_frame(timeout_ms=500)
            if capture_stop.is_set() or not camera.is_capturing:
                break
            if arr is None:
                if camera.last_frame_error:
                    _put_latest(frame_queue, ("error", camera.last_frame_error))
                    break
                continue
            telemetry = {}
            for name, reader in {
                "exposure_readback_ms": camera.get_exposure_time,
                "temperature_readback_c": camera.get_sensor_temperature,
                "fan_readback": camera.get_fan_gear,
                "bit_depth": camera.get_bit_depth,
                "working_mode": camera.get_working_mode,
            }.items():
                try:
                    telemetry[name] = reader()
                except Exception:
                    pass
            _put_latest(frame_queue, ("frame", arr, telemetry))

    try:
        while True:
            request_id, method, args = connection.recv()
            try:
                if method == "shutdown":
                    capture_stop.set()
                    if camera.is_capturing:
                        camera.stop_capture()
                    camera.uninitialize()
                    connection.send((request_id, True, None))
                    break
                if method == "start_capture":
                    camera.start_capture()
                    capture_stop.clear()
                    capture_thread = threading.Thread(target=capture_loop, daemon=True)
                    capture_thread.start()
                    result = None
                elif method == "abort_wait":
                    capture_stop.set()
                    camera.abort_wait()
                    if capture_thread is not None:
                        capture_thread.join(timeout=2.0)
                        if capture_thread.is_alive():
                            raise RuntimeError("SDK capture thread did not exit after AbortWait")
                    result = None
                elif method == "ping":
                    result = os.getpid()
                elif method == "finish_stop_capture":
                    camera.finish_stop_capture()
                    result = None
                else:
                    result = getattr(camera, method)(*args)
                connection.send((request_id, True, result))
            except Exception as exc:
                connection.send((request_id, False, f"{type(exc).__name__}: {exc}"))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        try:
            camera.uninitialize()
        except Exception:
            pass


class ProcessCameraController:
    """Camera API compatible proxy with hard timeouts around native SDK calls."""

    MODE_LABELS = {0: "HDR", 1: "Std_High", 2: "Std_Low"}

    def __init__(self) -> None:
        self._ctx = mp.get_context("spawn")
        self._process = None
        self._connection = None
        self._frame_queue = None
        self._rpc_lock = threading.Lock()
        self._request_id = 0
        self._is_open = False
        self._is_capturing = False
        self._last_frame_error: str | None = None
        self._telemetry: dict[str, Any] = {}
        self._exposure_ms = 1000.0

    def _start_process(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        parent, child = self._ctx.Pipe()
        self._frame_queue = self._ctx.Queue(maxsize=2)
        self._process = self._ctx.Process(
            target=_sdk_process_main,
            args=(child, self._frame_queue),
            name="TUCamSDKProcess",
            daemon=True,
        )
        self._process.start()
        child.close()
        self._connection = parent
        log.info("SDK process started pid=%s", self._process.pid)

    def _terminate_process(self, reason: str, expected_process=None) -> None:
        process = self._process
        if expected_process is not None and process is not expected_process:
            return
        if process is not None and process.is_alive():
            log.error("Terminating SDK process pid=%s: %s", process.pid, reason)
            process.terminate()
            process.join(timeout=2.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
        self._process = self._connection = self._frame_queue = None
        self._is_open = self._is_capturing = False

    def _rpc(self, method: str, *args, timeout: float = 5.0):
        self._start_process()
        with self._rpc_lock:
            process = self._process
            connection = self._connection
            self._request_id += 1
            request_id = self._request_id
            try:
                connection.send((request_id, method, args))
                if not connection.poll(timeout):
                    raise TimeoutError(f"{method} exceeded {timeout:.1f} s")
                response_id, ok, payload = connection.recv()
                if response_id != request_id:
                    raise RuntimeError("SDK response sequence mismatch")
            except (EOFError, BrokenPipeError, OSError, TimeoutError) as exc:
                self._terminate_process(str(exc), expected_process=process)
                raise RuntimeError(f"SDK process failure during {method}: {exc}") from exc
            if not ok:
                raise RuntimeError(payload)
            return payload

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def last_frame_error(self) -> str | None:
        return self._last_frame_error

    def initialize(self) -> int:
        return int(self._rpc("initialize", timeout=8.0))

    def ping(self) -> int:
        return int(self._rpc("ping", timeout=3.0))

    def force_terminate(self, reason: str = "requested by application") -> None:
        self._terminate_process(reason)

    def open(self, index: int = 0) -> None:
        self._rpc("open", index, timeout=15.0)
        self._is_open = True

    def close(self) -> None:
        if self._is_open:
            self._rpc("close", timeout=8.0)
        self._is_open = False

    def uninitialize(self) -> None:
        if self._process is None:
            return
        try:
            self._rpc("shutdown", timeout=8.0)
        finally:
            if self._process is not None:
                self._process.join(timeout=1.0)
            self._process = self._connection = self._frame_queue = None
            self._is_open = self._is_capturing = False

    def start_capture(self) -> None:
        self._rpc("start_capture", timeout=8.0)
        self._is_capturing = True
        self._last_frame_error = None

    def abort_wait(self) -> None:
        if self._is_capturing:
            self._rpc("abort_wait", timeout=4.0)

    def finish_stop_capture(self) -> None:
        if self._is_capturing:
            self._rpc("finish_stop_capture", timeout=5.0)
        self._is_capturing = False

    def stop_capture(self) -> None:
        self.abort_wait()
        self.finish_stop_capture()

    def wait_for_frame(self, timeout_ms: int = 2000):
        if not self._is_capturing or self._frame_queue is None:
            return None
        try:
            event = self._frame_queue.get(timeout=max(0.05, timeout_ms / 1000.0))
        except queue.Empty:
            return None
        if event[0] == "error":
            self._last_frame_error = event[1]
            return None
        _, arr, telemetry = event
        self._telemetry.update(telemetry)
        self._last_frame_error = None
        return arr

    def capture_single(self):
        self.start_capture()
        try:
            return self.wait_for_frame(int(self._exposure_ms + 3000))
        finally:
            self.stop_capture()

    def connection_status(self):
        if self._is_capturing:
            return None
        return self._rpc("connection_status")

    def is_connected(self) -> bool:
        return self.connection_status() is not False

    def set_exposure_time(self, value: float) -> None:
        self._rpc("set_exposure_time", value)
        self._exposure_ms = value

    def __getattr__(self, name: str):
        if name.startswith("get_") and self._is_capturing:
            cache_key = {
                "get_exposure_time": "exposure_readback_ms",
                "get_sensor_temperature": "temperature_readback_c",
                "get_fan_gear": "fan_readback",
                "get_bit_depth": "bit_depth",
                "get_working_mode": "working_mode",
            }.get(name)
            if cache_key in self._telemetry:
                return lambda: self._telemetry[cache_key]
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args: self._rpc(name, *args)

    def __del__(self) -> None:
        try:
            self._terminate_process("proxy destroyed")
        except Exception:
            pass
