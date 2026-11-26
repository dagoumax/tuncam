"""Bounded-memory, timestamp-aligned concentration CSV export."""

from __future__ import annotations

import csv
from datetime import datetime
from bisect import bisect_left

import numpy as np
from scipy.interpolate import PchipInterpolator


EXPORT_CHUNK_SIZE = 4096


def split_samples(values, times, breaks=()):
    pairs = sorted({t.timestamp(): float(v) for v, t in zip(values, times)}.items())
    boundaries = sorted(t.timestamp() for t in breaks)
    segments = []
    start = 0
    for i in range(1, len(pairs)):
        boundary = bisect_left(boundaries, pairs[i - 1][0])
        if boundary < len(boundaries) and boundaries[boundary] < pairs[i][0]:
            segments.append(pairs[start:i])
            start = i
    if pairs:
        segments.append(pairs[start:])
    return segments


def write_concentration_csv(path, columns, sample_rate=1, breaks=(), progress=None):
    """Interpolate only within sessions; absent probes produce empty cells."""
    rate = max(1, min(1000, int(sample_rate)))
    prepared = []
    intervals = []
    for _, values, times in columns:
        segments = []
        for pairs in split_samples(values, times, breaks):
            x, y = map(np.asarray, zip(*pairs))
            interpolation = PchipInterpolator(x, y, extrapolate=False) if len(x) > 1 else None
            segments.append((x, y, interpolation))
            intervals.append((float(x[0]), float(x[-1])))
        prepared.append(segments)

    spans = []
    for start, end in sorted(intervals):
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))

    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["时间 / Time", *(header for header, _, _ in columns)])
        total = sum(max(1, int(round((end - start) * rate)) + 1) for start, end in spans)
        completed = 0
        for start, end in spans:
            count = int(np.floor((end - start) * rate + 1e-6)) + 1
            endpoints = np.unique([point for interval in intervals for point in interval
                                   if start <= point <= end])
            for offset in range(0, count, EXPORT_CHUNK_SIZE):
                stop = min(count, offset + EXPORT_CHUNK_SIZE)
                grid = start + np.arange(offset, stop, dtype=float) / rate
                lower = start + offset / rate
                upper = start + stop / rate if stop < count else end + 1.0 / rate
                grid = np.unique(np.concatenate((grid, endpoints[(endpoints >= lower) & (endpoints < upper)])))
                grid = grid[grid <= end + 1e-7]
                block = np.full((len(grid), len(columns)), np.nan)
                for column, segments in enumerate(prepared):
                    for x, y, interpolation in segments:
                        inside = (grid >= x[0]) & (grid <= x[-1])
                        if not np.any(inside):
                            continue
                        block[inside, column] = interpolation(grid[inside]) if interpolation else y[0]
                for timestamp, row in zip(grid, block):
                    if np.all(np.isnan(row)):
                        continue
                    writer.writerow([
                        datetime.fromtimestamp(timestamp).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
                        *("" if np.isnan(value) else f"{value:.4f}" for value in row),
                    ])
                completed += stop - offset
                if progress is not None:
                    progress(min(100, int(completed * 100 / max(1, total))))
