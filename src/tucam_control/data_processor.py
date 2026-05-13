# -*- coding: utf-8 -*-
"""
Data processor for splitting rows, merging columns, and baseline correction (arPLS).
"""

import numpy as np
from scipy import sparse
from scipy.sparse import diags
from scipy.sparse.linalg import spsolve


def arPLS(y: np.ndarray, lam: float = 1e5, max_iter: int = 50, tol: float = 1e-6) -> np.ndarray:
    """
    Asymmetrically Reweighted Penalized Least Squares baseline estimation.

    Parameters
    ----------
    y : np.ndarray
        1-D input signal.
    lam : float
        Smoothing parameter (larger = smoother baseline).
    max_iter : int
        Maximum iterations.
    tol : float
        Convergence tolerance.

    Returns
    -------
    np.ndarray
        Estimated baseline *z* (same shape as *y*).
    """
    y = np.asarray(y, dtype=np.float64).flatten()
    N = len(y)
    if N < 3:
        return y.copy()

    D = diags([1, -2, 1], [0, 1, 2], shape=(N - 2, N), format="csc")
    DTD = D.T @ D
    w = np.ones(N, dtype=np.float64)

    for _ in range(max_iter):
        W = diags(w, 0, shape=(N, N), format="csc")
        A = W + lam * DTD
        b = w * y
        z = spsolve(A, b)

        d = y - z
        idx = d < 0
        if np.any(idx):
            dn = d[idx]
            m = np.mean(dn)
            s = np.std(dn)
            s = max(s, np.finfo(np.float64).eps)
        else:
            m, s = 0.0, 1.0

        arg = 2 * (d - (-m + 2 * s)) / s
        arg = np.clip(arg, -60, 60)
        w_new = np.where(d >= 0, 1.0 / (1.0 + np.exp(arg)), 1.0)

        norm_w = np.linalg.norm(w)
        norm_w = max(norm_w, np.finfo(np.float64).eps)
        if np.linalg.norm(w_new - w) / norm_w < tol:
            w = w_new
            W = diags(w, 0, shape=(N, N), format="csc")
            z = spsolve(W + lam * DTD, w * y)
            break

        w = w_new

    return z


