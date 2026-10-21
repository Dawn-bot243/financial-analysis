from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.core.history import (
    AssetHistory,
    HistoryData,
    run_history_backtest,
)
from backend.app.main import app
from backend.app.models import HistoryRequest

client = TestClient(app)


def monthly_dates(count: int) -> list[date]:
    return [
        date(2020 + (index // 12), (index % 12) + 1, 1)
        for index in range(count)
    ]


def synthetic_data(prices: list[float]) -> HistoryData:
    dates = monthly_dates(len(prices))
    asset = AssetHistory(
        name="test",
        label="测试资产",
        source="synthetic",
        role="growth",
        dates=dates,
        prices=np.asarray(prices, dtype=float),
    )
    return HistoryData(
        data_version="synthetic",
        inflation_assumption=0.02,
        latest_date=dates[-1],
        source_note="",
        assets={"test": asset},
    )


def test_constant_price_dca_has_zero_profit_and_irr():
    data = synthetic_data([1.0] * 13)
    request = HistoryRequest(
        mode="single",
        asset="test",
        initial_capital=1_000.0,
        monthly_contribution=100.0,
        start_date=data.assets["test"].dates[0],
        end_date=data.assets["test"].dates[-1],
        lookback_years=None,
        rebalance="none",
    )
    result = run_history_backtest(request, data)
    assert result.total_invested == pytest.approx(2_300.0)
    assert result.terminal_value == pytest.approx(2_300.0)
    assert result.profit == pytest.approx(0.0)
    assert result.irr_annual == pytest.approx(0.0, abs=1e-6)
    assert result.max_drawdown == pytest.approx(0.0)
    assert result.contribution_count == 13
    assert result.path[-1].value == pytest.approx(2_300.0)


def test_rising_price_dca_has_positive_irr():
    prices = [1.01**index for index in range(13)]
    data = synthetic_data(prices)
    request = HistoryRequest(
        mode="single",
        asset="test",
        initial_capital=1_000.0,
        monthly_contribution=100.0,
        start_date=data.assets["test"].dates[0],
        end_date=data.assets["test"].dates[-1],
        lookback_years=None,
        rebalance="none",
    )
    result = run_history_backtest(request, data)
    assert result.terminal_value > result.total_invested
    assert result.profit > 0
    assert result.irr_annual is not None and result.irr_annual > 0
    assert result.max_drawdown == pytest.approx(0.0)


def test_drawdown_is_computed_from_time_weighted_unit_value():
    data = synthetic_data([1.0, 1.2, 0.6, 0.8, 0.9, 1.0])
    request = HistoryRequest(
        mode="single",
        asset="test",
        initial_capital=1_000.0,
        monthly_contribution=100.0,
        start_date=data.assets["test"].dates[0],
        end_date=data.assets["test"].dates[-1],
        lookback_years=None,
        rebalance="none",
    )
    result = run_history_backtest(request, data)
    assert result.max_drawdown == pytest.approx(0.5)
    assert result.drawdown_peak_date == data.assets["test"].dates[1]
    assert result.drawdown_trough_date == data.assets["test"].dates[2]


def test_history_meta():
    response = client.get("/api/history/meta")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data_version"]
    assert payload["latest_date"] == "2026-10-20"
    assert {asset["name"] for asset in payload["assets"]} == {
        "csi300",
        "csi500",
        "dividend",
        "ndx100",
        "gold",
        "bond",
    }


def test_gold_last_ten_years_backtest():
    body = {
        "mode": "single",
        "asset": "gold",
        "initial_capital": 100_000,
        "monthly_contribution": 5_000,
        "lookback_years": 10,
        "end_date": "2026-10-20",
        "rebalance": "annual",
    }
    response = client.post("/api/history/backtest", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["run_id"] and len(payload["run_id"]) == 16
    assert payload["effective_start_date"] == "2016-10-20"
    assert payload["effective_end_date"] == "2026-10-20"
    assert payload["terminal_value"] > 0
    assert payload["total_invested"] == pytest.approx(705_000.0)
    assert payload["contribution_count"] == 121
    assert payload["path"]
    assert payload["irr_annual"] is not None
    assert 0.0 <= payload["max_drawdown"] <= 1.0
    assert payload["warnings"] == []

    second = client.post("/api/history/backtest", json=body)
    assert second.json()["run_id"] == payload["run_id"]

    fetched = client.get(f"/api/history/runs/{payload['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["terminal_value"] == pytest.approx(payload["terminal_value"])


def test_portfolio_backtest_and_validation():
    body = {
        "mode": "portfolio",
        "asset": "gold",
        "weights": {
            "csi300": 0.4,
            "csi500": 0.1,
            "dividend": 0.1,
            "ndx100": 0.1,
            "gold": 0.1,
            "bond": 0.2,
        },
        "initial_capital": 100_000,
        "monthly_contribution": 5_000,
        "lookback_years": 10,
        "end_date": "2026-10-20",
        "rebalance": "annual",
    }
    response = client.post("/api/history/backtest", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["final_composition"]) == 6
    assert sum(item["value"] for item in payload["final_composition"]) == pytest.approx(
        payload["terminal_value"], rel=1e-6
    )
    assert sum(item["weight"] for item in payload["final_composition"]) == pytest.approx(
        1.0, abs=1e-6
    )

    bad = dict(body)
    bad["weights"] = {"csi300": 0.9}
    assert client.post("/api/history/backtest", json=bad).status_code == 422

    unknown = dict(body)
    unknown["mode"] = "single"
    unknown["asset"] = "not_an_asset"
    assert client.post("/api/history/backtest", json=unknown).status_code == 422


def test_custom_dates_and_zero_monthly_contribution():
    body = {
        "mode": "single",
        "asset": "csi300",
        "initial_capital": 100_000,
        "monthly_contribution": 0,
        "start_date": "2020-01-01",
        "end_date": "2021-01-01",
        "rebalance": "none",
    }
    response = client.post("/api/history/backtest", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["contribution_count"] == 0
    assert payload["total_invested"] == pytest.approx(100_000.0)
    assert payload["effective_start_date"] >= "2020-01-01"
    assert payload["effective_end_date"] <= "2021-01-01"
