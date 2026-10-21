import numpy as np
import pytest

from backend.app.core.engine import run_simulation
from backend.app.core.metrics import build_metrics
from backend.app.core.strategy import target_weights
from backend.app.models import (
    AssetAssumption,
    Household,
    LifeEvent,
    MarketAssumptions,
    ScenarioRequest,
    StrategySpec,
)


def single_asset_request(**overrides) -> ScenarioRequest:
    payload = dict(
        name="test",
        market=MarketAssumptions(
            assets=[
                AssetAssumption(
                    name="equity",
                    expected_real_return=0.06,
                    volatility=0.0,
                    expense_ratio=0.0,
                )
            ],
            correlation=[[1.0]],
            student_t_df=5.0,
        ),
        household=Household(
            current_age=30.0,
            initial_capital=10_000.0,
            monthly_income=1_000.0,
            monthly_expense=0.0,
            liabilities=[],
            events=[],
        ),
        strategy=StrategySpec(
            kind="all_equity",
            equity_asset="equity",
            rebalance="annual",
        ),
        horizon_years=1,
        n_paths=100,
        seed=1,
        include_explanation=False,
    )
    payload.update(overrides)
    return ScenarioRequest(**payload)


def test_zero_vol_terminal_value_matches_closed_form_annuity():
    request = single_asset_request()
    simulation = run_simulation(request)

    monthly_return = (1.06) ** (1.0 / 12.0) - 1.0
    contributions_fv = sum(
        (1.0 + monthly_return) ** k for k in range(1, 13)
    ) * 1_000.0
    expected = 10_000.0 * 1.06 + contributions_fv

    assert np.allclose(simulation.total_assets[:, -1], expected)
    assert np.allclose(simulation.twr_index[:, -1], 1.06)
    # Contributions are reported per path, not summed across paths.
    assert simulation.total_contributions == pytest.approx(12_000.0)


def test_zero_vol_has_no_drawdown():
    request = single_asset_request()
    metrics = build_metrics(request, run_simulation(request))
    assert metrics.max_drawdown.p50 == pytest.approx(0.0)
    assert metrics.max_drawdown.p95 == pytest.approx(0.0)
    assert sum(metrics.max_drawdown.hist_counts) == request.n_paths


def test_event_shortfall_liquidates_all_assets():
    request = single_asset_request(
        market=MarketAssumptions(
            assets=[
                AssetAssumption(
                    name="equity",
                    expected_real_return=0.0,
                    volatility=0.0,
                    expense_ratio=0.0,
                )
            ],
            correlation=[[1.0]],
        ),
        household=Household(
            current_age=30.0,
            initial_capital=100_000.0,
            monthly_income=0.0,
            monthly_expense=0.0,
            liabilities=[],
            events=[LifeEvent(name="买房", age=30.5, amount=150_000.0)],
        ),
    )
    simulation = run_simulation(request)
    assert simulation.event_success[0, 0] == np.False_
    assert simulation.event_gaps[0, 0] == pytest.approx(50_000.0)
    assert np.allclose(simulation.total_assets[:, -1], 0.0)


def test_event_success_leaves_remaining_assets():
    request = single_asset_request(
        market=MarketAssumptions(
            assets=[
                AssetAssumption(
                    name="equity",
                    expected_real_return=0.0,
                    volatility=0.0,
                    expense_ratio=0.0,
                )
            ],
            correlation=[[1.0]],
        ),
        household=Household(
            current_age=30.0,
            initial_capital=100_000.0,
            monthly_income=0.0,
            monthly_expense=0.0,
            liabilities=[],
            events=[LifeEvent(name="教育", age=30.5, amount=50_000.0)],
        ),
    )
    simulation = run_simulation(request)
    assert simulation.event_success[0, 0] == np.True_
    assert simulation.event_gaps[0, 0] == pytest.approx(0.0)
    assert np.allclose(simulation.total_assets[:, -1], 50_000.0)


def test_negative_cash_flow_marks_ruin():
    request = single_asset_request(
        household=Household(
            current_age=30.0,
            initial_capital=1_000.0,
            monthly_income=0.0,
            monthly_expense=2_000.0,
            liabilities=[],
            events=[],
        )
    )
    simulation = run_simulation(request)
    assert bool(simulation.ruin[0])
    assert np.allclose(simulation.total_assets[:, -1], 0.0)


def test_event_outside_horizon_is_dropped_with_warning():
    request = single_asset_request(
        household=Household(
            current_age=30.0,
            initial_capital=10_000.0,
            monthly_income=1_000.0,
            monthly_expense=0.0,
            liabilities=[],
            events=[LifeEvent(name="退休", age=60.0, amount=1_000_000.0)],
        )
    )
    simulation = run_simulation(request)
    assert simulation.events == []
    assert any("区间外" in warning for warning in simulation.warnings)


def test_same_seed_is_reproducible_and_different_seed_differs():
    request = single_asset_request(
        market=MarketAssumptions(
            assets=[
                AssetAssumption(
                    name="equity",
                    expected_real_return=0.06,
                    volatility=0.2,
                    expense_ratio=0.0,
                )
            ],
            correlation=[[1.0]],
        ),
        n_paths=200,
        horizon_years=2,
    )
    first = run_simulation(request)
    second = run_simulation(request)
    assert np.array_equal(first.total_assets, second.total_assets)

    different = run_simulation(request.model_copy(update={"seed": 999}))
    assert not np.array_equal(first.total_assets, different.total_assets)


def test_glide_path_weights_are_bounded_and_sum_to_one():
    request = single_asset_request()
    strategy = StrategySpec(
        kind="glide",
        equity_start=0.8,
        equity_end=0.4,
        glide_start_age=30.0,
        glide_end_age=60.0,
        floor=0.2,
        cap=1.0,
    )
    names = ["equity", "bond", "cash"]
    start = target_weights(strategy, names, 30.0)
    end = target_weights(strategy, names, 60.0)
    beyond = target_weights(strategy, names, 80.0)
    assert start.sum() == pytest.approx(1.0)
    assert end.sum() == pytest.approx(1.0)
    assert beyond.sum() == pytest.approx(1.0)
    assert start[0] == pytest.approx(0.8)
    assert end[0] == pytest.approx(0.4)
    assert beyond[0] == pytest.approx(0.4)
