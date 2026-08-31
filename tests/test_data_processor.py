from __future__ import annotations

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import spsolve

from tucam_control.data_processor import DataProcessor, arPLS


def _sparse_arpls_reference(
    y: np.ndarray,
    lam: float = 1e5,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64).flatten()
    n = len(y)
    if n < 3:
        return y.copy()
    difference = diags([1, -2, 1], [0, 1, 2], shape=(n - 2, n), format="csc")
    penalty = difference.T @ difference
    weights = np.ones(n, dtype=np.float64)

    for _ in range(max_iter):
        weight_matrix = diags(weights, 0, shape=(n, n), format="csc")
        baseline = spsolve(weight_matrix + lam * penalty, weights * y)
        residual = y - baseline
        negative = residual[residual < 0]
        if negative.size:
            mean = np.mean(negative)
            sigma = max(np.std(negative), np.finfo(np.float64).eps)
        else:
            mean, sigma = 0.0, 1.0
        argument = np.clip(
            2 * (residual - (-mean + 2 * sigma)) / sigma,
            -60,
            60,
        )
        new_weights = np.where(
            residual >= 0,
            1.0 / (1.0 + np.exp(argument)),
            1.0,
        )
        denominator = max(np.linalg.norm(weights), np.finfo(np.float64).eps)
        if np.linalg.norm(new_weights - weights) / denominator < tol:
            weights = new_weights
            weight_matrix = diags(weights, 0, shape=(n, n), format="csc")
            return spsolve(weight_matrix + lam * penalty, weights * y)
        weights = new_weights
    return baseline


def test_row_groups_default_to_sum() -> None:
    image = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)
    processor = DataProcessor()
    processor.row_groups = [(1, 2)]

    result = processor.process(image)

    np.testing.assert_array_equal(result, [[5.0, 7.0, 9.0]])


def test_row_groups_can_use_mean() -> None:
    image = np.array([[1, 2, 3], [3, 4, 5]], dtype=np.uint16)
    processor = DataProcessor()
    processor.row_groups = [(1, 2)]
    processor.row_aggregation = DataProcessor.ROW_AGGREGATION_MEAN

    result = processor.process(image)

    np.testing.assert_array_equal(result, [[2.0, 3.0, 4.0]])


def test_banded_arpls_matches_sparse_reference() -> None:
    rng = np.random.default_rng(20260724)
    x = np.linspace(0.0, 1.0, 512)
    spectrum = (
        100.0
        + 20.0 * x
        + 500.0 * np.exp(-((x - 0.4) / 0.01) ** 2)
        + rng.normal(0.0, 3.0, x.size)
    )

    expected = _sparse_arpls_reference(spectrum, lam=1e4)
    actual = arPLS(spectrum, lam=1e4)

    np.testing.assert_allclose(actual, expected, rtol=1e-9, atol=1e-8)


def test_banded_arpls_handles_constant_and_short_spectra() -> None:
    constant = np.full(64, 12.5)

    np.testing.assert_allclose(arPLS(constant), constant, atol=1e-6)
    np.testing.assert_array_equal(arPLS(np.asarray([1.0, 2.0])), [1.0, 2.0])


def test_baseline_only_display_keeps_corrected_analysis_result() -> None:
    x = np.arange(128, dtype=float)
    spectrum = 100.0 + 0.2 * x + 500.0 * np.exp(-((x - 60.0) / 2.0) ** 2)
    image = np.tile(spectrum, (4, 1)).astype(np.uint16)
    processor = DataProcessor()
    processor.row_groups = [(1, 4)]
    processor.arPLS_enabled = True
    processor.baseline_mode = DataProcessor.BASELINE_ONLY
    processor.arPLS_lam = 1e4

    displayed = processor.process(image)
    analysis = processor.last_analysis_result

    assert analysis is not None
    assert displayed.shape == analysis.shape == (1, 128)
    assert analysis[0, 60] > analysis[0, 45] + 500.0
    assert displayed[0, 60] < analysis[0, 60]
