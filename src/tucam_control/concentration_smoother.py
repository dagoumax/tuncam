# -*- coding: utf-8 -*-
"""Adaptive smoothing for concentration display."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class SmoothingProfile:
    """Parameters for concentration smoothing."""

    enabled: bool
    stable_alpha: float
    fast_alpha: float
    relative_threshold: float
    absolute_threshold: float
    median_window: int = 3


PROFILES: dict[str, SmoothingProfile] = {
    "off": SmoothingProfile(False, 1.0, 1.0, 0.0, 0.0, 1),
    "extra_smooth": SmoothingProfile(True, 0.10, 0.35, 0.12, 0.006, 7),
    "steady": SmoothingProfile(True, 0.18, 0.65, 0.10, 0.005, 3),
    "balanced": SmoothingProfile(True, 0.25, 0.75, 0.08, 0.003, 3),
    "responsive": SmoothingProfile(True, 0.40, 0.90, 0.05, 0.002, 3),
}


class AdaptiveConcentrationSmoother:
    """Smooth concentration fractions while still following real changes."""

    def __init__(self) -> None:
        self._state: dict[tuple[str, str], float] = {}
        self._recent: dict[tuple[str, str], list[float]] = {}
        self._profile_name = "balanced"

    def reset(self) -> None:
        self._state.clear()
        self._recent.clear()

    def set_profile(self, profile_name: str) -> None:
        if profile_name not in PROFILES:
            profile_name = "balanced"
        if profile_name != self._profile_name:
            self._profile_name = profile_name
            self.reset()

    @property
    def profile_name(self) -> str:
        return self._profile_name

    def smooth_groups(self, all_group_results: list, group_labels: list[str], mode: str) -> list:
        """Return a smoothed deep copy of grouped GasResult values."""
        profile = PROFILES.get(self._profile_name, PROFILES["balanced"])
        if not profile.enabled or mode != "time":
            return copy.deepcopy(all_group_results)

        smoothed_groups = []
        for group_label, gas_results in zip(group_labels, all_group_results):
            group = []
            smoothed_sum = 0.0
            for result in gas_results:
                smoothed = self._smooth_one(
                    key=(group_label, result.name),
                    raw=float(result.concentration),
                    profile=profile,
                )
                smoothed_sum += max(0.0, smoothed)
                group.append(replace(result, concentration=max(0.0, smoothed)))

            if smoothed_sum > 0:
                group = [
                    replace(result, concentration=result.concentration / smoothed_sum)
                    for result in group
                ]
            smoothed_groups.append(group)
        return smoothed_groups

    def _smooth_one(
        self,
        key: tuple[str, str],
        raw: float,
        profile: SmoothingProfile,
    ) -> float:
        recent = self._recent.setdefault(key, [])
        recent.append(raw)
        if len(recent) > profile.median_window:
            del recent[0 : len(recent) - profile.median_window]
        filtered = float(np.median(recent)) if len(recent) >= profile.median_window else raw

        if key not in self._state:
            self._state[key] = filtered
            return filtered

        previous = self._state[key]
        threshold = max(profile.absolute_threshold, abs(previous) * profile.relative_threshold)
        alpha = profile.fast_alpha if abs(filtered - previous) > threshold else profile.stable_alpha
        value = previous + alpha * (filtered - previous)
        self._state[key] = value
        return value
