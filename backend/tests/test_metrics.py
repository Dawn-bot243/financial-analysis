import numpy as np
import pytest

from backend.app.core.metrics import wilson_interval


def test_wilson_interval_bounds_and_symmetry():
    low, high = wilson_interval(50, 100)
    assert 0.0 <= low < 0.5 < high <= 1.0
    assert low == pytest.approx(1.0 - high, abs=1e-12)


def test_wilson_interval_handles_extremes():
    low, high = wilson_interval(0, 100)
    assert low == pytest.approx(0.0)
    assert 0.0 < high < 0.05

    low, high = wilson_interval(100, 100)
    assert 0.95 < low < 1.0
    assert high == pytest.approx(1.0)


def test_wilson_interval_empty_sample():
    assert wilson_interval(0, 0) == (0.0, 0.0)
