# -*- coding: utf-8 -*-

import numpy as np

from tucam_control.gas_analyzer import GasConfig
from tucam_control.raman_signal_diagnostic import (
    RamanSignalHealthMonitor,
    assess_raman_signal,
)


GASES = [
    GasConfig("O2", 60, window=8, detection_sigma=0.1),
    GasConfig("N2", 140, window=8, detection_sigma=20.0),
]


def _noise_spectra(groups: int = 2) -> np.ndarray:
    rng = np.random.default_rng(20260723)
    return rng.normal(0.0, 1.0, size=(groups, 200))


def _healthy_spectra(groups: int = 2) -> np.ndarray:
    spectra = _noise_spectra(groups)
    spectra[:, 59:62] += np.asarray([8.0, 16.0, 8.0])
    spectra[:, 139:142] += np.asarray([8.0, 16.0, 8.0])
    return spectra


def test_noise_only_spectra_are_identified_per_group() -> None:
    assessment = assess_raman_signal(
        _noise_spectra(),
        ["行 1-10", "行 11-20"],
        GASES,
    )

    assert assessment.all_groups_noise_only is True
    assert assessment.noise_only_groups == ("行 1-10", "行 11-20")


def test_known_raman_peak_marks_groups_as_healthy() -> None:
    assessment = assess_raman_signal(
        _healthy_spectra(),
        ["行 1-10", "行 11-20"],
        GASES,
    )

    assert assessment.all_groups_noise_only is False
    assert assessment.noise_only_groups == ()
    assert assessment.strongest_peak_snr > 4.0


def test_single_narrow_noise_spike_is_not_raman_signal() -> None:
    spectra = _noise_spectra(1)
    spectra[0, 140] += 30.0

    assessment = assess_raman_signal(spectra, ["noise"], GASES)

    assert assessment.noise_only_groups == ("noise",)


def test_two_moderate_broad_peaks_are_raman_signal() -> None:
    spectra = _noise_spectra(1)
    spectra[0, 59:62] += np.asarray([5.0, 10.0, 5.0])
    spectra[0, 139:142] += np.asarray([5.0, 10.0, 5.0])

    assessment = assess_raman_signal(spectra, ["signal"], GASES)

    assert assessment.noise_only_groups == ()
    assert assessment.groups[0].moderate_peak_count >= 2


def test_single_strong_broad_peak_is_raman_signal() -> None:
    spectra = _noise_spectra(1)
    spectra[0, 137:144] += np.asarray([3.0, 8.0, 16.0, 22.0, 16.0, 8.0, 3.0])

    assessment = assess_raman_signal(spectra, ["signal"], GASES)

    assert assessment.noise_only_groups == ()
    assert assessment.groups[0].strong_peak_count == 1


def test_gas_detection_sigma_does_not_change_signal_health() -> None:
    spectra = _healthy_spectra(1)
    first = assess_raman_signal(spectra, ["signal"], GASES)
    changed = assess_raman_signal(
        spectra,
        ["signal"],
        [
            GasConfig("O2", 60, window=8, detection_sigma=100.0),
            GasConfig("N2", 140, window=8, detection_sigma=0.01),
        ],
    )

    assert first.noise_only_groups == changed.noise_only_groups == ()


def test_all_groups_need_three_consecutive_noise_frames_for_failure() -> None:
    assessment = assess_raman_signal(_noise_spectra(), ["A", "B"], GASES)
    monitor = RamanSignalHealthMonitor(failure_frames=3, recovery_frames=2)

    assert monitor.update(assessment).state == "suspect"
    assert monitor.update(assessment).state == "suspect"
    failed = monitor.update(assessment)

    assert failed.state == "failed"
    assert "检查激光器" in failed.message


def test_single_bad_group_reports_row_group_instead_of_laser_failure() -> None:
    spectra = _healthy_spectra()
    spectra[1] = _noise_spectra(1)[0]
    assessment = assess_raman_signal(spectra, ["good", "bad"], GASES)
    monitor = RamanSignalHealthMonitor(failure_frames=3)

    monitor.update(assessment)
    monitor.update(assessment)
    status = monitor.update(assessment)

    assert status.state == "degraded"
    assert status.noise_only_groups == ("bad",)
    assert "bad" in status.message


def test_failure_requires_two_healthy_frames_to_clear() -> None:
    noise = assess_raman_signal(_noise_spectra(), ["A", "B"], GASES)
    healthy = assess_raman_signal(_healthy_spectra(), ["A", "B"], GASES)
    monitor = RamanSignalHealthMonitor(failure_frames=3, recovery_frames=2)
    for _ in range(3):
        monitor.update(noise)

    assert monitor.update(healthy).state == "recovering"
    assert monitor.update(healthy).state == "healthy"


def test_failure_clears_when_one_row_group_recovers() -> None:
    noise = assess_raman_signal(_noise_spectra(), ["A", "B"], GASES)
    partially_recovered_spectra = _noise_spectra()
    partially_recovered_spectra[0] = _healthy_spectra(1)[0]
    partially_recovered = assess_raman_signal(
        partially_recovered_spectra,
        ["A", "B"],
        GASES,
    )
    monitor = RamanSignalHealthMonitor(failure_frames=3, recovery_frames=2)
    for _ in range(3):
        monitor.update(noise)

    recovering = monitor.update(partially_recovered)
    recovered = monitor.update(partially_recovered)

    assert recovering.state == "recovering"
    assert recovering.consecutive_recovery_frames == 1
    assert recovered.state == "degraded"
    assert recovered.noise_only_groups == ("B",)
    assert "全局拉曼信号已恢复" in recovered.message
    assert "B" in recovered.message


def test_gap_breaks_consecutive_failure_count() -> None:
    noise = assess_raman_signal(_noise_spectra(), ["A", "B"], GASES)
    monitor = RamanSignalHealthMonitor(failure_frames=3)
    monitor.update(noise)
    monitor.update(noise)
    monitor.mark_gap()

    assert monitor.update(noise).state == "suspect"


def test_renaming_group_keeps_failure_counter_by_stable_id() -> None:
    spectra = _healthy_spectra()
    spectra[1] = _noise_spectra(1)[0]
    monitor = RamanSignalHealthMonitor(failure_frames=3)

    first = assess_raman_signal(
        spectra,
        ["旧名称A", "旧名称B"],
        GASES,
        group_ids=["rows:1:10", "rows:11:20"],
    )
    renamed = assess_raman_signal(
        spectra,
        ["参考通道", "哈龙通道"],
        GASES,
        group_ids=["rows:1:10", "rows:11:20"],
    )
    monitor.update(first)
    monitor.update(first)
    status = monitor.update(renamed)

    assert status.state == "degraded"
    assert status.noise_only_group_ids == ("rows:11:20",)
    assert status.noise_only_groups == ("哈龙通道",)
    assert "哈龙通道" in status.message
    assert "旧名称B" not in status.message
