from __future__ import annotations

import numpy as np


def monthly_log_params(
    expected_real_returns: list[float], volatilities: list[float]
) -> tuple[np.ndarray, np.ndarray]:
    """Convert annualized geometric real returns and vols to monthly log params.

    The expected return is interpreted as a geometric (median) annual return in
    today's purchasing power. Feeding it through log returns preserves that
    interpretation in the deterministic zero-volatility case.
    """
    expected = np.asarray(expected_real_returns, dtype=float)
    vols = np.asarray(volatilities, dtype=float)
    if expected.size != vols.size:
        raise ValueError("expected returns and volatilities must have the same length")
    if np.any(expected <= -1.0):
        raise ValueError("expected real return must be greater than -100%")
    if np.any(vols < 0.0):
        raise ValueError("volatility must be non-negative")
    return np.log1p(expected) / 12.0, vols / np.sqrt(12.0)


def monthly_fee_log(expense_ratios: list[float]) -> np.ndarray:
    """Monthly log drag that compounds to the stated annual expense ratio."""
    fees = np.asarray(expense_ratios, dtype=float)
    if np.any(fees < 0.0) or np.any(fees >= 1.0):
        raise ValueError("expense ratio must be in [0, 1)")
    return np.log1p(-fees) / 12.0


def cholesky_with_jitter(correlation: np.ndarray, jitter: float = 1e-10) -> np.ndarray:
    correlation = np.asarray(correlation, dtype=float)
    try:
        return np.linalg.cholesky(correlation)
    except np.linalg.LinAlgError:
        eigenvalues, eigenvectors = np.linalg.eigh(correlation)
        eigenvalues = np.clip(eigenvalues, jitter, None)
        repaired = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
        diagonal = np.sqrt(np.diag(repaired))
        repaired = repaired / np.outer(diagonal, diagonal)
        return np.linalg.cholesky(repaired + np.eye(len(correlation)) * jitter)


def draw_standardized_shocks(
    rng: np.random.Generator, n_paths: int, n_assets: int, student_t_df: float
) -> np.ndarray:
    """Unit-variance shocks, Student-t for fat tails when df > 2."""
    if student_t_df is not None and student_t_df > 2.0:
        shocks = rng.standard_t(student_t_df, size=(n_paths, n_assets))
        shocks *= np.sqrt((student_t_df - 2.0) / student_t_df)
        return shocks
    return rng.standard_normal((n_paths, n_assets))
