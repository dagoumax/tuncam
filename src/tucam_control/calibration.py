# -*- coding: utf-8 -*-
"""Raman shift calibration — pixel-to-wavenumber mapping."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import find_peaks


@dataclass
class CalibrationPoint:
    """A single calibration point: pixel column ↔ Raman shift (cm⁻¹)."""
    pixel: int
    raman_shift: float = 0.0


def detect_peaks(spectrum: np.ndarray, height_ratio: float = 0.3,
                 distance: int = 10, max_peaks: int = 20) -> list[int]:
    """
    Auto-detect peaks in a 1-D spectrum.

    Returns list of pixel indices sorted by intensity (highest first).
    """
    threshold = float(np.min(spectrum)) + height_ratio * float(np.ptp(spectrum))
    peaks, props = find_peaks(spectrum, height=threshold, distance=distance)
    if len(peaks) == 0:
        return []
    intensities = props["peak_heights"]
    order = np.argsort(intensities)[::-1]
    result = [int(peaks[i]) for i in order[:max_peaks]]
    return sorted(result)


def fit_calibration(points: list[CalibrationPoint], degree: int = 2) -> np.ndarray:
    """
    Fit polynomial: Raman shift = poly(pixel) of given degree.

    Returns polynomial coefficients (highest degree first).
    """
    if len(points) < degree + 1:
        raise ValueError(f"Need at least {degree + 1} points for degree {degree}")
    px = np.array([p.pixel for p in points], dtype=np.float64)
    rs = np.array([p.raman_shift for p in points], dtype=np.float64)
    return np.polyfit(px, rs, degree)


def apply_calibration(pixels: np.ndarray, coeffs: np.ndarray | None) -> np.ndarray:
    """Convert pixel indices to Raman shift (cm⁻¹) using polynomial coefficients."""
    if coeffs is None or len(coeffs) == 0:
        return pixels.astype(np.float64)
    return np.polyval(coeffs, pixels.astype(np.float64))


def pixel_from_raman(raman_shift: float, coeffs: np.ndarray) -> int:
    """Given a Raman shift (cm⁻¹), find the nearest pixel column using calibration."""
    if coeffs is None or len(coeffs) == 0:
        return int(raman_shift)
    # Solve polynomial: coeffs[0]*p^n + ... + coeffs[-1] = raman_shift
    # Build polynomial with RHS subtracted
    p = np.polynomial.Polynomial(coeffs[::-1] - np.array([raman_shift]))
    roots = p.roots()
    real_roots = np.real(roots[np.isreal(roots)])
    positive_roots = real_roots[real_roots >= 0]
    if len(positive_roots) > 0:
        return int(round(positive_roots[0]))
    # Fallback: brute-force search
    candidates = np.arange(0, 4096)
    vals = np.polyval(coeffs, candidates.astype(np.float64))
    return int(candidates[np.argmin(np.abs(vals - raman_shift))])
