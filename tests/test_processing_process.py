from __future__ import annotations

import os
import time

import numpy as np

from tucam_control.gas_analyzer import GasConfig
from tucam_control.processing_process import ProcessDataProcessor, process_frame_payload


def _wait_for_outcome(processor: ProcessDataProcessor, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        outcome = processor.poll()
        if outcome is not None:
            return outcome
        time.sleep(0.01)
    raise AssertionError("processing process did not return a result")


def test_processing_runs_in_persistent_separate_process() -> None:
    processor = ProcessDataProcessor(timeout_seconds=10.0)
    frame = np.arange(8 * 16, dtype=np.uint16).reshape(8, 16)
    settings = {
        "row_groups_text": "1-4 5-8",
        "row_group_names": {
            "rows:1:4": "参考通道",
            "rows:5:8": "哈龙通道",
        },
        "row_aggregation": "sum",
        "arpls_enabled": False,
    }
    try:
        processor.submit(frame, settings, [], generation=7, batch_mode=True)
        first = _wait_for_outcome(processor)

        assert first.ok is True
        assert first.payload is not None
        assert first.payload["generation"] == 7
        assert first.payload["result"].shape == (2, 16)
        assert first.payload["group_ids"] == ["rows:1:4", "rows:5:8"]
        assert first.payload["labels"] == ["参考通道", "哈龙通道"]
        assert first.payload["processing_cpu_ms"] >= 0.0
        assert first.payload["processing_cpu_percent"] >= 0.0
        if os.name == "nt":
            assert first.payload["processing_memory_mb"] > 0.0
        assert first.payload["worker_pid"] != os.getpid()
        first_pid = first.payload["worker_pid"]

        processor.submit(frame + 1, settings, [], generation=8, batch_mode=False)
        second = _wait_for_outcome(processor)

        assert second.ok is True
        assert second.payload is not None
        assert second.payload["worker_pid"] == first_pid
        assert second.payload["generation"] == 8
    finally:
        processor.shutdown()

    assert processor.pid is None


def test_force_restart_recreates_processing_process() -> None:
    processor = ProcessDataProcessor(timeout_seconds=10.0)
    frame = np.ones((4, 8), dtype=np.uint16)
    settings = {"arpls_enabled": False}
    try:
        processor.submit(frame, settings, [], generation=1, batch_mode=False)
        first = _wait_for_outcome(processor)
        assert first.payload is not None
        first_pid = first.payload["worker_pid"]

        processor.force_restart("test restart")
        processor.submit(frame, settings, [], generation=2, batch_mode=False)
        second = _wait_for_outcome(processor)

        assert second.ok is True
        assert second.payload is not None
        assert second.payload["worker_pid"] != first_pid
    finally:
        processor.shutdown()


def test_baseline_only_output_still_calculates_concentration_from_corrected_data() -> None:
    x = np.arange(128, dtype=float)
    spectrum = 100.0 + 0.2 * x + 500.0 * np.exp(-((x - 60.0) / 2.0) ** 2)
    frame = np.tile(spectrum, (4, 1)).astype(np.uint16)
    settings = {
        "row_groups_text": "1-4",
        "row_aggregation": "mean",
        "arpls_enabled": True,
        "arpls_mode": "baseline",
        "arpls_lam": 1e4,
        "arpls_max_iter": 50,
        "arpls_tol": 1e-6,
        "detection_threshold_sigma": 3.0,
    }
    gases = [GasConfig("Test", 60, 8, 1.0, detection_sigma=2.0)]

    payload = process_frame_payload(
        frame,
        settings,
        gases,
        generation=1,
        batch_mode=True,
    )

    result = payload["all_results"][0][0]
    assert payload["display_spectrum_mode"] == "baseline"
    assert payload["analysis_spectrum_mode"] == "corrected"
    assert result.detected is True
    assert result.concentration == 1.0
    assert result.peak_height > payload["result"][0, 60]
