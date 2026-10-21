from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.engine import run_simulation
from backend.app.core.metrics import build_metrics
from backend.app.main import app
from backend.app.models import (
    AssetAssumption,
    Household,
    MarketAssumptions,
    ScenarioRequest,
    StrategySpec,
)

client = TestClient(app)


def simple_payload(**overrides) -> dict:
    payload = {
        "name": "简版测试",
        "initial_capital": 100_000.0,
        "monthly_contribution": 5_000.0,
        "horizon_years": 10,
        "weights": {"csi300": 1.0},
        "goal_amount": 2_000_000.0,
        "calibration_window": "10y",
        "n_paths": 200,
        "seed": 7,
    }
    payload.update(overrides)
    return payload


def test_simple_run_maps_to_a_constant_allocation_scenario():
    response = client.post("/api/simple", json=simple_payload())
    assert response.status_code == 200, response.text
    run = response.json()

    household = run["request"]["household"]
    assert household["monthly_income"] == pytest.approx(5_000.0)
    assert household["monthly_expense"] == pytest.approx(0.0)
    assert household["emergency_fund_months"] == pytest.approx(0.0)
    assert household["events"] == []
    assert household["liabilities"] == []
    assert len(household["holdings"]) == 7
    positive = [
        holding
        for holding in household["holdings"]
        if holding["value"] > 0
    ]
    assert positive[0]["asset"] == "csi300"
    assert positive[0]["value"] == pytest.approx(100_000.0)

    assert run["request"]["strategy"]["kind"] == "constant"
    assert run["request"]["strategy"]["rebalance"] == "annual"
    assert run["request"]["goal_amount"] == pytest.approx(2_000_000.0)
    assert run["metrics"]["goal_amount"] == pytest.approx(2_000_000.0)
    assert 0.0 <= run["metrics"]["goal_probability"] <= 1.0
    assert run["metrics"]["terminal_assets"]["p50"] > 0.0
    assert run["explanation"]["source"] == "template"


@pytest.mark.parametrize(
    "payload",
    [
        simple_payload(weights={"csi300": 0.9}),
        simple_payload(weights={"not_an_asset": 1.0}),
        simple_payload(weights={}),
        simple_payload(initial_capital=0.0, monthly_contribution=0.0),
    ],
)
def test_simple_rejects_invalid_inputs(payload):
    response = client.post("/api/simple", json=payload)
    assert response.status_code == 422


def test_goal_probability_uses_terminal_liquid_assets():
    def request_with_goal(goal: float) -> ScenarioRequest:
        return ScenarioRequest(
            name="goal",
            market=MarketAssumptions(
                assets=[
                    AssetAssumption(
                        name="equity",
                        label="权益",
                        role="growth",
                        expected_real_return=0.0,
                        volatility=0.0,
                    )
                ],
                correlation=[[1.0]],
            ),
            household=Household(
                current_age=30.0,
                initial_capital=100_000.0,
                monthly_income=0.0,
                monthly_expense=0.0,
                events=[],
                emergency_fund_months=0.0,
            ),
            strategy=StrategySpec(kind="all_equity", equity_asset="equity"),
            horizon_years=1,
            n_paths=100,
            seed=1,
            include_explanation=False,
            goal_amount=goal,
        )

    hit = build_metrics(request_with_goal(100_000.0), run_simulation(request_with_goal(100_000.0)))
    miss = build_metrics(request_with_goal(200_000.0), run_simulation(request_with_goal(200_000.0)))
    assert hit.goal_probability == pytest.approx(1.0)
    assert hit.goal_ci95_high == pytest.approx(1.0)
    assert hit.goal_ci95_low > 0.9
    assert miss.goal_probability == pytest.approx(0.0)
    assert miss.goal_ci95_low == pytest.approx(0.0)
