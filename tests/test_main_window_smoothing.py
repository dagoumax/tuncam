from __future__ import annotations

from types import SimpleNamespace

from tucam_control.concentration_smoother import AdaptiveConcentrationSmoother
from tucam_control.ui.main_window import MainWindow


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
