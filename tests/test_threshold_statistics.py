# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

import pytest

from tucam_control.gas_analyzer import GasResult
from tucam_control.threshold_statistics import ThresholdStatisticsTracker


def _result(value_percent: float) -> GasResult:
    return GasResult(
        name="halong",
        position=0,
        found_col=0,
        peak_height=1.0,
        peak_area=1.0,
        coefficient=1.0,
        component=value_percent,
        concentration=value_percent / 100.0,
    )


def _add(
    tracker: ThresholdStatisticsTracker,
    value_percent: float,
    timestamp: datetime,
) -> None:
    tracker.update([[_result(value_percent)]], ["行 1-10"], timestamp)


def test_threshold_crossings_are_linearly_interpolated() -> None:
    tracker = ThresholdStatisticsTracker()
    tracker.set_thresholds({"halong": 10.0})
    start = datetime(2026, 7, 23, 10, 0, 0)

    _add(tracker, 8.0, start)
    _add(tracker, 12.0, start + timedelta(seconds=4))
    rising = tracker.snapshots()[0]
    assert rising.continuous_seconds == pytest.approx(2.0)
    assert rising.cumulative_seconds == pytest.approx(2.0)

    _add(tracker, 8.0, start + timedelta(seconds=8))
    falling = tracker.snapshots()[0]
    assert falling.continuous_seconds == 0.0
    assert falling.cumulative_seconds == pytest.approx(4.0)


def test_equal_threshold_is_not_above() -> None:
    tracker = ThresholdStatisticsTracker()
    tracker.set_thresholds({"halong": 10.0})
    start = datetime(2026, 7, 23, 10, 0, 0)

    _add(tracker, 10.0, start)
    _add(tracker, 10.0, start + timedelta(seconds=3))

    snapshot = tracker.snapshots()[0]
    assert snapshot.is_above is False
    assert snapshot.continuous_seconds == 0.0
    assert snapshot.cumulative_seconds == 0.0


def test_gap_breaks_continuous_time_but_preserves_total() -> None:
    tracker = ThresholdStatisticsTracker()
    tracker.set_thresholds({"halong": 10.0})
    start = datetime(2026, 7, 23, 10, 0, 0)

    _add(tracker, 12.0, start)
    _add(tracker, 12.0, start + timedelta(seconds=3))
    tracker.mark_gap()
    _add(tracker, 12.0, start + timedelta(seconds=300))

    snapshot = tracker.snapshots()[0]
    assert snapshot.continuous_seconds == 0.0
    assert snapshot.cumulative_seconds == pytest.approx(3.0)


def test_multiple_episodes_accumulate_until_reset() -> None:
    tracker = ThresholdStatisticsTracker()
    tracker.set_thresholds({"halong": 10.0})
    start = datetime(2026, 7, 23, 10, 0, 0)

    for seconds, value in ((0, 11.0), (2, 11.0), (4, 9.0), (6, 11.0), (8, 11.0)):
        _add(tracker, value, start + timedelta(seconds=seconds))

    assert tracker.snapshots()[0].cumulative_seconds == pytest.approx(6.0)
    tracker.reset()
    assert tracker.snapshots() == []


def test_rolling_window_uses_only_recent_values_for_mean() -> None:
    tracker = ThresholdStatisticsTracker(window_seconds=5)
    start = datetime(2026, 7, 23, 10, 0, 0)

    _add(tracker, 1.0, start)
    _add(tracker, 3.0, start + timedelta(seconds=4))
    _add(tracker, 5.0, start + timedelta(seconds=6))

    snapshot = tracker.snapshots()[0]
    assert snapshot.sample_count == 2
    assert snapshot.mean_percent == pytest.approx(4.0)
    assert snapshot.standard_deviation_percent == pytest.approx(1.0)
    assert snapshot.range_low_percent == pytest.approx(3.0)
    assert snapshot.range_high_percent == pytest.approx(5.0)


def test_single_sample_has_zero_standard_deviation() -> None:
    tracker = ThresholdStatisticsTracker()
    now = datetime(2026, 7, 23, 10, 0, 0)
    _add(tracker, 100.0, now)

    snapshot = tracker.snapshots()[0]
    assert snapshot.sample_count == 1
    assert snapshot.mean_percent == 100.0
    assert snapshot.standard_deviation_percent == 0.0
    assert snapshot.range_low_percent == 100.0
    assert snapshot.range_high_percent == 100.0
