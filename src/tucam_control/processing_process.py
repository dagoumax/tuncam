# -*- coding: utf-8 -*-
"""Persistent process for CPU-bound Raman image processing."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import logging
import multiprocessing as mp
import os
import sys
import time
from typing import Any

import numpy as np

from .data_processor import DataProcessor
from .gas_analyzer import GasAnalyzer
from .raman_signal_diagnostic import assess_raman_signal
from .row_groups import describe_row_groups


log = logging.getLogger("tucam_control.processing_process")


def _build_pipeline(settings: dict, gas_configs: list) -> tuple[DataProcessor, GasAnalyzer]:
    row_groups = DataProcessor.parse_groups(settings.get("row_groups_text", ""))
    processor = DataProcessor()
    processor.row_groups = row_groups
    processor.row_aggregation = settings.get(
        "row_aggregation",
        DataProcessor.ROW_AGGREGATION_SUM,
    )
    processor.merge_factor = settings.get("merge_factor", 1)
    processor.arPLS_enabled = settings.get("arpls_enabled", False)
    processor.baseline_mode = settings.get("arpls_mode", "raw")
    processor.arPLS_lam = settings.get("arpls_lam", 1e5)
    processor.arPLS_max_iter = settings.get("arpls_max_iter", 50)
    processor.arPLS_tol = settings.get("arpls_tol", 1e-6)

    analyzer = GasAnalyzer()
    analyzer.gases = gas_configs
    analyzer.merge_factor = processor.merge_factor
    analyzer.threshold_sigma = settings.get("detection_threshold_sigma", 3.0)
    # arPLS output mode controls the Raman-page display only. Peak detection
    # always uses corrected data while arPLS is enabled.
    analyzer.baseline_corrected = bool(settings.get("arpls_enabled", False))
    return processor, analyzer


def _working_set_bytes() -> int | None:
    """Return current-process resident memory without an optional dependency."""
    if sys.platform != "win32":
        return None
    try:
        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        handle = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.WorkingSetSize) if ok else None
    except Exception:
        return None


def _run_pipeline(
    frame: np.ndarray,
    processor: DataProcessor,
    analyzer: GasAnalyzer,
    generation: int,
    batch_mode: bool,
    settings: dict,
) -> dict:
    started = time.perf_counter()
    cpu_started = time.process_time()
    row_groups = processor.row_groups

    result = processor.process(frame)
    analysis_result = processor.last_analysis_result
    if analysis_result is None:
        analysis_result = result
    group_descriptors = describe_row_groups(
        row_groups,
        frame.shape[0],
        settings.get("row_group_names", {}),
    )
    group_ids = [group.key for group in group_descriptors]
    labels = [group.label for group in group_descriptors]
    gas_names = [gas.name for gas in analyzer.gases]
    all_results = (
        analyzer.analyze_groups(analysis_result)
        if analysis_result.shape[0] > 0
        else []
    )
    signal_assessment = assess_raman_signal(
        analysis_result,
        labels,
        analyzer.gases,
        processor.merge_factor,
        group_ids=group_ids,
    )
    duration_ms = (time.perf_counter() - started) * 1000.0
    cpu_ms = (time.process_time() - cpu_started) * 1000.0
    working_set = _working_set_bytes()
    return {
        "generation": generation,
        "duration_ms": duration_ms,
        "processing_cpu_ms": cpu_ms,
        "processing_cpu_percent": (
            100.0 * cpu_ms / duration_ms if duration_ms > 0.0 else 0.0
        ),
        "processing_memory_mb": (
            working_set / (1024.0 * 1024.0) if working_set is not None else None
        ),
        "worker_pid": os.getpid(),
        "result": result,
        "baseline": processor.last_baseline,
        "labels": labels,
        "group_ids": group_ids,
        "gas_names": gas_names,
        "all_results": all_results,
        "raman_signal": signal_assessment,
        "mode": "time",
        "display_spectrum_mode": processor.baseline_mode,
        "analysis_spectrum_mode": (
            "corrected" if processor.arPLS_enabled else "raw"
        ),
        "batch_mode": bool(batch_mode),
    }


def process_frame_payload(
    frame: np.ndarray,
    settings: dict,
    gas_configs: list,
    generation: int,
    batch_mode: bool,
) -> dict:
    """Run the complete processing pipeline and return a UI-ready payload."""
    processor, analyzer = _build_pipeline(settings, gas_configs)
    return _run_pipeline(
        frame,
        processor,
        analyzer,
        generation,
        batch_mode,
        settings,
    )


def _processing_process_main(connection, shared_buffer) -> None:
    cached_settings = None
    cached_gas_configs = None
    processor = None
    analyzer = None
    try:
        while True:
            request_id, method, payload = connection.recv()
            if method == "shutdown":
                connection.send((request_id, True, None))
                break
            if method != "process":
                connection.send(
                    (request_id, False, f"Unknown processing method: {method}")
                )
                continue

            try:
                (
                    shape,
                    dtype_string,
                    settings,
                    gas_configs,
                    generation,
                    batch_mode,
                ) = payload
                dtype = np.dtype(dtype_string)
                element_count = int(np.prod(shape))
                frame = np.frombuffer(
                    shared_buffer,
                    dtype=dtype,
                    count=element_count,
                ).reshape(shape)
                if (
                    processor is None
                    or analyzer is None
                    or settings != cached_settings
                    or gas_configs != cached_gas_configs
                ):
                    processor, analyzer = _build_pipeline(settings, gas_configs)
                    cached_settings = dict(settings)
                    cached_gas_configs = list(gas_configs)
                result = _run_pipeline(
                    frame,
                    processor,
                    analyzer,
                    generation,
                    batch_mode,
                    settings,
                )
                connection.send((request_id, True, result))
            except Exception as exc:
                connection.send(
                    (request_id, False, f"{type(exc).__name__}: {exc}")
                )
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        try:
            connection.close()
        except Exception:
            pass


@dataclass(frozen=True)
class ProcessingOutcome:
    ok: bool
    payload: dict[str, Any] | None = None
    error: str | None = None


class ProcessDataProcessor:
    """Non-blocking proxy for a persistent CPU-bound processing process."""

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self._ctx = mp.get_context("spawn")
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._process = None
        self._connection = None
        self._shared_buffer = None
        self._buffer_nbytes = 0
        self._request_id = 0
        self._active_request_id: int | None = None
        self._active_started = 0.0

    @property
    def is_busy(self) -> bool:
        return self._active_request_id is not None

    @property
    def pid(self) -> int | None:
        if self._process is None or not self._process.is_alive():
            return None
        return int(self._process.pid)

    def _ensure_buffer(self, nbytes: int) -> None:
        if self._shared_buffer is not None and self._buffer_nbytes >= nbytes:
            return
        if self.is_busy:
            raise RuntimeError("Cannot resize the processing buffer while busy")
        self._terminate_process("resizing shared frame buffer")
        self._shared_buffer = self._ctx.RawArray("B", int(nbytes))
        self._buffer_nbytes = int(nbytes)

    def _start_process(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        if self._shared_buffer is None:
            raise RuntimeError("Processing buffer has not been initialized")
        parent, child = self._ctx.Pipe()
        process = self._ctx.Process(
            target=_processing_process_main,
            args=(child, self._shared_buffer),
            name="RamanProcessingProcess",
            daemon=True,
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        log.info("Processing process started pid=%s", process.pid)

    def submit(
        self,
        frame: np.ndarray,
        settings: dict,
        gas_configs: list,
        generation: int,
        batch_mode: bool,
    ) -> int:
        if self.is_busy:
            raise RuntimeError("Processing process is already busy")
        contiguous = np.ascontiguousarray(frame)
        self._ensure_buffer(contiguous.nbytes)
        self._start_process()

        target = np.frombuffer(
            self._shared_buffer,
            dtype=contiguous.dtype,
            count=contiguous.size,
        ).reshape(contiguous.shape)
        np.copyto(target, contiguous, casting="no")

        self._request_id += 1
        request_id = self._request_id
        request_payload = (
            tuple(contiguous.shape),
            contiguous.dtype.str,
            settings,
            gas_configs,
            int(generation),
            bool(batch_mode),
        )
        try:
            self._connection.send((request_id, "process", request_payload))
        except (BrokenPipeError, EOFError, OSError) as exc:
            self._terminate_process(f"submit failed: {exc}")
            raise RuntimeError(f"Processing process submit failed: {exc}") from exc
        self._active_request_id = request_id
        self._active_started = time.monotonic()
        return request_id

    def poll(self) -> ProcessingOutcome | None:
        if not self.is_busy:
            return None
        process = self._process
        connection = self._connection
        if process is None or connection is None or not process.is_alive():
            exit_code = None if process is None else process.exitcode
            self._terminate_process(
                f"process exited unexpectedly with code {exit_code}"
            )
            return ProcessingOutcome(
                False,
                error=f"Processing process exited unexpectedly ({exit_code})",
            )

        if connection.poll(0):
            try:
                response_id, ok, payload = connection.recv()
            except (BrokenPipeError, EOFError, OSError) as exc:
                self._terminate_process(f"receive failed: {exc}")
                return ProcessingOutcome(
                    False,
                    error=f"Processing process receive failed: {exc}",
                )
            expected_id = self._active_request_id
            self._active_request_id = None
            if response_id != expected_id:
                self._terminate_process("response sequence mismatch")
                return ProcessingOutcome(
                    False,
                    error="Processing process response sequence mismatch",
                )
            if ok:
                return ProcessingOutcome(True, payload=payload)
            return ProcessingOutcome(False, error=str(payload))

        elapsed = time.monotonic() - self._active_started
        if elapsed > self._timeout_seconds:
            self._terminate_process(
                f"processing exceeded {self._timeout_seconds:.1f} seconds"
            )
            return ProcessingOutcome(
                False,
                error=(
                    "Processing timed out after "
                    f"{self._timeout_seconds:.1f} seconds; worker was restarted"
                ),
            )
        return None

    def _terminate_process(self, reason: str) -> None:
        process = self._process
        connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        if process is not None and process.is_alive():
            reporter = (
                log.info
                if reason in {"shutdown", "resizing shared frame buffer"}
                else log.warning
            )
            reporter(
                "Terminating processing process pid=%s: %s",
                process.pid,
                reason,
            )
            process.terminate()
            process.join(timeout=2.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
        elif process is not None:
            process.join(timeout=0.1)
        self._process = None
        self._connection = None
        self._active_request_id = None
        self._active_started = 0.0

    def force_restart(self, reason: str = "requested") -> None:
        self._terminate_process(reason)

    def shutdown(self) -> None:
        process = self._process
        connection = self._connection
        if process is not None and process.is_alive() and connection is not None:
            if not self.is_busy:
                self._request_id += 1
                request_id = self._request_id
                try:
                    connection.send((request_id, "shutdown", None))
                    if connection.poll(1.5):
                        connection.recv()
                        process.join(timeout=1.0)
                except (BrokenPipeError, EOFError, OSError):
                    pass
        self._terminate_process("shutdown")
        self._shared_buffer = None
        self._buffer_nbytes = 0

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass
