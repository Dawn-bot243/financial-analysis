from __future__ import annotations

import numpy as np
import pytest

from backend.app.core.engine import run_simulation
from backend.app.core.strategy import target_weights
from backend.app.models import (
    AssetAssumption,
    AssetPurchase,
    Household,
    InitialHolding,
    Liability,
    LifeEvent,
    MarketAssumptions,
    ScenarioRequest,
    StrategySpec,
)


def two_asset_request(**overrides) -> ScenarioRequest:
    payload = dict(
        name="test",
        market=MarketAssumptions(
            assets=[
                AssetAssumption(
                    name="cash",
                    label="现金",
                    role="cash",
                    expected_real_return=0.0,
                    volatility=0.0,
                    expense_ratio=0.0,
                ),
                AssetAssumption(
                    name="equity",
                    label="权益",
                    role="growth",
                    expected_real_return=0.0,
                    volatility=0.0,
                    expense_ratio=0.0,
                ),
            ],
            correlation=[[1.0, 0.0], [0.0, 1.0]],
        ),
        household=Household(
            current_age=30.0,
            initial_capital=0.0,
            holdings=[
                InitialHolding(asset="cash", label="现金", value=0.0),
                InitialHolding(asset="equity", label="权益", value=0.0),
            ],
            monthly_income=0.0,
            monthly_expense=0.0,
            liabilities=[],
            events=[],
            emergency_fund_months=0.0,
        ),
        strategy=StrategySpec(
            kind="constant",
            weights={"cash": 1.0, "equity": 0.0},
        ),
        horizon_years=1,
        n_paths=100,
        seed=1,
        include_explanation=False,
    )
    payload.update(overrides)
    return ScenarioRequest(**payload)


def test_emergency_fund_is_filled_before_investing():
    request = two_asset_request(
        household=Household(
            current_age=30.0,
            holdings=[
                InitialHolding(asset="cash", label="现金", value=0.0),
                InitialHolding(asset="equity", label="权益", value=1_000.0),
            ],
            monthly_income=2_000.0,
            monthly_expense=1_000.0,
            emergency_fund_months=10.0,
        ),
    )
    simulation = run_simulation(request)
    assert simulation.emergency_fund[0, -1] == pytest.approx(10_000.0)
    assert simulation.investable_assets[0, -1] == pytest.approx(3_000.0)
    assert simulation.total_assets[0, -1] == pytest.approx(13_000.0)


def test_emergency_fund_is_drawn_before_investable_assets():
    request = two_asset_request(
        household=Household(
            current_age=30.0,
            holdings=[
                InitialHolding(asset="cash", label="现金", value=10_000.0),
                InitialHolding(asset="equity", label="权益", value=5_000.0),
            ],
            monthly_income=0.0,
            monthly_expense=1_000.0,
            emergency_fund_months=10.0,
        ),
    )
    simulation = run_simulation(request)
    assert simulation.emergency_fund[0, 9] == pytest.approx(0.0, abs=1e-6)
    assert simulation.investable_assets[0, -1] == pytest.approx(3_000.0)
    assert not bool(simulation.ruin[0])


def test_growth_sleeve_glide_weights():
    strategy = StrategySpec(
        kind="glide",
        growth_assets=["equity"],
        growth_weights={"equity": 1.0},
        defensive_assets=["bond"],
        defensive_weights={"bond": 1.0},
        cash_asset="cash",
        cash_weight=0.0,
        growth_start=0.8,
        growth_end=0.4,
        glide_start_age=30.0,
        glide_end_age=60.0,
        floor=0.2,
        cap=1.0,
    )
    names = ["cash", "equity", "bond"]
    start = target_weights(strategy, names, 30.0)
    end = target_weights(strategy, names, 60.0)
    beyond = target_weights(strategy, names, 80.0)
    assert start.sum() == pytest.approx(1.0)
    assert end.sum() == pytest.approx(1.0)
    assert beyond.sum() == pytest.approx(1.0)
    assert start[1] == pytest.approx(0.8)
    assert end[1] == pytest.approx(0.4)
    assert beyond[1] == pytest.approx(0.4)
    assert start[2] == pytest.approx(0.2)
    assert end[2] == pytest.approx(0.6)


def test_purchase_and_sale_without_loan():
    request = two_asset_request(
        horizon_years=2,
        household=Household(
            current_age=30.0,
            holdings=[InitialHolding(asset="cash", label="现金", value=500_000.0)],
            monthly_income=0.0,
            monthly_expense=0.0,
            emergency_fund_months=0.0,
            events=[
                LifeEvent(
                    name="买车",
                    start_age=30.5,
                    purchase=AssetPurchase(
                        asset="car",
                        label="家用车",
                        price=100_000.0,
                        down_payment=100_000.0,
                        loan_months=0,
                        appreciation_rate=0.0,
                        selling_cost_rate=0.0,
                        sell_age=31.0,
                    ),
                )
            ],
        ),
    )
    simulation = run_simulation(request)
    assert bool(simulation.event_success[0, 0])
    # Age 30.5 is month 7 (age is current_age + (month - 1) / 12).
    assert simulation.illiquid_assets[0, 6] == pytest.approx(100_000.0)
    assert simulation.illiquid_assets[0, -1] == pytest.approx(0.0)
    assert simulation.total_assets[0, -1] == pytest.approx(500_000.0)


