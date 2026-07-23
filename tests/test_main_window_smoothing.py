from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import numpy as np

import tucam_control.ui.main_window as main_window_module
from tucam_control.concentration_smoother import AdaptiveConcentrationSmoother
from tucam_control.gas_analyzer import GasResult
from tucam_control.ui.main_window import MainWindow, _ProcessingTask


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


def test_stopping_batch_clears_pending_frame_and_smoothing_state() -> None:
    states: list[bool] = []
    gaps: list[bool] = []
    smoother = AdaptiveConcentrationSmoother()
    result = GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 1.0, 1.0, True)
    smoother.smooth_groups([[result]], ["行 1-10"], mode="time")
    window = SimpleNamespace(
        _batch_timer=SimpleNamespace(stop=lambda: None),
        _processing_generation=4,
        _pending_frame=np.ones((2, 2), dtype=np.uint16),
        _concentration_smoother=smoother,
        _conc_tab=SimpleNamespace(mark_history_gap=lambda: gaps.append(True)),
        _acq_tab=SimpleNamespace(set_batch_state=states.append),
        _batch_idx=2,
        _batch_images=["a", "b"],
        status_changed=SimpleNamespace(emit=lambda _message: None),
    )

    MainWindow._on_batch_stop(window)

    assert window._processing_generation == 5
    assert window._pending_frame is None
    assert smoother._state == {}
    assert states == [False]
    assert gaps == [True]


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
