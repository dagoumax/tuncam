# -*- coding: utf-8 -*-
"""Rolling concentration statistics and threshold-duration tracking."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ThresholdStatistics:
    group_label: str
    gas_name: str
    current_percent: float
    threshold_percent: float | None
    is_above: bool
    continuous_seconds: float
    cumulative_seconds: float
    sample_count: int
    mean_percent: float
    standard_deviation_percent: float
    range_low_percent: float
    range_high_percent: float
    latest_time: datetime


@dataclass
class _SeriesState:
    samples: deque[tuple[datetime, float]] = field(default_factory=deque)
    previous_time: datetime | None = None
    previous_value: float | None = None
    current_value: float = 0.0
    latest_time: datetime | None = None
    continuous_seconds: float = 0.0
    cumulative_seconds: float = 0.0


class ThresholdStatisticsTracker:
    """Track smoothed concentration statistics for each row-group/gas pair."""

    def __init__(self, window_seconds: int = 60) -> None:
        self._window_seconds = self._normalize_window(window_seconds)
        self._thresholds: dict[str, float] = {}
        self._states: dict[tuple[str, str], _SeriesState] = {}

    @staticmethod
    def _normalize_window(value: int) -> int:
        return max(1, min(86400, int(value)))

    @property
    def window_seconds(self) -> int:
        return self._window_seconds

    def set_window_seconds(self, value: int) -> None:
        self._window_seconds = self._normalize_window(value)
        for state in self._states.values():
            if state.latest_time is not None:
                self._trim_samples(state, state.latest_time)

    def set_thresholds(self, thresholds: dict[str, float | None]) -> None:
        normalized = {
            str(name): float(value)
            for name, value in thresholds.items()
            if value is not None
        }
        if normalized == self._thresholds:
            return
        changed_names = {
            name
            for name in set(self._thresholds) | set(normalized)
            if self._thresholds.get(name) != normalized.get(name)
        }
        self._thresholds = normalized
        for (group_label, gas_name), state in self._states.items():
            if gas_name in changed_names:
                state.previous_time = None
                state.previous_value = None
                state.continuous_seconds = 0.0
                state.cumulative_seconds = 0.0

    def reset(self) -> None:
        self._states.clear()

    def mark_gap(self) -> None:
        """Break continuity without discarding rolling samples or totals."""
        for state in self._states.values():
            state.previous_time = None
            state.previous_value = None
            state.continuous_seconds = 0.0

    def update(
        self,
        all_group_results: list,
        group_labels: list[str],
        timestamp: datetime,
    ) -> None:
        for group_label, gas_results in zip(group_labels, all_group_results):
            for result in gas_results:
                key = (group_label, result.name)
                state = self._states.setdefault(key, _SeriesState())
                value = float(result.concentration) * 100.0
                self._update_duration(
                    state,
                    self._thresholds.get(result.name),
                    value,
                    timestamp,
                )
                state.current_value = value
                state.latest_time = timestamp
                state.samples.append((timestamp, value))
                self._trim_samples(state, timestamp)
                state.previous_time = timestamp
                state.previous_value = value

    def snapshots(self) -> list[ThresholdStatistics]:
        snapshots = []
        for (group_label, gas_name), state in sorted(self._states.items()):
            if state.latest_time is None or not state.samples:
                continue
            cutoff = state.latest_time - timedelta(seconds=self._window_seconds)
            values = []
            for timestamp, value in reversed(state.samples):
                if timestamp < cutoff:
                    break
                values.append(value)
            if not values:
                continue
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            standard_deviation = variance ** 0.5
            range_low = max(0.0, mean - standard_deviation)
            range_high = min(100.0, mean + standard_deviation)
            threshold = self._thresholds.get(gas_name)
            snapshots.append(
                ThresholdStatistics(
                    group_label=group_label,
                    gas_name=gas_name,
                    current_percent=state.current_value,
                    threshold_percent=threshold,
                    is_above=threshold is not None and state.current_value > threshold,
                    continuous_seconds=state.continuous_seconds,
                    cumulative_seconds=state.cumulative_seconds,
                    sample_count=len(values),
                    mean_percent=mean,
                    standard_deviation_percent=standard_deviation,
                    range_low_percent=range_low,
                    range_high_percent=range_high,
                    latest_time=state.latest_time,
                )
            )
        return snapshots

    def _trim_samples(self, state: _SeriesState, latest_time: datetime) -> None:
        # Preserve enough real samples to support enlarging the visible window.
        cutoff = latest_time - timedelta(seconds=86400)
        while state.samples and state.samples[0][0] < cutoff:
            state.samples.popleft()

    @staticmethod
    def _update_duration(
        state: _SeriesState,
        threshold: float | None,
        value: float,
        timestamp: datetime,
    ) -> None:
        previous_time = state.previous_time
        previous_value = state.previous_value
        if threshold is None or previous_time is None or previous_value is None:
            state.continuous_seconds = 0.0
            return

        elapsed = (timestamp - previous_time).total_seconds()
        if elapsed <= 0.0:
            state.continuous_seconds = 0.0 if value <= threshold else state.continuous_seconds
            return

        previous_above = previous_value > threshold
        current_above = value > threshold
        above_seconds = 0.0

        if previous_above and current_above:
            above_seconds = elapsed
            state.continuous_seconds += elapsed
        elif not previous_above and current_above:
            fraction = (threshold - previous_value) / (value - previous_value)
            above_seconds = elapsed * max(0.0, min(1.0, 1.0 - fraction))
            state.continuous_seconds = above_seconds
        elif previous_above and not current_above:
            fraction = (previous_value - threshold) / (previous_value - value)
            above_seconds = elapsed * max(0.0, min(1.0, fraction))
            state.continuous_seconds = 0.0
        else:
            state.continuous_seconds = 0.0

        state.cumulative_seconds += above_seconds
