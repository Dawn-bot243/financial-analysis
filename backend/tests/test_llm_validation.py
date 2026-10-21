import pytest

from backend.app.core.engine import run_simulation
from backend.app.core.explain import (
    LLMValidationError,
    build_metric_context,
    explain_run,
    template_explanation,
    validate_llm_payload,
)
from backend.app.core.metrics import build_metrics
from backend.app.defaults import default_request


@pytest.fixture(scope="module")
def sample():
    request = default_request().model_copy(
        update={"n_paths": 200, "horizon_years": 10, "include_explanation": False}
    )
    metrics = build_metrics(request, run_simulation(request))
    metric_map, _ = build_metric_context(request, metrics)
    return request, metrics, metric_map


def test_template_explanation_renders_all_placeholders(sample):
    request, metrics, metric_map = sample
    explanation = template_explanation(request, metrics)
    assert explanation.source == "template"
    assert explanation.metric_refs
    assert "{{" not in explanation.summary
    assert "{{" not in " ".join(explanation.bullets)
    assert any(key.startswith("event_") for key in explanation.metric_refs)
    assert "terminal_assets_p50" in metric_map


def test_valid_llm_payload_is_rendered(sample):
    _request, _metrics, metric_map = sample
    payload = {
        "summary": "期末金融资产中位数约为{{terminal_assets_p50}}，这是假设推演。",
        "bullets": [
            "未来{{horizon_years}}内，所有事件同时通过的概率约为{{joint_success_probability}}。",
            "最大回撤中位数约为{{max_drawdown_p50}}。",
        ],
        "caveats": ["收益与波动是假设，不是预测。"],
        "metric_refs": [
            "terminal_assets_p50",
            "horizon_years",
            "joint_success_probability",
            "max_drawdown_p50",
        ],
    }
    validated = validate_llm_payload(payload, metric_map)
    assert "{{" not in validated.summary
    assert "万元" in validated.summary or "元" in validated.summary
    assert validated.metric_refs == sorted(payload["metric_refs"])


@pytest.mark.parametrize(
    "text",
    [
        "期末资产约为123万元。",
        "通过率约为50%。",
        "未来十年内结果可能不同。",
        "大约百分之五的路径会失败。",
    ],
)
def test_raw_numbers_are_rejected(sample, text):
    _request, _metrics, metric_map = sample
    payload = {
        "summary": text,
        "bullets": ["{{terminal_assets_p50}}"],
        "caveats": ["这是假设。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    with pytest.raises(LLMValidationError):
        validate_llm_payload(payload, metric_map)


def test_unknown_placeholder_is_rejected(sample):
    _request, _metrics, metric_map = sample
    payload = {
        "summary": "约为{{not_a_real_key}}。",
        "bullets": ["{{terminal_assets_p50}}"],
        "caveats": ["这是假设。"],
        "metric_refs": ["not_a_real_key", "terminal_assets_p50"],
    }
    with pytest.raises(LLMValidationError):
        validate_llm_payload(payload, metric_map)


def test_metric_refs_must_match_used_placeholders(sample):
    _request, _metrics, metric_map = sample
    payload = {
        "summary": "约为{{terminal_assets_p50}}。",
        "bullets": ["{{horizon_years}}"],
        "caveats": ["这是假设。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    with pytest.raises(LLMValidationError):
        validate_llm_payload(payload, metric_map)


def test_proper_names_with_digits_are_allowed(sample):
    _request, _metrics, metric_map = sample
    payload = {
        "summary": "纳斯达克100的期末资产中位数约为{{terminal_assets_p50}}。",
        "bullets": ["{{terminal_assets_p50}}"],
        "caveats": ["这是假设。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    with pytest.raises(LLMValidationError):
        validate_llm_payload(payload, metric_map)
    validated = validate_llm_payload(
        payload, metric_map, {"纳斯达克100"}
    )
    assert "纳斯达克100" in validated.summary


def test_window_placeholders_are_available_and_render(sample):
    _request, _metrics, metric_map = sample
    assert "event_0_window" in metric_map
    assert "event_0_median_action_age" in metric_map
    assert "event_0_natural_success_probability" in metric_map
    payload = {
        "summary": "购车窗口为{{event_0_window}}，完成时点中位数约为{{event_0_median_action_age}}。",
        "bullets": ["窗口内完成概率约为{{event_0_natural_success_probability}}。"],
        "caveats": ["这是假设。"],
        "metric_refs": [
            "event_0_window",
            "event_0_median_action_age",
            "event_0_natural_success_probability",
        ],
    }
    validated = validate_llm_payload(payload, metric_map, {"购车"})
    assert "33–36岁" in validated.summary
    assert "{{" not in validated.summary


def test_advice_language_is_rejected(sample):
    _request, _metrics, metric_map = sample
    payload = {
        "summary": "建议买入高权益组合。",
        "bullets": ["{{terminal_assets_p50}}"],
        "caveats": ["这是假设。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    with pytest.raises(LLMValidationError):
        validate_llm_payload(payload, metric_map)


def test_guarantee_promise_is_rejected_but_negation_is_allowed(sample):
    _request, _metrics, metric_map = sample
    promise = {
        "summary": "本组合保证收益。",
        "bullets": ["{{terminal_assets_p50}}"],
        "caveats": ["这是假设。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    with pytest.raises(LLMValidationError):
        validate_llm_payload(promise, metric_map)

    caveat = {
        "summary": "本工具不保证收益，只是情景推演。",
        "bullets": ["{{terminal_assets_p50}}"],
        "caveats": ["这是假设。"],
        "metric_refs": ["terminal_assets_p50"],
    }
    validated = validate_llm_payload(caveat, metric_map)
    assert "不保证收益" in validated.summary


def test_explain_run_falls_back_to_template_without_key(sample):
    request, metrics, _metric_map = sample
    request = request.model_copy(update={"include_explanation": True})

    class NoLLM:
        llm_enabled = False
        llm_api_key = ""
        llm_model = "test"
        llm_base_url = "http://127.0.0.1:9"
        llm_timeout_seconds = 1.0

    explanation, warnings = explain_run(request, metrics, NoLLM())
    assert explanation.source == "template"
    assert warnings
