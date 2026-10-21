from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def defaults_body() -> dict:
    response = client.get("/api/defaults")
    assert response.status_code == 200
    body = response.json()["request"]
    body["include_explanation"] = False
    body["n_paths"] = 200
    body["seed"] = 7
    return body


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["llm_enabled"] is False


def test_defaults_include_assets_and_presets():
    response = client.get("/api/defaults")
    assert response.status_code == 200
    payload = response.json()
    assert [asset["name"] for asset in payload["request"]["market"]["assets"]] == [
        "csi300",
        "csi500",
        "dividend",
        "ndx100",
        "gold",
        "bond",
        "cash",
    ]
    assert set(payload["presets"]) == {"conservative", "base", "optimistic"}
    assert payload["calibration"]["data_version"]
    assert "10y" in payload["calibration"]["correlations"]


def test_calibration_endpoint():
    response = client.get("/api/calibration")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_version"]
    assert set(payload["correlations"]) == {"5y", "10y", "15y", "full"}


def test_create_get_and_list_run():
    body = defaults_body()
    response = client.post("/api/runs", json=body)
    assert response.status_code == 200, response.text
    run = response.json()
    assert len(run["run_id"]) == 16
    assert run["explanation"]["source"] == "template"
    assert run["metrics"]["terminal_assets"]["p50"] > 0
    assert run["code_fingerprint"]

    fetched = client.get(f"/api/runs/{run['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run["run_id"]

    listed = client.get("/api/runs?limit=5")
    assert listed.status_code == 200
    assert any(item["run_id"] == run["run_id"] for item in listed.json())

    missing = client.get("/api/runs/does-not-exist")
    assert missing.status_code == 404


def test_same_request_is_idempotent():
    body = defaults_body()
    first = client.post("/api/runs", json=body).json()
    second = client.post("/api/runs", json=body).json()
    assert first["run_id"] == second["run_id"]
    assert first["created_at"] == second["created_at"]


def test_compare_scenarios_use_common_seed():
    conservative = defaults_body()
    conservative["name"] = "保守"
    conservative["n_paths"] = 500
    conservative["market"]["assets"][0]["expected_real_return"] = 0.02

    optimistic = deepcopy(conservative)
    optimistic["name"] = "乐观"
    optimistic["market"]["assets"][0]["expected_real_return"] = 0.06

    response = client.post("/api/compare", json=[conservative, optimistic])
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["name"] for item in items] == ["保守", "乐观"]
    assert items[0]["terminal_assets_p50"] < items[1]["terminal_assets_p50"]
    assert all(len(item["run_id"]) == 16 for item in items)


def test_life_path_comparison_with_and_without_car():
    baseline = defaults_body()
    baseline["name"] = "含买车"
    baseline["n_paths"] = 500

    no_car = deepcopy(baseline)
    no_car["name"] = "不买车"
    no_car["household"]["events"] = [
        event
        for event in no_car["household"]["events"]
        if not event.get("purchase")
    ]

    response = client.post("/api/compare", json=[baseline, no_car])
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["name"] for item in items] == ["含买车", "不买车"]
    assert items[0]["terminal_assets_p25"] is not None
    assert items[0]["terminal_assets_p75"] is not None
    # The no-car path avoids the down payment, maintenance, interest and
    # depreciation, so its median liquid assets should be higher.
    assert items[1]["terminal_assets_p50"] > items[0]["terminal_assets_p50"]


def test_default_run_includes_window_event_metrics():
    body = defaults_body()
    body["n_paths"] = 200
    response = client.post("/api/runs", json=body)
    assert response.status_code == 200, response.text
    run = response.json()

    car_event = next(
        event for event in run["request"]["household"]["events"] if event["name"] == "购车"
    )
    assert car_event["window_years"] == pytest.approx(3.0)

    car_result = next(
        event for event in run["metrics"]["events"] if event["name"] == "购车"
    )
    assert car_result["window_years"] == pytest.approx(3.0)
    assert car_result["window_end_age"] == pytest.approx(36.0)
    assert car_result["timing"]
    assert car_result["timing"][-1]["probability"] == pytest.approx(
        car_result["success_probability"]
    )
    assert (
        car_result["natural_success_probability"]
        + car_result["deadline_success_probability"]
    ) == pytest.approx(car_result["success_probability"])
    assert car_result["funding_investable_mean"] is not None
    assert car_result["funding_emergency_mean"] is not None


def test_malformed_static_path_returns_404_not_500():
    response = client.get("/%2A%2A%E3%80%82")
    assert response.status_code == 404


def test_compare_requires_shared_seed():
    first = defaults_body()
    second = defaults_body()
    second["seed"] = first["seed"] + 1
    response = client.post("/api/compare", json=[first, second])
    assert response.status_code == 422


def test_invalid_constant_weights_are_rejected():
    body = defaults_body()
    body["strategy"] = {
        "kind": "constant",
        "weights": {"equity": 0.5, "bond": 0.2, "cash": 0.1},
    }
    response = client.post("/api/runs", json=body)
    assert response.status_code == 422
