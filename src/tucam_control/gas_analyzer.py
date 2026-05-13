# -*- coding: utf-8 -*-
"""
Raman gas analysis — peak detection and concentration calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class GasConfig:
    """Configuration for a single gas species."""

    name: str
    position: int       # expected peak column index
    window: int = 15    # search window (± columns)
    coefficient: float = 1.0  # calibration coefficient


def _local_baseline(spectrum: np.ndarray, center: int, window: int) -> float:
    """Estimate local baseline as the minimum value in the search window."""
    lo = max(0, center - window)
    hi = min(len(spectrum), center + window + 1)
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
    lo = max(0, center - window)
    hi = min(len(spectrum), center + window + 1)
    region = spectrum[lo:hi]
    peak_col = lo + int(np.argmax(region))
    peak_height = float(region.max())

    baseline = _local_baseline(spectrum, center, window)
    subtracted = np.clip(region - baseline, 0, None)
    peak_area = float(np.sum(subtracted))

    return peak_col, peak_height, peak_area


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
        self._threshold_sigma: float = 2.0    # min height = noise_sigma × threshold
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
        self._threshold_sigma = v

    @property
    def last_results(self) -> list[GasResult]:
        return self._last_results

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(self, spectrum: np.ndarray) -> list[GasResult]:
        """
        Find peaks and compute concentrations for all configured gases
        on a single 1-D spectrum.
        """
        if len(self._gases) == 0:
            return []

        noise_std = float(np.std(spectrum))
        threshold = self._threshold_sigma * noise_std

        results: list[GasResult] = []
        total_component = 0.0

        for cfg in self._gases:
            col, height, area = find_peak(spectrum, cfg.position, cfg.window)
            local_bl = _local_baseline(spectrum, cfg.position, cfg.window)
            net_height = height - local_bl

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
            GasConfig("O2", 584, 15, 1.0),
            GasConfig("N2", 1024, 15, 1.0),
            GasConfig("CO2", 488, 15, 1.0),
        ]
