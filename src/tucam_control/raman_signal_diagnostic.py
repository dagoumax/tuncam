# -*- coding: utf-8 -*-
"""Raman signal-health assessment for laser and optical-path diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import warnings

import numpy as np
from scipy.signal import peak_widths

from .gas_analyzer import GasConfig, estimate_noise_sigma


MODERATE_PEAK_SNR = 6.0
MODERATE_PEAK_WIDTH = 1.5
STRONG_PEAK_SNR = 12.0
STRONG_PEAK_WIDTH = 2.5


@dataclass(frozen=True)
class GroupSignalMetrics:
    group_label: str
    noise_sigma: float
    strongest_peak_snr: float
    moderate_peak_count: int
    strong_peak_count: int
    group_id: str = ""

    @property
    def noise_only(self) -> bool:
        return self.moderate_peak_count < 2 and self.strong_peak_count == 0


@dataclass(frozen=True)
class RamanSignalAssessment:
    groups: tuple[GroupSignalMetrics, ...]

    @property
    def strongest_peak_snr(self) -> float:
        return max((group.strongest_peak_snr for group in self.groups), default=0.0)

    @property
    def noise_only_groups(self) -> tuple[str, ...]:
        return tuple(group.group_label for group in self.groups if group.noise_only)

    @property
    def noise_only_group_ids(self) -> tuple[str, ...]:
        return tuple(
            (group.group_id or group.group_label)
            for group in self.groups
            if group.noise_only
        )

    @property
    def all_groups_noise_only(self) -> bool:
        return bool(self.groups) and all(group.noise_only for group in self.groups)


@dataclass(frozen=True)
class RamanSignalStatus:
    state: str
    message: str
    strongest_peak_snr: float
    noise_only_groups: tuple[str, ...]
    consecutive_all_noise_frames: int
    consecutive_recovery_frames: int = 0
    noise_only_group_ids: tuple[str, ...] = ()
    invalid_group_ids: tuple[str, ...] = ()


def _candidate_peak_width(region: np.ndarray) -> float:
    """Return the strongest candidate's full width at half prominence."""
    if region.size < 3:
        return 0.0
    peak_index = int(np.argmax(region))
    if peak_index == 0 or peak_index == region.size - 1:
        return 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        width = peak_widths(region, [peak_index], rel_height=0.5)[0][0]
    return max(0.0, float(width))


