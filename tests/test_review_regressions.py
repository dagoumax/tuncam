from collections import deque
import csv
from datetime import datetime, timedelta
import queue
import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from tucam_control.background_io import BackgroundFileIO
from tucam_control.camera_process import ProcessCameraController, _put_latest
from tucam_control.concentration_export import write_concentration_csv
from tucam_control.gas_analyzer import GasResult
from tucam_control.threshold_statistics import ThresholdStatisticsTracker
from tucam_control.ui.concentration_tab import ConcentrationTab
from tucam_control.ui.main_window import MainWindow


@pytest.fixture
def camera():
    controller = ProcessCameraController()
    controller._process = Mock(is_alive=Mock(return_value=True))
    controller._frame_queue = queue.Queue()
    controller._is_capturing = True
    controller._session_id = 2
    controller._last_frame_monotonic = time.monotonic()
    yield controller
    controller._process = controller._frame_queue = None


def test_old_camera_session_is_ignored(camera):
    now = datetime.now().astimezone()
    camera._frame_queue.put(("error", 1, "old failure"))
    camera._frame_queue.put(("frame", 1, now, "old image", {}))
    camera._frame_queue.put(("frame", 2, now, "new image", {}))
    assert camera.wait_for_frame(100) == "new image"
    assert camera.last_frame_timestamp == now


def test_dead_sdk_process_is_detected(camera):
    camera._process.is_alive.return_value = False
    with pytest.raises(RuntimeError, match="exited"):
        camera.wait_for_frame(100)
    assert camera.connection_status() is False


def test_three_second_exposure_watchdog(camera):
    camera._exposure_ms = 3000
    camera._last_frame_monotonic = time.monotonic() - 4
    assert camera.wait_for_frame(50) is None
    camera._last_frame_monotonic = time.monotonic() - 10
    with pytest.raises(TimeoutError, match="9.0 seconds"):
        camera.wait_for_frame(50)


def test_full_frame_queue_keeps_latest():
    frames = queue.Queue(maxsize=1)
    frames.put("old")
    _put_latest(frames, "new")
    assert frames.get_nowait() == "new"


def test_statistics_window_can_be_enlarged():
    tracker = ThresholdStatisticsTracker(window_seconds=2)
    start = datetime(2026, 9, 15)
    for second in range(11):
        result = GasResult("gas", 0, 0, 1, 1, 1, 1, second / 100)
        tracker.update([[result]], ["probe"], start + timedelta(seconds=second))
    assert tracker.snapshots()[0].sample_count == 3
    tracker.set_window_seconds(60)
    snapshot = tracker.snapshots()[0]
    assert snapshot.sample_count == 11
    assert snapshot.mean_percent == pytest.approx(5)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.reader(stream))


def test_csv_aligns_probe_timestamps(tmp_path):
    start = datetime(2026, 9, 15)
    path = tmp_path / "aligned.csv"
    write_concentration_csv(path, [
        ("A", [1, 2], [start, start + timedelta(seconds=1)]),
        ("B", [3, 4], [start + timedelta(seconds=10), start + timedelta(seconds=11)]),
    ], sample_rate=1)
    rows = read_csv(path)
    assert len(rows) == 5
    assert rows[1][1:] == ["1.0000", ""]
    assert rows[3] == ["2026-09-15T00:00:10.000", "", "3.0000"]


def test_csv_does_not_interpolate_across_stop(tmp_path):
    start = datetime(2026, 9, 15)
    path = tmp_path / "gap.csv"
    write_concentration_csv(path, [("gas", [10, 20], [start, start + timedelta(seconds=60)])],
                            sample_rate=1000, breaks=[start])
    assert len(read_csv(path)) == 3