class DataProcessor:
    """
    Process a 2-D grayscale image array.

    Pipeline:
        1. Row grouping — extract specified row ranges, take the mean
           across rows to produce a 1-D spectrum per group.
        2. Column merging — average adjacent columns by *merge_factor*.
        3. Baseline correction (arPLS) — estimate and optionally subtract
           the baseline from each spectrum.

    Output is a 2-D array of shape ``(num_groups, 2048 // merge_factor)``.
    """

    BASELINE_RAW = "raw"
    BASELINE_CORRECTED = "corrected"
    BASELINE_ONLY = "baseline"

    def __init__(self) -> None:
        self._row_groups: list[tuple[int, int]] = []
        self._merge_factor: int = 1
        self._arPLS_enabled: bool = False
        self._arPLS_lam: float = 1e5
        self._arPLS_max_iter: int = 50
        self._arPLS_tol: float = 1e-6
        self._baseline_mode: str = self.BASELINE_RAW
        self._last_image: np.ndarray | None = None
        self._last_raw: np.ndarray | None = None
        self._last_baseline: np.ndarray | None = None
        self._last_result: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def row_groups(self) -> list[tuple[int, int]]:
        return self._row_groups

    @row_groups.setter
    def row_groups(self, groups: list[tuple[int, int]]) -> None:
        for s, e in groups:
            if s < 1 or e < s:
                raise ValueError(f"Invalid row group: ({s}, {e})")
        self._row_groups = groups

    @property
    def merge_factor(self) -> int:
        return self._merge_factor

    @merge_factor.setter
    def merge_factor(self, n: int) -> None:
        if n < 1:
            raise ValueError("Merge factor must be >= 1")
        self._merge_factor = n

    @property
    def arPLS_enabled(self) -> bool:
        return self._arPLS_enabled

    @arPLS_enabled.setter
    def arPLS_enabled(self, v: bool) -> None:
        self._arPLS_enabled = v

    @property
    def arPLS_lam(self) -> float:
        return self._arPLS_lam

    @arPLS_lam.setter
    def arPLS_lam(self, v: float) -> None:
        self._arPLS_lam = v

    @property
    def arPLS_max_iter(self) -> int:
        return self._arPLS_max_iter

    @arPLS_max_iter.setter
    def arPLS_max_iter(self, v: int) -> None:
        self._arPLS_max_iter = v

    @property
    def arPLS_tol(self) -> float:
        return self._arPLS_tol

    @arPLS_tol.setter
    def arPLS_tol(self, v: float) -> None:
        self._arPLS_tol = v

    @property
    def baseline_mode(self) -> str:
        return self._baseline_mode

    @baseline_mode.setter
    def baseline_mode(self, v: str) -> None:
        if v not in (self.BASELINE_RAW, self.BASELINE_CORRECTED, self.BASELINE_ONLY):
            raise ValueError(f"Unknown baseline_mode: {v}")
        self._baseline_mode = v

    @property
    def last_image(self) -> np.ndarray | None:
        return self._last_image

    @property
    def last_raw(self) -> np.ndarray | None:
        return self._last_raw

    @property
    def last_baseline(self) -> np.ndarray | None:
        return self._last_baseline

    @property
    def last_result(self) -> np.ndarray | None:
        return self._last_result

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(self, image: np.ndarray) -> np.ndarray:
        """
        Full pipeline on a 2-D image.

        Returns
        -------
        np.ndarray
            2-D array, shape ``(num_groups, 2048 // merge_factor)``.
        """
        self._last_image = image.copy()
        h, w = image.shape
        if not self._row_groups:
            self._row_groups = [(1, h)]

        # Row grouping → 1-D spectra
        spectra: list[np.ndarray] = []
        for start, end in self._row_groups:
            s_idx = start - 1
            e_idx = end
            if e_idx > h:
                raise ValueError(f"Row range ({start}, {end}) exceeds image height {h}")
            row_block = image[s_idx:e_idx, :].mean(axis=0, dtype=np.float64)
            spectra.append(row_block)

        merged = np.vstack(spectra)
        self._last_raw = merged.copy()

        # Column merging
        if self._merge_factor > 1:
            n = self._merge_factor
            new_w = w // n
            merged = merged[:, : new_w * n].reshape(merged.shape[0], new_w, n).mean(axis=2)

        # arPLS baseline correction
        merged = self._apply_arPLS(merged)

        self._last_result = merged
        return merged

    def reprocess(self) -> np.ndarray | None:
        """Re-run the full pipeline on the last cached image with current parameters."""
        if self._last_image is None:
            return None
        return self.process(self._last_image)

    def _apply_arPLS(self, merged: np.ndarray) -> np.ndarray:
        """Apply arPLS baseline correction to merged spectra."""
        if self._arPLS_enabled:
            baselines = np.zeros_like(merged)
            for i in range(merged.shape[0]):
                baselines[i] = arPLS(
                    merged[i],
                    lam=self._arPLS_lam,
                    max_iter=self._arPLS_max_iter,
                    tol=self._arPLS_tol,
                )
            self._last_baseline = baselines

            if self._baseline_mode == self.BASELINE_CORRECTED:
                return merged - baselines
            elif self._baseline_mode == self.BASELINE_ONLY:
                return baselines
        else:
            self._last_baseline = None
        return merged

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_groups(text: str) -> list[tuple[int, int]]:
        """
        Parse a user-friendly string into a list of row group tuples.

        Supports comma, space, and newline as separators.
        Format examples: ``"1-40, 91-130"``, ``"1-40 91-130"``,
        or multi-line entries.

        Returns an empty list if the string is empty.
        """
        text = text.strip()
        if not text:
            return []
        normalized = text.replace("\n", ",").replace("\r", ",").replace(" ", ",")
        groups: list[tuple[int, int]] = []
        for part in normalized.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" not in part:
                raise ValueError(
                    f"格式错误：无法解析「{part}」，请使用「起始行-结束行」格式。\n"
                    f"Invalid format: 「{part}」, expected 「start-end」."
                )
            a, b = part.split("-", 1)
            try:
                groups.append((int(a.strip()), int(b.strip())))
            except ValueError:
                raise ValueError(
                    f"格式错误：「{part}」中的行号无法识别为整数。\n"
                    f"Invalid: 「{part}」 contains non-integer values."
                )
        return groups
