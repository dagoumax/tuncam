from __future__ import annotations

import numpy as np

from tucam_control.gas_analyzer import (
    GasAnalyzer,
    GasConfig,
    GasResult,
    apply_halon_concentration_correction,
    correct_halon_percentage,
)


def test_detection_threshold_sigma_controls_weak_peak_detection() -> None:
    spectrum = np.tile(np.asarray([-1.0, 1.0]), 50)
    spectrum[50] = 10.0
    analyzer = GasAnalyzer()
    analyzer.gases = [GasConfig("test", 50, window=5)]

    assert analyzer.threshold_sigma == 3.0
    assert analyzer.analyze(spectrum)[0].detected is True

    analyzer.threshold_sigma = 20.0

    assert analyzer.analyze(spectrum)[0].detected is False


def test_known_strong_peaks_are_excluded_from_mad_noise() -> None:
    spectrum = np.tile(np.asarray([-1.0, 1.0]), 100)
    spectrum[50] = 5.0
    spectrum[150] = 1000.0
    analyzer = GasAnalyzer()
    analyzer.baseline_corrected = True
    analyzer.gases = [
        GasConfig("weak", 50, window=5),
        GasConfig("strong", 150, window=5),
    ]

    result = analyzer.analyze(spectrum)

    assert 0.8 < analyzer.last_noise_sigma < 1.2
    assert result[0].detected is True


def test_per_gas_detection_sigma_overrides_global_value() -> None:
    spectrum = np.tile(np.asarray([-1.0, 1.0]), 50)
    spectrum[50] = 4.0
    analyzer = GasAnalyzer()
    analyzer.baseline_corrected = True
    analyzer.threshold_sigma = 5.0
    analyzer.gases = [GasConfig("test", 50, window=5, detection_sigma=2.0)]

    assert analyzer.analyze(spectrum)[0].detected is True

    analyzer.gases = [GasConfig("test", 50, window=5)]

    assert analyzer.analyze(spectrum)[0].detected is False


def test_detection_threshold_sigma_is_kept_positive() -> None:
    analyzer = GasAnalyzer()

    analyzer.threshold_sigma = 0

    assert analyzer.threshold_sigma == 0.01


def test_corrected_spectrum_does_not_subtract_negative_window_minimum() -> None:
    analyzer = GasAnalyzer()
    analyzer.gases = [GasConfig("test", 50, window=5)]
    analyzer.threshold_sigma = 0.1
    analyzer.baseline_corrected = True
    first = np.zeros(100, dtype=np.float64)
    second = np.zeros(100, dtype=np.float64)
    first[50], second[50] = 10.0, 10.0
    first[47], second[47] = -1.0, -5.0

    first_result = analyzer.analyze(first)[0]
    second_result = analyzer.analyze(second)[0]

    assert first_result.peak_height == second_result.peak_height == 10.0
    assert first_result.component == second_result.component == 10.0


def test_raw_spectrum_still_uses_local_baseline() -> None:
    spectrum = np.full(100, 4.0, dtype=np.float64)
    spectrum[50] = 10.0
    analyzer = GasAnalyzer()
    analyzer.gases = [GasConfig("test", 50, window=5)]
    analyzer.threshold_sigma = 0.1

    result = analyzer.analyze(spectrum)[0]

    assert result.component == 6.0


def test_halon_empirical_correction_hits_all_calibration_points() -> None:
    calibration_points = ((3.0, 2.0), (5.4, 5.0), (6.5, 6.0), (10.0, 10.0), (20.0, 20.0))

    for measured, actual in calibration_points:
        assert correct_halon_percentage(measured) == actual


def test_halon_correction_is_monotonic_between_points() -> None:
    corrected = [correct_halon_percentage(value) for value in np.linspace(0, 20, 201)]

    assert all(right >= left for left, right in zip(corrected, corrected[1:]))
    assert correct_halon_percentage(25.0) == 25.0


def test_halon_correction_preserves_total_concentration() -> None:
    results = [
        GasResult("halong", 0, 0, 1.0, 1.0, 1.0, 1.0, concentration=0.054),
        GasResult("N2", 0, 0, 1.0, 1.0, 1.0, 1.0, concentration=0.746),
        GasResult("O2", 0, 0, 1.0, 1.0, 1.0, 1.0, concentration=0.200),
    ]

    apply_halon_concentration_correction(results)

    assert np.isclose(results[0].concentration, 0.05)
    assert np.isclose(sum(result.concentration for result in results), 1.0)
    assert np.isclose(results[1].concentration / results[2].concentration, 0.746 / 0.2)
