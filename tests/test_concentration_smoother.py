# -*- coding: utf-8 -*-

from tucam_control.concentration_smoother import AdaptiveConcentrationSmoother, PROFILES
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


def test_extra_smooth_profile_uses_seven_point_median_and_low_alpha() -> None:
    profile = PROFILES["extra_smooth"]

    assert profile.median_window == 7
    assert profile.stable_alpha == 0.10
    assert profile.fast_alpha == 0.35


def test_extra_smooth_profile_rejects_single_sample_spike() -> None:
    smoother = AdaptiveConcentrationSmoother()
    smoother.set_profile("extra_smooth")
    label = ["行 1-10"]

    for _ in range(7):
        smoother.smooth_groups(
            [[_result("O2", 0.2), _result("N2", 0.8)]], label, mode="time"
        )
    output = smoother.smooth_groups(
        [[_result("O2", 0.8), _result("N2", 0.2)]], label, mode="time"
    )

    assert output[0][0].concentration == 0.2
    assert output[0][1].concentration == 0.8


def test_extra_smooth_uses_seven_real_frames_at_three_second_exposure() -> None:
    profile = PROFILES["extra_smooth"]

    assert profile.median_window == 7
    assert profile.median_window * 3 == 21
