from __future__ import annotations

import numpy as np
import pytest

from backend.app.core.engine import run_simulation
from backend.app.core.metrics import build_metrics
from backend.app.models import (
    AssetAssumption,
    AssetPurchase,
    Household,
    InitialHolding,
    LifeEvent,
    MarketAssumptions,
    ScenarioRequest,
    StrategySpec,
)


def window_request(
    *,
    cash: float = 0.0,
    equity: float = 0.0,
    monthly_income: float = 10_000.0,
    monthly_expense: float = 0.0,
    emergency_months: float = 0.0,
    events: list[LifeEvent] | None = None,
    illiquid: float = 0.0,
    horizon_years: int = 1,
) -> ScenarioRequest:
    holdings = [
        InitialHolding(asset="cash", label="现金", value=cash),
        InitialHolding(asset="equity", label="权益", value=equity),
    ]
    if illiquid > 0:
        holdings.append(
            InitialHolding(
                asset="real_estate",
                label="自住房",
                value=illiquid,
                liquidity="illiquid",
                growth_rate=0.0,
            )
        )
    return ScenarioRequest(
        name="window-test",
        market=MarketAssumptions(
            assets=[
                AssetAssumption(
                    name="cash",
                    label="现金",
                    role="cash",
                    expected_real_return=0.0,
                    volatility=0.0,
                ),
                AssetAssumption(
                    name="equity",
                    label="权益",
                    role="growth",
                    expected_real_return=0.0,
                    volatility=0.0,
                ),
            ],
            correlation=[[1.0, 0.0], [0.0, 1.0]],
        ),
        household=Household(
            current_age=30.0,
            holdings=holdings,
            monthly_income=monthly_income,
            monthly_expense=monthly_expense,
            emergency_fund_months=emergency_months,
            events=events or [],
        ),
        strategy=StrategySpec(
            kind="constant",
            weights={"cash": 1.0, "equity": 0.0},
            rebalance="none",
        ),
        horizon_years=horizon_years,
        n_paths=100,
        seed=1,
        include_explanation=False,
    )


def car_purchase(
    *,
    start_age: float = 30.0,
    window_years: float = 1.0,
    price: float = 200_000.0,
    down_payment: float = 200_000.0,
    loan_months: int = 0,
    sell_age: float | None = None,
    appreciation_rate: float = 0.0,
) -> LifeEvent:
    return LifeEvent(
        name="买车",
        start_age=start_age,
        window_years=window_years,
        purchase=AssetPurchase(
            asset="car",
            label="车",
            price=price,
            down_payment=down_payment,
            loan_months=loan_months,
            appreciation_rate=appreciation_rate,
            sell_age=sell_age,
        ),
    )


def test_window_buys_at_first_affordable_month():
    request = window_request(
        equity=100_000.0,
        events=[car_purchase(window_years=1.0)],
    )
    simulation = run_simulation(request)

    # Month 1 has 110k; by month 10 the portfolio has 200k, enough for the
    # 200k down payment. The first affordable month is 10.
    assert simulation.event_success[0, 0]
    assert simulation.event_action_month[0, 0] == 10
    assert simulation.event_action_age[0, 0] == pytest.approx(30.0 + 9.0 / 12.0)
    assert not bool(simulation.event_deadline[0, 0])
    assert simulation.event_funding_investable[0, 0] == pytest.approx(200_000.0)
    assert simulation.event_funding_emergency[0, 0] == pytest.approx(0.0)
    assert simulation.event_costs[0, 0] == pytest.approx(200_000.0)

    metrics = build_metrics(request, simulation)
    result = metrics.events[0]
    assert result.window_years == pytest.approx(1.0)
    assert result.natural_success_probability == pytest.approx(1.0)
    assert result.deadline_success_probability == pytest.approx(0.0)
    assert result.failure_probability == pytest.approx(0.0)
    assert result.median_action_age == pytest.approx(30.0 + 9.0 / 12.0)
    assert result.timing
    assert result.timing[-1].probability == pytest.approx(1.0)
    assert result.funding_investable_mean == pytest.approx(200_000.0)


def test_window_deadline_purchase_is_classified_separately():
    request = window_request(
        equity=100_000.0,
        # Nine months after the start is month 10, the first affordable month.
        events=[car_purchase(window_years=9.0 / 12.0)],
    )
    simulation = run_simulation(request)
    assert simulation.event_action_month[0, 0] == 10
    assert bool(simulation.event_deadline[0, 0])

    result = build_metrics(request, simulation).events[0]
    assert result.natural_success_probability == pytest.approx(0.0)
    assert result.deadline_success_probability == pytest.approx(1.0)
    assert result.failure_probability == pytest.approx(0.0)


