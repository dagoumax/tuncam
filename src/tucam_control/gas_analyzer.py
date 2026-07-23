# -*- coding: utf-8 -*-
"""
Raman gas analysis — peak detection and concentration calculation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class GasConfig:
    """Configuration for a single gas species."""

    name: str
    position: int               # expected peak column index
    window: int = 15            # search window (± columns)
    coefficient: float = 1.0    # calibration coefficient
    raman_shift: float = 0.0    # reference Raman shift (cm⁻¹), 0 = unknown
    alarm_concentration: float | None = None  # alarm threshold in percent
    detection_sigma: float | None = None  # per-gas detection multiplier


def _local_baseline(spectrum: np.ndarray, center: int, window: int) -> float:
    """Estimate local baseline as the minimum value in the search window."""
    lo = max(0, min(center - window, len(spectrum) - 1))
    hi = min(len(spectrum), center + window + 1)
    if lo >= hi:
        return 0.0
    return float(np.min(spectrum[lo:hi]))


def find_peak(spectrum: np.ndarray, center: int, window: int) -> tuple[int, float, float]:
    """
    Find the peak near *center* ± *window*.

    Returns
    -------
    (peak_column, peak_height, peak_area)
        Peak area is computed as sum of (value – local_baseline) over the
        window, clamped to non-negative.
    """
    lo = max(0, min(center - window, len(spectrum) - 1))
    hi = min(len(spectrum), center + window + 1)
    if lo >= hi:
        return center, 0.0, 0.0
    region = spectrum[lo:hi]
    peak_col = lo + int(np.argmax(region))
    peak_height = float(region.max())

    baseline = _local_baseline(spectrum, center, window)
    subtracted = np.clip(region - baseline, 0, None)
    peak_area = float(np.sum(subtracted))

    return peak_col, peak_height, peak_area


def estimate_noise_sigma(
    spectrum: np.ndarray,
    gas_configs: list[GasConfig],
    merge_factor: int = 1,
) -> float:
    """Estimate noise with MAD after excluding all configured gas windows."""
    if spectrum.size == 0:
        return 0.0
    mask = np.ones(spectrum.size, dtype=bool)
    factor = max(1, int(merge_factor))
    for config in gas_configs:
        center = config.position // factor
        window = max(1, config.window // factor)
        lo = max(0, center - window)
        hi = min(spectrum.size, center + window + 1)
        if lo < hi:
            mask[lo:hi] = False

    noise = spectrum[mask]
    minimum_samples = min(spectrum.size, max(16, spectrum.size // 4))
    if noise.size < minimum_samples:
        noise = spectrum
    median = float(np.median(noise))
    mad = float(np.median(np.abs(noise - median)))
    if mad > 0.0:
        return 1.4826 * mad
    return float(np.std(noise - median))


@dataclass
class GasResult:
    """Analysis result for a single gas."""

    name: str
    position: int          # expected column
    found_col: int         # actual peak column
    peak_height: float
    peak_area: float
    coefficient: float
    component: float       # peak_height × coefficient
    concentration: float = 0.0   # fraction of total
    detected: bool = True


HALON_NAMES = {"halon", "halong", "哈龙"}
HALON_CORRECTION_MEASURED = np.asarray([0.0, 3.0, 5.4, 6.5, 10.0, 20.0])
HALON_CORRECTION_ACTUAL = np.asarray([0.0, 2.0, 5.0, 6.0, 10.0, 20.0])


def correct_halon_percentage(measured_percent: float) -> float:
    """Apply the empirical Halon calibration curve in percentage units."""
    measured = float(np.clip(measured_percent, 0.0, 100.0))
    if measured >= HALON_CORRECTION_MEASURED[-1]:
        return measured
    return float(np.interp(
        measured,
        HALON_CORRECTION_MEASURED,
        HALON_CORRECTION_ACTUAL,
    ))


def apply_halon_concentration_correction(results: list[GasResult]) -> None:
    """Correct Halon and rescale other gases proportionally to keep 100%."""
    halon = next(
        (result for result in results if result.name.strip().casefold() in HALON_NAMES),
        None,
    )
    if halon is None:
        return

    corrected = correct_halon_percentage(halon.concentration * 100.0) / 100.0
    corrected = float(np.clip(corrected, 0.0, 1.0))
    other_total = sum(result.concentration for result in results if result is not halon)
    halon.concentration = corrected
    if other_total <= 0.0:
        return
    scale = max(0.0, 1.0 - corrected) / other_total
    for result in results:
        if result is not halon:
            result.concentration *= scale


class GasAnalyzer:
    """
    Analyze Raman spectra for gas concentrations.

    Usage::

        analyzer = GasAnalyzer()
        analyzer.set_gases([
            GasConfig("O2", 584, 15, 1.0),
            GasConfig("N2", 1024, 15, 1.0),
            GasConfig("CO2", 488, 15, 1.0),
        ])
        results = analyzer.analyze(spectrum)  # spectrum is 1-D array
        for r in results:
            print(f"{r.name}: {r.concentration:.1%}")
    """

    def __init__(self) -> None:
        self._gases: list[GasConfig] = []
        self._threshold_sigma: float = 3.0
        self._merge_factor: int = 1
        self._baseline_corrected: bool = False
        self._last_noise_sigma: float = 0.0
        self._last_results: list[GasResult] = []

    @property
    def gases(self) -> list[GasConfig]:
        return self._gases

    @gases.setter
    def gases(self, configs: list[GasConfig]) -> None:
        self._gases = configs

    @property
    def threshold_sigma(self) -> float:
        return self._threshold_sigma

    @threshold_sigma.setter
    def threshold_sigma(self, v: float) -> None:
        self._threshold_sigma = max(0.01, float(v))

    @property
    def merge_factor(self) -> int:
        return self._merge_factor

    @merge_factor.setter
    def merge_factor(self, n: int) -> None:
        self._merge_factor = max(1, n)

    @property
    def baseline_corrected(self) -> bool:
        return self._baseline_corrected

    @baseline_corrected.setter
    def baseline_corrected(self, value: bool) -> None:
        self._baseline_corrected = bool(value)

    @property
    def last_results(self) -> list[GasResult]:
        return self._last_results

    @property
    def last_noise_sigma(self) -> float:
        return self._last_noise_sigma

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(self, spectrum: np.ndarray) -> list[GasResult]:
        """
        Find peaks and compute concentrations for all configured gases
        on a single 1-D spectrum.  Gas positions are automatically scaled
        by ``merge_factor`` to account for column merging.
        """
        if len(self._gases) == 0:
            return []

        factor = self._merge_factor
        noise_std = estimate_noise_sigma(spectrum, self._gases, factor)
        self._last_noise_sigma = noise_std

        results: list[GasResult] = []
        total_component = 0.0

        for cfg in self._gases:
            scaled_pos = cfg.position // factor
            scaled_win = max(1, cfg.window // factor)
            col, height, area = find_peak(spectrum, scaled_pos, scaled_win)
            if self._baseline_corrected:
                local_bl = 0.0
                net_height = max(0.0, height)
                lo = max(0, min(scaled_pos - scaled_win, len(spectrum) - 1))
                hi = min(len(spectrum), scaled_pos + scaled_win + 1)
                area = float(np.sum(np.clip(spectrum[lo:hi], 0, None)))
            else:
                local_bl = _local_baseline(spectrum, scaled_pos, scaled_win)
                net_height = height - local_bl

            detection_sigma = (
                cfg.detection_sigma
                if cfg.detection_sigma is not None
                else self._threshold_sigma
            )
            threshold = max(0.01, float(detection_sigma)) * noise_std
            detected = net_height > threshold
            if not detected:
                height = local_bl
                net_height = 0.0
                area = 0.0

            component = net_height * cfg.coefficient
            total_component += component

            results.append(GasResult(
                name=cfg.name,
                position=cfg.position,
                found_col=col,
                peak_height=height,
                peak_area=area,
                coefficient=cfg.coefficient,
                component=component,
                detected=detected,
            ))

        if total_component > 0:
            for r in results:
                r.concentration = r.component / total_component
        else:
            for r in results:
                r.concentration = 0.0

        apply_halon_concentration_correction(results)

        self._last_results = results
        return results

    def analyze_groups(self, spectra: np.ndarray) -> list[list[GasResult]]:
        """
        Analyze a 2-D array of spectra (n_groups × n_cols).

        Returns one list of GasResult per row group.
        """
        return [self.analyze(spectra[i]) for i in range(spectra.shape[0])]

    @staticmethod
    def default_gases() -> list[GasConfig]:
        """Return the default gas configuration for Dhyana-95-V2."""
        return [
            GasConfig("O2", 572, 15, 1.0, raman_shift=1558, detection_sigma=3.5),
            GasConfig("N2", 1015, 15, 1.0, raman_shift=2333, detection_sigma=4.0),
            GasConfig("CO2", 488, 15, 1.0, raman_shift=1387, detection_sigma=3.0),
        ]
