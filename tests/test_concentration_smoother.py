# -*- coding: utf-8 -*-

from tucam_control.concentration_smoother import AdaptiveConcentrationSmoother
from tucam_control.gas_analyzer import GasResult


def _result(name: str, concentration: float) -> GasResult:
    return GasResult(
        name=name,
        position=0,
        found_col=0,
        peak_height=1.0,
        peak_area=1.0,
        coefficient=1.0,
        component=concentration,
        concentration=concentration,
        detected=True,
    )


def test_batch_mode_is_not_smoothed() -> None:
    smoother = AdaptiveConcentrationSmoother()
    first = [[_result("O2", 0.2), _result("N2", 0.8)]]
    second = [[_result("O2", 0.9), _result("N2", 0.1)]]

    smoother.smooth_groups(first, ["行 1-10"], mode="index")
    out = smoother.smooth_groups(second, ["行 1-10"], mode="index")

    assert out[0][0].concentration == 0.9
    assert out[0][1].concentration == 0.1


def test_responsive_profile_follows_large_change() -> None:
    smoother = AdaptiveConcentrationSmoother()
    smoother.set_profile("responsive")
    first = [[_result("O2", 0.2), _result("N2", 0.8)]]
    second = [[_result("O2", 0.9), _result("N2", 0.1)]]

    smoother.smooth_groups(first, ["行 1-10"], mode="time")
    out = smoother.smooth_groups(second, ["行 1-10"], mode="time")

    assert out[0][0].concentration > 0.7
    assert out[0][1].concentration < 0.3
    assert round(sum(r.concentration for r in out[0]), 8) == 1.0