def assess_raman_signal(
    spectra: np.ndarray,
    group_labels: list[str],
    gas_configs: list[GasConfig],
    merge_factor: int = 1,
    moderate_peak_snr: float = MODERATE_PEAK_SNR,
    moderate_peak_width: float = MODERATE_PEAK_WIDTH,
    strong_peak_snr: float = STRONG_PEAK_SNR,
    strong_peak_width: float = STRONG_PEAK_WIDTH,
    group_ids: list[str] | None = None,
) -> RamanSignalAssessment:
    """Assess configured Raman peak structure in each processed spectrum."""
    if spectra.ndim != 2 or not gas_configs:
        return RamanSignalAssessment(())

    factor = max(1, int(merge_factor))
    metrics = []
    for index, spectrum in enumerate(spectra):
        noise_sigma = estimate_noise_sigma(spectrum, gas_configs, factor)
        denominator = max(float(noise_sigma), 1e-12)
        strongest_snr = 0.0
        moderate_peaks = 0
        strong_peaks = 0

        for config in gas_configs:
            center = config.position // factor
            window = max(1, config.window // factor)
            lo = max(0, center - window)
            hi = min(spectrum.size, center + window + 1)
            if lo >= hi:
                continue
            region = np.asarray(spectrum[lo:hi], dtype=float)
            prominence = max(0.0, float(np.max(region) - np.median(region)))
            peak_snr = prominence / denominator
            peak_width = _candidate_peak_width(region)
            strongest_snr = max(strongest_snr, peak_snr)
            if peak_snr >= moderate_peak_snr and peak_width >= moderate_peak_width:
                moderate_peaks += 1
            if peak_snr >= strong_peak_snr and peak_width >= strong_peak_width:
                strong_peaks += 1

        label = group_labels[index] if index < len(group_labels) else f"Group {index + 1}"
        group_id = (
            group_ids[index]
            if group_ids is not None and index < len(group_ids)
            else label
        )
        metrics.append(
            GroupSignalMetrics(
                group_label=label,
                noise_sigma=float(noise_sigma),
                strongest_peak_snr=strongest_snr,
                moderate_peak_count=moderate_peaks,
                strong_peak_count=strong_peaks,
                group_id=group_id,
            )
        )
    return RamanSignalAssessment(tuple(metrics))


class RamanSignalHealthMonitor:
    """Debounce noise-only frames and report laser/row-group signal failures."""

    def __init__(self, failure_frames: int = 3, recovery_frames: int = 2) -> None:
        self._failure_frames = max(1, int(failure_frames))
        self._recovery_frames = max(1, int(recovery_frames))
        self._all_noise_frames = 0
        self._recovery_frames_seen = 0
        self._group_noise_frames: dict[str, int] = {}
        self._group_recovery_frames: dict[str, int] = {}
        self._failed_group_ids: set[str] = set()
        self._failed = False

    def reset(self) -> None:
        self._all_noise_frames = 0
        self._recovery_frames_seen = 0
        self._group_noise_frames.clear()
        self._group_recovery_frames.clear()
        self._failed_group_ids.clear()
        self._failed = False

    def mark_gap(self) -> None:
        """Do not treat frames separated by a stop or error as consecutive."""
        self._all_noise_frames = 0
        self._recovery_frames_seen = 0
        self._group_noise_frames.clear()
        self._group_recovery_frames.clear()

    def update(self, assessment: RamanSignalAssessment) -> RamanSignalStatus:
        if not assessment.groups:
            return RamanSignalStatus("unavailable", "未配置可诊断的拉曼峰", 0.0, (), 0)

        noise_group_ids = set(assessment.noise_only_group_ids)
        active_ids = {
            group.group_id or group.group_label for group in assessment.groups
        }
        label_by_id = {
            group.group_id or group.group_label: group.group_label
            for group in assessment.groups
        }
        self._failed_group_ids.intersection_update(active_ids)
        for group_id in active_ids:
            if group_id in noise_group_ids:
                noise_frames = self._group_noise_frames.get(group_id, 0) + 1
                self._group_noise_frames[group_id] = noise_frames
                self._group_recovery_frames[group_id] = 0
                if noise_frames >= self._failure_frames:
                    self._failed_group_ids.add(group_id)
            else:
                self._group_noise_frames[group_id] = 0
                if group_id in self._failed_group_ids:
                    recovery_frames = (
                        self._group_recovery_frames.get(group_id, 0) + 1
                    )
                    self._group_recovery_frames[group_id] = recovery_frames
                    if recovery_frames >= self._recovery_frames:
                        self._failed_group_ids.discard(group_id)
                        self._group_recovery_frames[group_id] = 0
                else:
                    self._group_recovery_frames[group_id] = 0

        if assessment.all_groups_noise_only:
            self._all_noise_frames += 1
            self._recovery_frames_seen = 0
        else:
            self._all_noise_frames = 0
            # Global failure means every probe lost signal. Recovery is
            # therefore confirmed once any probe has valid signal again.
            self._recovery_frames_seen = (
                self._recovery_frames_seen + 1 if self._failed else 0
            )

        confirmed_group_ids = tuple(
            group.group_id or group.group_label
            for group in assessment.groups
            if (group.group_id or group.group_label) in self._failed_group_ids
        )
        confirmed_groups = tuple(
            label_by_id[group_id] for group_id in confirmed_group_ids
        )

        if self._all_noise_frames >= self._failure_frames:
            self._failed = True
            self._recovery_frames_seen = 0
            state = "failed"
            message = (
                f"所有探头连续 {self._all_noise_frames} 帧未检测到有效拉曼信号，"
                "请检查激光器、光路或探头位置"
            )
        elif self._failed:
            if self._recovery_frames_seen >= self._recovery_frames:
                self._failed = False
                self._recovery_frames_seen = 0
                if confirmed_groups:
                    state = "degraded"
                    message = (
                        "全局拉曼信号已恢复；以下探头仍未检测到有效拉曼信号: "
                        + ", ".join(confirmed_groups)
                    )
                else:
                    state = "healthy"
                    message = "拉曼信号已恢复"
            else:
                state = "recovering"
                message = (
                    f"正在确认拉曼信号恢复 "
                    f"({self._recovery_frames_seen}/{self._recovery_frames})"
                )
        elif confirmed_groups:
            state = "degraded"
            message = "以下探头连续未检测到有效拉曼信号: " + ", ".join(confirmed_groups)
        elif noise_group_ids:
            state = "suspect"
            message = "拉曼信号暂时偏弱，正在确认"
        else:
            state = "healthy"
            message = "拉曼信号正常"

        invalid_group_ids = (
            tuple(
                group.group_id or group.group_label
                for group in assessment.groups
            )
            if self._failed
            else confirmed_group_ids
        )

        return RamanSignalStatus(
            state=state,
            message=message,
            strongest_peak_snr=assessment.strongest_peak_snr,
            noise_only_groups=tuple(
                group.group_label
                for group in assessment.groups
                if group.noise_only
            ),
            consecutive_all_noise_frames=self._all_noise_frames,
            consecutive_recovery_frames=self._recovery_frames_seen,
            noise_only_group_ids=tuple(
                group.group_id or group.group_label
                for group in assessment.groups
                if group.noise_only
            ),
            invalid_group_ids=invalid_group_ids,
        )
