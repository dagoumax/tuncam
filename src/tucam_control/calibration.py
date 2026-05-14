# -*- coding: utf-8 -*-
"""Raman shift calibration — pixel-to-wavenumber mapping."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks


@dataclass
class CalibrationPoint:
    """A single calibration point: pixel column ↔ Raman shift (cm⁻¹)."""
    pixel: int
    raman_shift: float = 0.0


def default_calibration() -> np.ndarray | None:
    """Return default linear calibration from known gas peaks.

    O2: pixel 572 → 1558 cm⁻¹
    N2: pixel 1015 → 2333 cm⁻¹
    """
    px = np.array([572, 1015], dtype=np.float64)
    rs = np.array([1558, 2333], dtype=np.float64)
    try:
        return np.polyfit(px, rs, 1)
    except Exception:
        return None


def detect_peaks(spectrum: np.ndarray, height_ratio: float = 0.3,
                 distance: int = 10, max_peaks: int = 20) -> list[int]:
    """Auto-detect peaks in a 1-D spectrum. Returns pixel indices sorted by intensity."""
    threshold = float(np.min(spectrum)) + height_ratio * float(np.ptp(spectrum))
    peaks, props = find_peaks(spectrum, height=threshold, distance=distance)
    if len(peaks) == 0:
        return []
    intensities = props["peak_heights"]
    order = np.argsort(intensities)[::-1]
    result = [int(peaks[i]) for i in order[:max_peaks]]
    return sorted(result)


def fit_calibration(points: list[CalibrationPoint], degree: int = 2) -> np.ndarray:
    """Fit polynomial: Raman shift = poly(pixel) of given degree.
    Returns polynomial coefficients (highest degree first)."""
    if len(points) < degree + 1:
        raise ValueError(f"Need at least {degree + 1} points for degree {degree}")
    px = np.array([p.pixel for p in points], dtype=np.float64)
    rs = np.array([p.raman_shift for p in points], dtype=np.float64)
    return np.polyfit(px, rs, degree)


def apply_calibration(pixels: np.ndarray, coeffs: np.ndarray | None) -> np.ndarray:
    """Convert pixel indices to Raman shift (cm⁻¹) using polynomial coefficients.
    Falls back to default calibration if coeffs is None."""
    if coeffs is None or len(coeffs) == 0:
        coeffs = default_calibration()
    if coeffs is None:
        return pixels.astype(np.float64)
    return np.polyval(coeffs, pixels.astype(np.float64))


def pixel_from_raman(raman_shift: float, coeffs: np.ndarray | None) -> int:
    """Given a Raman shift (cm⁻¹), find the nearest pixel column.
    Falls back to default calibration if coeffs is None."""
    if coeffs is None or len(coeffs) == 0:
        coeffs = default_calibration()
    if coeffs is None:
        return int(raman_shift)
    if len(coeffs) == 2:
        # Linear: p = (raman - b) / a
        return int(round((raman_shift - coeffs[1]) / coeffs[0]))
    # Higher order: solve coeffs[0]*p^n + ... + coeffs[-2]*p + coeffs[-1] - raman = 0
    poly = np.array(coeffs, copy=True)
    poly[-1] -= raman_shift
    roots = np.roots(poly)
    real_roots = np.real(roots[np.isreal(roots)])
    positive_roots = real_roots[real_roots >= 0]
    if len(positive_roots) > 0:
        return int(round(positive_roots[0]))
    candidates = np.arange(0, 4096)
    vals = np.polyval(coeffs, candidates.astype(np.float64))
    return int(candidates[np.argmin(np.abs(vals - raman_shift))])
