from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import numpy as np
from PIL import Image

import tucam_control.ui.main_window as main_window_module
from tucam_control.concentration_smoother import AdaptiveConcentrationSmoother
from tucam_control.gas_analyzer import GasResult
from tucam_control.ui.main_window import MainWindow, _ProcessingTask


def _result(name: str, concentration: float) -> GasResult:
    return GasResult(name, 0, 0, 1.0, 1.0, 1.0, concentration, concentration, True)

class _ConcentrationTabRecorder:
    def __init__(self) -> None:
        self.export_smoothed: bool | None = None

    def set_export_smoothed(self, enabled: bool) -> None:
        self.export_smoothed = enabled


def _window(profile: str) -> SimpleNamespace:
    return SimpleNamespace(
        _settings={"concentration_smoothing": profile},
        _concentration_smoother=AdaptiveConcentrationSmoother(),
        _conc_tab=_ConcentrationTabRecorder(),
    )


def test_persisted_extra_smooth_profile_is_applied_at_startup() -> None:
    window = _window("extra_smooth")

    applied = MainWindow._configure_concentration_smoothing(window)

    assert applied == "extra_smooth"
    assert window._concentration_smoother.profile_name == "extra_smooth"
    assert window._settings["concentration_smoothing"] == "extra_smooth"
    assert window._conc_tab.export_smoothed is True


def test_persisted_off_profile_disables_smoothed_export() -> None:
    window = _window("off")

    applied = MainWindow._configure_concentration_smoothing(window)

    assert applied == "off"
    assert window._conc_tab.export_smoothed is False


def test_invalid_persisted_profile_falls_back_consistently() -> None:
    window = _window("invalid-profile")

    applied = MainWindow._configure_concentration_smoothing(window)

    assert applied == "balanced"
    assert window._settings["concentration_smoothing"] == "balanced"
    assert window._conc_tab.export_smoothed is True


def test_batch_processing_uses_local_time_chart_mode() -> None:
    payloads: list[dict] = []
    task = _ProcessingTask(
        frame=np.ones((2, 16), dtype=np.uint16),
        settings={"arpls_enabled": False},
        gas_configs=[],
        generation=1,
        batch_mode=True,
    )
    task.signals.finished.connect(payloads.append)

    task.run()

    assert len(payloads) == 1
    assert payloads[0]["mode"] == "time"
    assert "raman_signal" in payloads[0]


def test_stopping_batch_clears_pending_frame_and_smoothing_state() -> None:
    states: list[bool] = []
    gaps: list[bool] = []
    signal_gaps: list[bool] = []
    smoother = AdaptiveConcentrationSmoother()
    result = GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 1.0, 1.0, True)
    smoother.smooth_groups([[result]], ["行 1-10"], mode="time")
    window = SimpleNamespace(
        _batch_timer=SimpleNamespace(stop=lambda: None),
        _processing_generation=4,
        _pending_frame=np.ones((2, 2), dtype=np.uint16),
        _concentration_smoother=smoother,
        _raman_signal_monitor=SimpleNamespace(mark_gap=lambda: signal_gaps.append(True)),
        _conc_tab=SimpleNamespace(mark_history_gap=lambda: gaps.append(True)),
        _acq_tab=SimpleNamespace(set_batch_state=states.append),
        _batch_idx=2,
        _batch_images=["a", "b"],
        _batch_generation=1,
        _batch_load_busy=False,
        _batch_load_task=None,
        status_changed=SimpleNamespace(emit=lambda _message: None),
    )

    MainWindow._on_batch_stop(window)

    assert window._processing_generation == 5
    assert window._pending_frame is None
    assert smoother._state == {}
    assert states == [False]
    assert gaps == [True]
    assert signal_gaps == [True]


