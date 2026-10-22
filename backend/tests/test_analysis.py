import json

import pytest
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.core import advice
from backend.app.core.advice import validate_analysis_payload
from backend.app.main import app

client = TestClient(app)


def create_run_body(n_paths: int = 200) -> dict:
    body = client.get("/api/defaults").json()["request"]
    body["include_explanation"] = False
    body["n_paths"] = n_paths
    body["seed"] = 11
    return body


def create_full_run() -> dict:
    response = client.post("/api/runs", json=create_run_body())
    assert response.status_code == 200, response.text
    return response.json()


def create_simple_run() -> dict:
    response = client.post(
        "/api/simple",
        json={
            "name": "简版分析测试",
            "initial_capital": 100_000,
            "monthly_contribution": 5_000,
            "horizon_years": 10,
            "weights": {
                "csi300": 0.4,
                "dividend": 0.2,
                "ndx100": 0.2,
                "bond": 0.2,
            },
            "goal_amount": 1_000_000,
            "calibration_window": "10y",
            "n_paths": 200,
            "seed": 11,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_full_analysis_template_and_cache():
    run = create_full_run()
    response = client.post(
        "/api/analysis", json={"mode": "full", "run_id": run["run_id"]}
    )
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["source"] == "template"
    assert len(analysis["analysis_id"]) == 16
    assert analysis["run_id"] == run["run_id"]
    assert len(analysis["variants"]) >= 2
    assert analysis["variants"][0]["key"] == "baseline"
    assert analysis["suggestions"]
    assert all("{{" not in item for item in analysis["suggestions"])
    assert "terminal_assets_p50" in analysis["metric_order"]
    assert analysis["facts"]["what_if"]

    fetched = client.get(f"/api/analysis/{analysis['analysis_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["analysis_id"] == analysis["analysis_id"]

    missing = client.get("/api/analysis/does-not-exist")
    assert missing.status_code == 404


def test_simple_analysis_has_monthly_and_initial_variants():
    run = create_simple_run()
    response = client.post(
        "/api/analysis", json={"mode": "simple", "run_id": run["run_id"]}
    )
    assert response.status_code == 200, response.text
    analysis = response.json()
    keys = {variant["key"] for variant in analysis["variants"]}
    assert {"baseline", "monthly_up", "initial_up"}.issubset(keys)
    assert analysis["suggestions"]
    assert all("{{" not in item for item in analysis["suggestions"])


def test_simple_analysis_without_goal_uses_downside_metric():
    response = client.post(
        "/api/simple",
        json={
            "name": "简版无目标",
            "initial_capital": 50_000,
            "monthly_contribution": 3_000,
            "horizon_years": 8,
            "weights": {"csi300": 0.6, "bond": 0.4},
            "goal_amount": 0,
            "calibration_window": "10y",
            "n_paths": 200,
            "seed": 3,
        },
    )
    assert response.status_code == 200, response.text
    analysis = client.post(
        "/api/analysis",
        json={"mode": "simple", "run_id": response.json()["run_id"]},
    )
    assert analysis.status_code == 200, analysis.text
    body = analysis.json()
    assert "terminal_assets_p5" in body["metric_order"]
    assert "ruin_probability" not in body["metric_order"]
    assert body["suggestions"]
    assert all("{{" not in item for item in body["suggestions"])


def test_negated_promise_and_recommendation_are_allowed():
    metric_map = {"terminal_assets_p50": "100万元"}
    payload = {
        "summary": "当前期末资产约为{{terminal_assets_p50}}；本内容不构成任何收益承诺，也不推荐具体产品。",
        "findings": ["这是基准结果。", "局部对比见下表。"],
        "suggestions": ["可以评估延长年限。", "也可以评估提高每月投入。"],
        "caveats": ["这是假设推演。", "不构成投资建议。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    validated = validate_analysis_payload(payload, metric_map)
    assert "不构成任何收益承诺" in validated.summary
    assert "不推荐具体产品" in validated.summary


def test_history_analysis_template():
    backtest = client.post(
        "/api/history/backtest",
        json={
            "mode": "single",
            "asset": "gold",
            "initial_capital": 100_000,
            "monthly_contribution": 5_000,
            "lookback_years": 10,
        },
    )
    assert backtest.status_code == 200, backtest.text
    history = backtest.json()
    response = client.post(
        "/api/analysis", json={"mode": "history", "run_id": history["run_id"]}
    )
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["source"] == "template"
    assert analysis["variants"][0]["key"] == "baseline"
    assert "terminal_value" in analysis["metric_order"]
    assert "max_drawdown" in analysis["metric_order"]
    assert any(
        variant["key"] == "start_earlier" for variant in analysis["variants"]
    )
    assert analysis["suggestions"]
    assert all("{{" not in item for item in analysis["suggestions"])


def test_analysis_payload_requires_whatif_reference():
    metric_map = {
        "terminal_assets_p50": "100万元",
        "whatif_monthly_up_label": "每月投入 +10%",
        "whatif_monthly_up_delta_terminal_assets_p50": "+5万元",
    }
    payload = {
        "summary": "当前方案期末资产约为{{terminal_assets_p50}}。",
        "findings": [
            "这是基准结果。",
            "局部对比见下表。",
        ],
        "suggestions": [
            "可以考虑{{whatif_monthly_up_label}}，期末资产变化"
            "{{whatif_monthly_up_delta_terminal_assets_p50}}。",
            "调整前先确认每月现金流是否可持续。",
        ],
        "caveats": ["这是假设推演。", "不构成投资建议。"],
        "metric_refs": [
            "terminal_assets_p50",
            "whatif_monthly_up_label",
            "whatif_monthly_up_delta_terminal_assets_p50",
        ],
    }
    validated = validate_analysis_payload(
        payload, metric_map, require_whatif=True
    )
    assert "+5万元" in validated.suggestions[0]

    generic = {
        **payload,
        "suggestions": ["建议提高每月投入。", "建议延长投资年限。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    with pytest.raises(advice.LLMValidationError):
        validate_analysis_payload(generic, metric_map, require_whatif=True)

    raw_number = {
        **payload,
        "suggestions": ["可以考虑提高每月投入10%。", "建议延长投资年限。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    with pytest.raises(advice.LLMValidationError):
        validate_analysis_payload(raw_number, metric_map, require_whatif=False)


def test_analysis_llm_success_and_fallback(monkeypatch):
    run = create_full_run()

    payload = {
        "summary": "当前方案的期末资产约为{{terminal_assets_p50}}。",
        "findings": [
            "最大回撤中位数约为{{max_drawdown_p50}}。",
            "延长年限后的期末资产变化为"
            "{{whatif_horizon_up_delta_terminal_assets_p50}}。",
        ],
        "suggestions": [
            "可以考虑{{whatif_horizon_up_label}}：期末资产中位数变化"
            "{{whatif_horizon_up_delta_terminal_assets_p50}}，"
            "最大回撤变化{{whatif_horizon_up_delta_max_drawdown_p50}}。",
            "在调整前先确认现金流和应急金是否充足。",
        ],
        "caveats": ["这是假设推演，不是预测。", "不构成投资建议。"],
        "metric_refs": [
            "terminal_assets_p50",
            "max_drawdown_p50",
            "whatif_horizon_up_delta_terminal_assets_p50",
            "whatif_horizon_up_label",
            "whatif_horizon_up_delta_max_drawdown_p50",
        ],
    }

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "test-model")
    monkeypatch.setattr(
        advice,
        "_call_llm",
        lambda *args, **kwargs: json.dumps(payload, ensure_ascii=False),
    )

    response = client.post(
        "/api/analysis", json={"mode": "full", "run_id": run["run_id"]}
    )
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["source"] == "llm"
    assert analysis["model"] == "test-model"
    assert analysis["suggestions"]
    assert all("{{" not in item for item in analysis["suggestions"])
    assert analysis["warnings"] == []

    monkeypatch.setattr(
        advice,
        "_call_llm",
        lambda *args, **kwargs: '{"summary": "直接写123万元", "findings": [],'
        ' "suggestions": [], "caveats": [], "metric_refs": []}',
    )
    fallback = client.post(
        "/api/analysis",
        json={"mode": "full", "run_id": run["run_id"], "force": True},
    )
    assert fallback.status_code == 200, fallback.text
    body = fallback.json()
    assert body["source"] == "template"
    assert body["warnings"]