def test_failed_purchase_does_not_force_liquidation():
    request = two_asset_request(
        household=Household(
            current_age=30.0,
            holdings=[InitialHolding(asset="cash", label="现金", value=50_000.0)],
            monthly_income=0.0,
            monthly_expense=0.0,
            emergency_fund_months=0.0,
            events=[
                LifeEvent(
                    name="买房",
                    start_age=30.5,
                    purchase=AssetPurchase(
                        asset="real_estate",
                        label="房",
                        price=100_000.0,
                        down_payment=100_000.0,
                        loan_months=0,
                        appreciation_rate=0.0,
                        sell_age=31.0,
                    ),
                )
            ],
        ),
    )
    simulation = run_simulation(request)
    assert not bool(simulation.event_success[0, 0])
    assert simulation.event_gaps[0, 0] == pytest.approx(50_000.0)
    assert simulation.illiquid_assets[0, -1] == pytest.approx(0.0)
    assert simulation.total_assets[0, -1] == pytest.approx(50_000.0)


def test_initial_real_estate_sale_repays_linked_mortgage():
    request = two_asset_request(
        horizon_years=2,
        household=Household(
            current_age=30.0,
            holdings=[
                InitialHolding(
                    asset="real_estate",
                    label="自住房",
                    value=1_000_000.0,
                    liquidity="illiquid",
                    growth_rate=0.0,
                    selling_cost_rate=0.0,
                    sell_age=31.0,
                    liability_name="房贷",
                )
            ],
            monthly_income=400_000.0 / 60.0,
            monthly_expense=0.0,
            liabilities=[
                Liability(
                    name="房贷",
                    balance=400_000.0,
                    annual_rate=0.0,
                    remaining_months=60,
                    linked_holding="自住房",
                )
            ],
            emergency_fund_months=0.0,
        ),
    )
    simulation = run_simulation(request)
    assert simulation.initial_illiquid == pytest.approx(1_000_000.0)
    assert simulation.initial_liabilities == pytest.approx(400_000.0)
    assert simulation.initial_net_worth == pytest.approx(600_000.0)
    assert simulation.illiquid_assets[0, -1] == pytest.approx(0.0)
    assert simulation.liabilities[0, -1] == pytest.approx(0.0)
    # Age 31 is month 13. The sale repays the remaining balance after 12
    # payments. From the sale month onward the mortgage is gone, so the
    # monthly income lands in the liquid portfolio.
    expected = (
        1_000_000.0
        - (400_000.0 - 400_000.0 / 60.0 * 12.0)
        + 400_000.0 / 60.0 * 12.0
    )
    assert simulation.total_assets[0, -1] == pytest.approx(expected, abs=2.0)


def test_calibration_snapshot_is_psd_and_complete():
    from backend.app.assets import load_calibration

    calibration = load_calibration()
    assert calibration["data_version"]
    assert calibration["asset_order"] == [
        "csi300",
        "csi500",
        "dividend",
        "sse",
        "sp500",
        "ndx100",
        "nikkei",
        "hsi",
        "gold",
        "bond",
        "cash",
    ]
    for window in ("5y", "10y", "15y", "full"):
        matrix = np.asarray(calibration["correlations"][window]["matrix"], dtype=float)
        assert matrix.shape == (11, 11)
        assert np.allclose(matrix, matrix.T)
        assert np.linalg.eigvalsh(matrix).min() > -1e-8
        for asset in calibration["asset_order"]:
            assert window in calibration["assets"][asset]["windows"]
    ten_year = calibration["assets"]["csi300"]["windows"]["10y"]
    assert 0.0 < ten_year["real_geo"] < 0.2
    assert 0.0 < ten_year["volatility"] < 0.5
    # The 20-year COMEX gold proxy gives the 10-year asset window and the
    # common correlation window full coverage.
    assert calibration["assets"]["csi300"]["windows"]["10y"]["is_short"] is False
    assert calibration["assets"]["gold"]["windows"]["10y"]["is_short"] is False
    assert calibration["correlations"]["5y"]["is_short"] is False
    assert calibration["correlations"]["10y"]["is_short"] is False
    assert calibration["correlations"]["15y"]["is_short"] is False
    assert (
        calibration["correlations"]["10y"]["months"]
        == calibration["correlations"]["10y"]["requested_months"]
    )