def test_window_purchase_fails_when_all_liquid_is_insufficient():
    request = window_request(
        equity=100_000.0,
        events=[car_purchase(window_years=0.5)],
    )
    simulation = run_simulation(request)
    assert not bool(simulation.event_success[0, 0])
    assert simulation.event_action_month[0, 0] == -1
    assert simulation.event_gaps[0, 0] == pytest.approx(30_000.0)
    assert simulation.illiquid_assets[0, -1] == pytest.approx(0.0)

    result = build_metrics(request, simulation).events[0]
    assert result.natural_success_probability == pytest.approx(0.0)
    assert result.deadline_success_probability == pytest.approx(0.0)
    assert result.failure_probability == pytest.approx(1.0)
    assert result.median_action_age is None


def test_purchase_uses_investable_assets_and_emergency_fund():
    request = window_request(
        cash=50_000.0,
        equity=50_000.0,
        monthly_income=5_000.0,
        monthly_expense=5_000.0,
        emergency_months=10.0,
        events=[car_purchase(window_years=0.0, down_payment=100_000.0, price=100_000.0)],
    )
    simulation = run_simulation(request)

    # The emergency target is 50k, carved from cash. The remaining 50k is
    # investable equity. The 100k down payment therefore uses both pools.
    assert simulation.event_success[0, 0]
    assert simulation.event_funding_investable[0, 0] == pytest.approx(50_000.0)
    assert simulation.event_funding_emergency[0, 0] == pytest.approx(50_000.0)
    assert np.allclose(simulation.total_assets[:, -1], 0.0)


def test_one_off_expense_waits_for_window_and_pays_early():
    request = window_request(
        equity=50_000.0,
        events=[
            LifeEvent(
                name="教育金",
                start_age=30.0,
                window_years=1.0,
                one_off_expense=100_000.0,
            )
        ],
    )
    simulation = run_simulation(request)
    # 50k + 10k per month: month 5 has 100k.
    assert simulation.event_success[0, 0]
    assert simulation.event_action_month[0, 0] == 5
    assert simulation.event_gaps[0, 0] == pytest.approx(0.0)

    result = build_metrics(request, simulation).events[0]
    assert result.natural_success_probability == pytest.approx(1.0)
    assert result.deadline_success_probability == pytest.approx(0.0)
    assert result.median_action_age == pytest.approx(30.0 + 4.0 / 12.0)


def test_one_off_expense_at_deadline_liquidates_all_and_records_gap():
    request = window_request(
        equity=50_000.0,
        events=[
            LifeEvent(
                name="教育金",
                start_age=30.0,
                window_years=3.0 / 12.0,
                one_off_expense=100_000.0,
            )
        ],
    )
    simulation = run_simulation(request)
    # Month 4 has 90k against a 100k expense: all financial assets are sold
    # and the remaining 10k is a gap.
    assert not bool(simulation.event_success[0, 0])
    assert simulation.event_gaps[0, 0] == pytest.approx(10_000.0)
    assert simulation.event_action_month[0, 0] == -1
    assert simulation.event_funding_investable[0, 0] == pytest.approx(90_000.0)
    # After the forced payment at month 4, the remaining eight months of income
    # are still invested, so the terminal balance is 80k.
    assert np.allclose(simulation.total_assets[:, -1], 80_000.0)

    result = build_metrics(request, simulation).events[0]
    assert result.failure_probability == pytest.approx(1.0)
    assert result.natural_success_probability == pytest.approx(0.0)
    assert result.deadline_success_probability == pytest.approx(0.0)


def test_illiquid_assets_are_not_auto_sold_for_a_purchase():
    request = window_request(
        cash=10_000.0,
        illiquid=1_000_000.0,
        monthly_income=0.0,
        events=[car_purchase(window_years=0.0, down_payment=100_000.0, price=100_000.0)],
    )
    simulation = run_simulation(request)
    assert not bool(simulation.event_success[0, 0])
    assert simulation.event_gaps[0, 0] == pytest.approx(90_000.0)
    assert simulation.initial_illiquid == pytest.approx(1_000_000.0)
    assert simulation.illiquid_assets[0, -1] == pytest.approx(1_000_000.0)


def test_window_sell_age_must_be_after_the_latest_purchase_month():
    with pytest.raises(ValueError):
        LifeEvent(
            name="买车",
            start_age=33.0,
            window_years=3.0,
            purchase=AssetPurchase(
                asset="car",
                price=100_000.0,
                down_payment=100_000.0,
                sell_age=35.0,
            ),
        )


def test_window_requires_a_purchase_or_one_off_expense():
    with pytest.raises(ValueError):
        LifeEvent(
            name="持续支出",
            start_age=33.0,
            window_years=3.0,
            monthly_expense=1_000.0,
        )