def test_batch_tick_reads_one_image_on_demand(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "frame.tif"
    expected = np.arange(16, dtype=np.uint16).reshape(4, 4)
    Image.fromarray(expected).save(image_path)
    displayed: list[np.ndarray] = []
    messages: list[str] = []
    window = SimpleNamespace(
        _processing_busy=False,
        _batch_load_busy=False,
        _batch_load_task=None,
        _batch_generation=1,
        _batch_timer=SimpleNamespace(isActive=lambda: True),
        _batch_idx=0,
        _batch_images=[str(image_path)],
        _acq_tab=SimpleNamespace(display_frame=displayed.append),
        status_changed=SimpleNamespace(emit=messages.append),
    )
    window._on_batch_frame_loaded = (
        lambda *args: MainWindow._on_batch_frame_loaded(window, *args)
    )
    window._on_batch_frame_load_failed = (
        lambda *args: MainWindow._on_batch_frame_load_failed(window, *args)
    )
    monkeypatch.setattr(
        main_window_module.QThreadPool,
        "globalInstance",
        lambda: SimpleNamespace(start=lambda task: task.run()),
    )

    MainWindow._on_batch_tick(window)

    assert window._batch_idx == 1
    assert window._batch_images == [str(image_path)]
    assert len(displayed) == 1
    np.testing.assert_array_equal(displayed[0], expected)
    assert image_path.name in messages[-1]


def test_batch_tick_skips_unreadable_image_without_stopping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bad_path = tmp_path / "bad.tif"
    bad_path.write_text("not a tif", encoding="utf-8")
    good_path = tmp_path / "good.tif"
    expected = np.full((3, 3), 42, dtype=np.uint16)
    Image.fromarray(expected).save(good_path)
    displayed: list[np.ndarray] = []
    messages: list[str] = []
    window = SimpleNamespace(
        _processing_busy=False,
        _batch_load_busy=False,
        _batch_load_task=None,
        _batch_generation=1,
        _batch_timer=SimpleNamespace(isActive=lambda: True),
        _batch_idx=0,
        _batch_images=[str(bad_path), str(good_path)],
        _acq_tab=SimpleNamespace(display_frame=displayed.append),
        status_changed=SimpleNamespace(emit=messages.append),
    )
    window._on_batch_tick = lambda: MainWindow._on_batch_tick(window)
    window._on_batch_frame_loaded = (
        lambda *args: MainWindow._on_batch_frame_loaded(window, *args)
    )
    window._on_batch_frame_load_failed = (
        lambda *args: MainWindow._on_batch_frame_load_failed(window, *args)
    )
    monkeypatch.setattr(
        main_window_module.QThreadPool,
        "globalInstance",
        lambda: SimpleNamespace(start=lambda task: task.run()),
    )
    monkeypatch.setattr(
        main_window_module.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )

    MainWindow._on_batch_tick(window)

    assert window._batch_idx == 2
    assert len(displayed) == 1
    np.testing.assert_array_equal(displayed[0], expected)
    assert any(bad_path.name in message for message in messages)


def test_statistics_window_change_is_persisted_immediately(monkeypatch) -> None:
    saved: list[dict] = []
    monkeypatch.setattr(
        main_window_module,
        "save_user_settings",
        lambda settings, _gases: saved.append(dict(settings)) or Path("settings.json"),
    )
    window = SimpleNamespace(
        _settings={"statistics_window_seconds": 60},
        _analyzer=SimpleNamespace(gases=[]),
        _clear_diagnostic_error=lambda _key: None,
        _set_diagnostic_error=lambda _key, _message: None,
    )

    MainWindow._on_statistics_window_changed(window, 120)

    assert window._settings["statistics_window_seconds"] == 120
    assert saved == [{"statistics_window_seconds": 120}]

def test_invalid_raman_probe_is_zeroed_for_display_and_export() -> None:
    smoother = AdaptiveConcentrationSmoother()
    window = SimpleNamespace(_concentration_smoother=smoother)
    results = [
        [_result("O2", 0.2), _result("N2", 0.8)],
        [_result("O2", 0.4), _result("N2", 0.6)],
    ]
    status = SimpleNamespace(invalid_group_ids=("probe-b",))

    display, exported = MainWindow._prepare_concentration_results(
        window,
        results,
        ["probe-a", "probe-b"],
        "time",
        status,
    )

    assert [item.concentration for item in display[0]] == [0.2, 0.8]
    assert [item.concentration for item in display[1]] == [0.0, 0.0]
    assert [item.concentration for item in exported[1]] == [0.0, 0.0]
    assert all(item.detected is False for item in exported[1])
    assert all(key[0] != "probe-b" for key in smoother._state)