@pytest.mark.parametrize("rate", [500, 1000])
def test_export_chunk_boundaries_and_sampling(tmp_path, monkeypatch, rate):
    monkeypatch.setattr("tucam_control.concentration_export.EXPORT_CHUNK_SIZE", 31)
    start = datetime(2026, 9, 15)
    path = tmp_path / "chunked.csv"
    write_concentration_csv(path, [("gas", [0, 100], [start, start + timedelta(seconds=3)])], rate)
    rows = read_csv(path)[1:]
    assert len(rows) == 3 * rate + 1
    assert len({row[0] for row in rows}) == len(rows)
    assert float(rows[len(rows) // 2][1]) == pytest.approx(50)


def test_stop_invalidates_pending_processing():
    window = SimpleNamespace(
        _capture_stopping=False, _capture_generation=1, _processing_generation=3,
        _pending_frame=object(), _capture_worker=None, _capture_thread=None,
        _camera=SimpleNamespace(is_capturing=False), _conc_tab=Mock(),
        _raman_signal_monitor=Mock(),
    )
    assert MainWindow._stop_continuous_capture(window, "test")
    assert window._processing_generation == 4
    assert window._pending_frame is None


def test_cached_reprocess_is_not_new_measurement():
    timestamp = datetime.now().astimezone()
    window = SimpleNamespace(_last_frame=np.zeros((2, 2)), _last_frame_time=timestamp,
                             _processing_busy=False, _queue_frame_processing=Mock())
    MainWindow._reprocess_cached(window)
    assert window._queue_frame_processing.call_args.kwargs == {
        "measurement_time": timestamp, "is_measurement": False,
    }


def test_clear_resets_remote_and_processing():
    window = SimpleNamespace(_processing_generation=3, _pending_frame=object(),
                             _concentration_smoother=Mock(), _raman_signal_monitor=Mock(),
                             _remote_server=Mock(), _remote_measurement_id=20)
    MainWindow._on_history_cleared(window)
    window._remote_server.reset_measurements.assert_called_once()
    assert window._remote_measurement_id == 0
    assert window._processing_generation == 4
    assert window._pending_frame is None


@pytest.mark.parametrize("generation,measurement", [(2, True), (3, False)])
def test_obsolete_and_preview_results_do_not_advance_statistics(generation, measurement):
    window = SimpleNamespace(
        _processing_busy=True, _processing_durations_ms=deque(),
        _processing_cpu_percent=deque(), _processing_memory_mb=deque(),
        _pending_frame=None, _processing_generation=3,
        _processing_context=(datetime.now().astimezone(), measurement),
        _update_diagnostics=Mock(), _clear_diagnostic_error=Mock(),
        _start_pending_processing=Mock(), _data_tab=Mock(),
        _raman_signal_monitor=Mock(), _conc_tab=Mock(),
    )
    MainWindow._on_processing_finished(window, {
        "generation": generation, "labels": [], "result": np.zeros((1, 2)), "baseline": None,
    })
    window._raman_signal_monitor.update.assert_not_called()
    window._conc_tab.add_data_point.assert_not_called()
    window._start_pending_processing.assert_called_once()


def test_storage_timeout_is_reported_and_queue_cleared():
    worker = BackgroundFileIO(timeout_seconds=1)
    worker._active = ("job", "image", "unused", "unused.tmp", None)
    worker._started = time.monotonic() - 2
    worker._process = Mock(is_alive=Mock(return_value=False))
    worker._results = Mock(get_nowait=Mock(side_effect=queue.Empty))
    events = worker.poll()
    assert events[0][1] == "error"
    assert not worker.is_busy
    assert worker._process is None


def test_chart_and_resampling_break_at_stop():
    app = QApplication.instance() or QApplication([])
    tab = ConcentrationTab()
    start = datetime.now().astimezone()
    tab._history = {"probe": {"gas": ([10], [start])}}
    tab.mark_history_gap()
    times = [start, start + timedelta(seconds=60)]
    tab._draw_series([("gas", [10, 20], times, "red", ("probe", "gas"))], True)
    x, _ = tab._curve_items[("probe", "gas")].getData()
    assert np.isnan(x).any()
    assert not tab._animation_tail_cache
    assert len(tab._resampled_pairs([10, 20], times)[0]) == 2
    cleared = Mock()
    tab.history_cleared.connect(cleared)
    tab.clear_history()
    cleared.assert_called_once()
    assert tab._history_breaks == []
    tab.close()
    app.processEvents()


def await_file_job(worker):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        for event in worker.poll():
            if event[1] != "progress":
                return event
        time.sleep(0.02)
    pytest.fail("File worker did not finish")


def test_background_save_and_disk_error(tmp_path):
    worker = BackgroundFileIO()
    try:
        from PIL import Image
        path = tmp_path / "image.tif"
        frame = np.arange(16, dtype=np.uint16).reshape(4, 4)
        worker.submit("image", path, frame)
        assert await_file_job(worker)[1] == "done"
        with Image.open(path) as image:
            np.testing.assert_array_equal(np.asarray(image), frame)
        worker.submit("image", path / "impossible.tif", frame)
        assert await_file_job(worker)[1] == "error"
        assert path.is_file()
    finally:
        worker.cancel()


def test_background_csv_export(tmp_path):
    worker = BackgroundFileIO(capacity=1)
    try:
        path = tmp_path / "export.csv"
        start = datetime(2026, 9, 15)
        worker.submit("csv", path, {"columns": [("gas", [10, 20], [start, start + timedelta(seconds=1)])],
                                     "sample_rate": 500})
        with pytest.raises(RuntimeError, match="queue is full"):
            worker.submit("csv", path, {})
        assert await_file_job(worker)[1] == "done"
        assert len(read_csv(path)) == 502
    finally:
        worker.cancel()
