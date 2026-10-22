"""On-demand LLM analysis and advice for a completed run.

The LLM never runs the model and never invents a number. The backend first
computes a small set of one-lever-at-a-time what-if variants, then passes the
actual baseline and variant results to the LLM. The LLM writes only prose; any
number in that prose must be a placeholder that the backend fills from the
computed facts. The same response also carries the structured variant table so
the UI can show the evidence behind each suggestion.

This is deliberately a local sensitivity analysis, not a global optimisation:
each variant changes one assumption and keeps everything else fixed.
"""

from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Literal

from ..models import (
    AnalysisMetric,
    AnalysisResponse,
    HistoryRequest,
    HistoryResponse,
    RunMetrics,
    RunResponse,
    ScenarioRequest,
    WhatIfVariant,
)
from .engine import run_simulation
from .explain import (
    LLMValidationError,
    _allowed_literals,
    _call_llm,
    _check_no_raw_numbers,
    _parse_json_object,
    build_metric_context,
    extract_placeholders,
    format_money,
    format_pct,
    render_placeholders,
    sanitize_error,
)
from .history import HistoryData, load_history_data, run_history_backtest
from .metrics import build_metrics
from .snapshot import canonical_json, sha256_hex

ADVICE_VERSION = "analysis-v1"

ADVICE_SYSTEM_PROMPT = """你是家庭财务情景分析助手，不是持牌投资顾问。
你可以解读推演结果，并给出情景层面的调整建议；但不能推荐具体基金、ETF、股票、平台或产品，
不能给出买卖时点，不能承诺收益，也不能声称某个方案是全局最优。

规则：
1. 只输出一个 JSON 对象，字段为 summary（字符串）、findings（字符串数组）、
   suggestions（字符串数组）、caveats（字符串数组）、metric_refs（字符串数组）。
2. summary 一句话概括当前结果；findings 2-4 条解读基准结果和主要风险；
   suggestions 2-4 条可执行的情景调整方向；caveats 2-4 条说明假设和边界。
3. 任何数值、金额、百分比、年月都必须写成 {{key}} 占位符，key 必须来自给定的占位符列表。
   文本中不得出现阿拉伯数字、百分号、小数，也不得用“十年”“八成”“百分之五”等数量表述。
   专有名词中的数字（例如纳斯达克100）可以使用。
4. 每条建议必须引用至少一个 what-if 占位符作为依据，说明调整后的结果变化和代价；
   如果本次没有可比较的 what-if，则引用基准指标，并明确说明没有可比较的局部调整。
5. 建议只能调整情景参数：储蓄率、每月投入、年限、资产类别权重、应急金、再平衡规则等。
   不要推荐具体产品、平台、基金、ETF、股票，不要给买卖时点，不要承诺收益。
6. 不要使用“买入”“卖出”“推荐”“加仓”“减仓”“清仓”“满仓”“梭哈”“抄底”
   “稳赚”“必涨”等措辞。
7. 语气克制，强调这是假设推演，不是预测；建议不是投资建议。
8. 不要输出 Markdown 代码围栏或 JSON 之外的任何文字。"""


class SkipVariant(Exception):
    """The one-lever change is not applicable to this run."""


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    kind: Literal["money", "pct"]
    higher_is_better: bool


@dataclass
class VariantPlan:
    key: str
    label: str
    description: str
    mutate: Callable[[], tuple[Any, dict[str, Any]]]


@dataclass
class VariantResult:
    key: str
    label: str
    description: str
    changes: dict[str, Any]
    values: dict[str, float]
    warnings: list[str]


@dataclass
class ValidatedAnalysis:
    summary: str
    findings: list[str]
    suggestions: list[str]
    caveats: list[str]
    metric_refs: list[str]
    templates: dict


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_metric(value: float, kind: Literal["money", "pct"]) -> str:
    return format_money(value) if kind == "money" else format_pct(value)


def _format_delta(value: float, kind: Literal["money", "pct"]) -> str:
    if kind == "money":
        if abs(value) < 0.5:
            return "持平"
        return ("+" if value > 0 else "-") + format_money(abs(value))
    # Treat differences that round to 0.0 percentage points as flat, so the
    # table does not show "+0.0个百分点" with a better/worse tag.
    if abs(value) * 100.0 < 0.05:
        return "持平"
    return f"{value * 100:+.1f}个百分点"


def _is_zero_delta(value: float, kind: Literal["money", "pct"]) -> bool:
    return abs(value) < (0.5 if kind == "money" else 5e-4)


def _better(value: float, kind: Literal["money", "pct"], higher_is_better: bool) -> str:
    if _is_zero_delta(value, kind):
        return "neutral"
    return "better" if (value > 0) == higher_is_better else "worse"


# ---------------------------------------------------------------------------
# Baseline extraction
# ---------------------------------------------------------------------------


def _simulation_values(metrics: RunMetrics) -> dict[str, float]:
    return {
        "terminal_assets_p50": float(metrics.terminal_assets.p50),
        "terminal_assets_p5": float(metrics.terminal_assets.p5),
        "terminal_assets_p95": float(metrics.terminal_assets.p95),
        "annualized_twr_p50": float(metrics.annualized_twr.p50),
        "max_drawdown_p50": float(metrics.max_drawdown.p50),
        "max_drawdown_p95": float(metrics.max_drawdown.p95),
        "goal_probability": float(metrics.goal_probability),
        "joint_success_probability": float(1.0 - metrics.joint_shortfall_probability),
        "ruin_probability": float(metrics.ruin_probability),
        "total_contributions": float(metrics.total_contributions),
    }


def _history_values(response: HistoryResponse) -> dict[str, float]:
    values = {
        "terminal_value": float(response.terminal_value),
        "total_invested": float(response.total_invested),
        "profit": float(response.profit),
        "return_on_invested": float(response.return_on_invested),
        "max_drawdown": float(response.max_drawdown),
    }
    if response.irr_annual is not None:
        values["irr_annual"] = float(response.irr_annual)
    return values


def _simulation_metric_specs(
    mode: Literal["simple", "full"], request: ScenarioRequest, metrics: RunMetrics
) -> list[MetricSpec]:
    specs = [
        MetricSpec("terminal_assets_p50", "期末资产中位数", "money", True),
        MetricSpec("annualized_twr_p50", "年化 TWR 中位数", "pct", True),
        MetricSpec("max_drawdown_p50", "最大回撤中位数", "pct", False),
    ]
    if request.goal_amount > 0.0:
        specs.append(MetricSpec("goal_probability", "目标达成概率", "pct", True))
    elif mode == "simple":
        specs.append(MetricSpec("terminal_assets_p5", "期末资产 5 分位", "money", True))
    elif any(event.has_goal for event in metrics.events):
        specs.append(
            MetricSpec("joint_success_probability", "目标事件同时通过率", "pct", True)
        )
    else:
        specs.append(MetricSpec("ruin_probability", "曾耗尽金融资产概率", "pct", False))
    return specs


def _history_metric_specs(values: dict[str, float]) -> list[MetricSpec]:
    specs = [
        MetricSpec("terminal_value", "期末总资产", "money", True),
        MetricSpec("irr_annual", "实际年化 IRR", "pct", True),
        MetricSpec("max_drawdown", "最大回撤", "pct", False),
        MetricSpec("return_on_invested", "累计收益率", "pct", True),
    ]
    return [spec for spec in specs if spec.key in values]


def _metrics_for_values(
    values: dict[str, float],
    baseline: dict[str, float],
    specs: list[MetricSpec],
    with_delta: bool,
) -> list[AnalysisMetric]:
    result: list[AnalysisMetric] = []
    for spec in specs:
        if spec.key not in values:
            continue
        value = values[spec.key]
        delta = value - baseline.get(spec.key, value) if with_delta else None
        result.append(
            AnalysisMetric(
                key=spec.key,
                label=spec.label,
                value=value,
                formatted=_format_metric(value, spec.kind),
                delta=delta,
                delta_formatted=(
                    _format_delta(delta, spec.kind) if delta is not None else None
                ),
                better=(
                    _better(delta, spec.kind, spec.higher_is_better)
                    if delta is not None
                    else "neutral"
                ),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Simulation variants
# ---------------------------------------------------------------------------


def _validated_simulation(request: ScenarioRequest) -> ScenarioRequest:
    return ScenarioRequest.model_validate(request.model_dump())


def _copy_simulation(request: ScenarioRequest) -> ScenarioRequest:
    return request.model_copy(deep=True)


def _growth_assets(request: ScenarioRequest) -> set[str]:
    return {asset.name for asset in request.market.assets if asset.role == "growth"}


def _can_adjust_growth(request: ScenarioRequest, delta: float) -> bool:
    strategy = request.strategy
    if strategy.kind == "constant":
        weights = strategy.weights or {}
        growth = _growth_assets(request)
        if not growth:
            return False
        growth_total = sum(float(weights.get(name, 0.0)) for name in growth)
        target = growth_total + delta
        if target < -1e-9 or target > 1.0 + 1e-9:
            return False
        if delta > 0 and growth_total <= 1e-9:
            return bool(growth)
        if delta < 0 and growth_total >= 1.0 - 1e-9:
            return False
        return abs(target - growth_total) > 1e-9
    if strategy.kind == "glide":
        new_start = min(max(strategy.growth_start + delta, strategy.floor), strategy.cap)
        new_end = min(max(strategy.growth_end + delta, strategy.floor), strategy.cap)
        return (
            abs(new_start - strategy.growth_start) > 1e-9
            or abs(new_end - strategy.growth_end) > 1e-9
        )
    return False


def _mutate_growth(
    request: ScenarioRequest, delta: float
) -> tuple[ScenarioRequest, dict[str, Any]]:
    variant = _copy_simulation(request)
    strategy = variant.strategy
    if strategy.kind == "constant":
        weights = {
            asset.name: float((strategy.weights or {}).get(asset.name, 0.0))
            for asset in variant.market.assets
        }
        growth = _growth_assets(variant)
        if not growth:
            raise SkipVariant
        growth_total = sum(weights[name] for name in growth)
        non_growth = set(weights) - growth
        non_total = sum(weights[name] for name in non_growth)
        target = growth_total + delta
        if target < -1e-9 or target > 1.0 + 1e-9:
            raise SkipVariant
        if delta > 0 and growth_total <= 1e-9:
            each = target / len(growth)
            for name in growth:
                weights[name] = each
        elif delta < 0 and growth_total >= 1.0 - 1e-9:
            raise SkipVariant
        else:
            growth_scale = target / growth_total
            for name in growth:
                weights[name] *= growth_scale
        if non_growth:
            non_target = 1.0 - target
            if non_total <= 1e-9:
                each = non_target / len(non_growth)
                for name in non_growth:
                    weights[name] = each
            else:
                non_scale = non_target / non_total
                for name in non_growth:
                    weights[name] *= non_scale
        strategy.weights = weights
        changes = {"strategy": "constant", "weights": weights}
    elif strategy.kind == "glide":
        new_start = min(max(strategy.growth_start + delta, strategy.floor), strategy.cap)
        new_end = min(max(strategy.growth_end + delta, strategy.floor), strategy.cap)
        if (
            abs(new_start - strategy.growth_start) <= 1e-9
            and abs(new_end - strategy.growth_end) <= 1e-9
        ):
            raise SkipVariant
        strategy.growth_start = new_start
        strategy.growth_end = new_end
        changes = {
            "strategy": "glide",
            "growth_start": new_start,
            "growth_end": new_end,
        }
    else:
        raise SkipVariant
    return _validated_simulation(variant), changes


def _mutate_simulation_horizon(
    request: ScenarioRequest,
) -> tuple[ScenarioRequest, dict[str, Any]]:
    if request.horizon_years >= 50:
        raise SkipVariant
    variant = _copy_simulation(request)
    variant.horizon_years = min(50, variant.horizon_years + 2)
    return _validated_simulation(variant), {
        "horizon_years": variant.horizon_years
    }


def _mutate_simulation_expense(
    request: ScenarioRequest,
) -> tuple[ScenarioRequest, dict[str, Any]]:
    if request.household.monthly_expense <= 0.0:
        raise SkipVariant
    variant = _copy_simulation(request)
    variant.household.monthly_expense *= 0.9
    return _validated_simulation(variant), {
        "monthly_expense": variant.household.monthly_expense
    }


def _mutate_simulation_monthly(
    request: ScenarioRequest, amount: float
) -> tuple[ScenarioRequest, dict[str, Any]]:
    if amount <= 0.0:
        raise SkipVariant
    variant = _copy_simulation(request)
    variant.household.monthly_income += amount
    return _validated_simulation(variant), {
        "monthly_income": variant.household.monthly_income,
        "monthly_income_increase": amount,
    }


def _mutate_simulation_initial(
    request: ScenarioRequest,
) -> tuple[ScenarioRequest, dict[str, Any]]:
    variant = _copy_simulation(request)
    changed = False
    if variant.household.holdings:
        for holding in variant.household.holdings:
            if holding.liquidity == "liquid":
                holding.value *= 1.1
                changed = True
    if not changed and variant.household.initial_capital > 0.0:
        variant.household.initial_capital *= 1.1
        changed = True
    if not changed:
        raise SkipVariant
    return _validated_simulation(variant), {"liquid_assets_multiplier": 1.1}


def _mutate_simulation_emergency(
    request: ScenarioRequest,
) -> tuple[ScenarioRequest, dict[str, Any]]:
    if request.household.emergency_fund_months >= 60.0:
        raise SkipVariant
    variant = _copy_simulation(request)
    variant.household.emergency_fund_months = min(
        60.0, variant.household.emergency_fund_months + 3.0
    )
    return _validated_simulation(variant), {
        "emergency_fund_months": variant.household.emergency_fund_months
    }


def _simulation_plans(
    mode: Literal["simple", "full"], request: ScenarioRequest, metrics: RunMetrics
) -> list[VariantPlan]:
    plans: list[VariantPlan] = []
    if mode == "simple":
        monthly = float(request.household.monthly_income)
        if monthly > 0.0:
            plans.append(
                VariantPlan(
                    "monthly_up",
                    "每月投入 +10%",
                    "每月投入提高一成，其他假设不变；用于观察持续投入对期末结果的影响。",
                    lambda: _mutate_simulation_monthly(request, monthly * 0.1),
                )
            )
    elif request.household.monthly_expense > 0.0:
        plans.append(
            VariantPlan(
                "expense_down",
                "每月支出 -10%",
                "每月支出降低一成，结余相应增加；不改变收入、负债和事件假设。",
                lambda: _mutate_simulation_expense(request),
            )
        )
    elif metrics.monthly_surplus > 0.0:
        plans.append(
            VariantPlan(
                "monthly_up",
                "每月结余 +10%",
                "每月结余提高一成，其他假设不变；用于观察持续投入对期末结果的影响。",
                lambda: _mutate_simulation_monthly(
                    request, metrics.monthly_surplus * 0.1
                ),
            )
        )

    horizon_delta = min(50, request.horizon_years + 2) - request.horizon_years
    if horizon_delta > 0:
        plans.append(
            VariantPlan(
                "horizon_up",
                f"投资年限 +{horizon_delta:g}年",
                "把推演年限延长两年（最多到上限），其他假设不变；"
                "用于观察更长时间是否改善结果。",
                lambda: _mutate_simulation_horizon(request),
            )
        )

    for delta, key, label in (
        (0.10, "growth_up", "成长资产 +10个百分点"),
        (-0.10, "growth_down", "成长资产 -10个百分点"),
    ):
        if _can_adjust_growth(request, delta):
            plans.append(
                VariantPlan(
                    key,
                    label,
                    "把成长资产的目标权重整体调整十个百分点，防御和现金资产按比例反向调整；"
                    "用于观察收益与回撤的取舍。",
                    lambda d=delta: _mutate_growth(request, d),
                )
            )

    if mode == "simple" and metrics.initial_capital > 0.0:
        plans.append(
            VariantPlan(
                "initial_up",
                "初始资金 +10%",
                "初始可投资资金增加一成；用于观察起点资金对期末结果的影响。",
                lambda: _mutate_simulation_initial(request),
            )
        )
    elif mode == "full":
        emergency_delta = min(
            60.0, request.household.emergency_fund_months + 3.0
        ) - request.household.emergency_fund_months
        if emergency_delta > 0.0:
            plans.append(
                VariantPlan(
                    "emergency_up",
                    f"应急金目标 +{emergency_delta:g}个月",
                    "把应急金目标提高三个月开销（最多到上限）；"
                    "可能降低可投资金额，但提高现金流韧性。",
                    lambda: _mutate_simulation_emergency(request),
                )
            )

    return plans[:5]


def _run_simulation_variants(
    request: ScenarioRequest, plans: list[VariantPlan]
) -> list[VariantResult]:
    results: list[VariantResult] = []
    for plan in plans:
        try:
            variant_request, changes = plan.mutate()
        except SkipVariant:
            continue
        simulation = run_simulation(variant_request)
        metrics = build_metrics(variant_request, simulation)
        results.append(
            VariantResult(
                key=plan.key,
                label=plan.label,
                description=plan.description,
                changes=changes,
                values=_simulation_values(metrics),
                warnings=simulation.warnings[:3],
            )
        )
    return results


# ---------------------------------------------------------------------------
# History variants
# ---------------------------------------------------------------------------


def _history_weights(request: HistoryRequest) -> dict[str, float]:
    if request.mode == "single":
        return {request.asset: 1.0}
    return {name: float(weight) for name, weight in request.weights.items()}


def _shift_date(value: date, years: int) -> date:
    new_year = value.year + years
    day = min(value.day, calendar.monthrange(new_year, value.month)[1])
    return date(new_year, value.month, day)


def _validated_history(request: HistoryRequest) -> HistoryRequest:
    return HistoryRequest.model_validate(request.model_dump())


def _copy_history(request: HistoryRequest) -> HistoryRequest:
    return request.model_copy(deep=True)


def _mutate_history_monthly(
    request: HistoryRequest,
) -> tuple[HistoryRequest, dict[str, Any]]:
    if request.monthly_contribution <= 0.0:
        raise SkipVariant
    variant = _copy_history(request)
    variant.monthly_contribution *= 1.1
    return _validated_history(variant), {
        "monthly_contribution": variant.monthly_contribution
    }


def _mutate_history_initial(
    request: HistoryRequest,
) -> tuple[HistoryRequest, dict[str, Any]]:
    if request.initial_capital <= 0.0:
        raise SkipVariant
    variant = _copy_history(request)
    variant.initial_capital *= 1.1
    return _validated_history(variant), {
        "initial_capital": variant.initial_capital
    }


def _mutate_history_start(
    request: HistoryRequest,
) -> tuple[HistoryRequest, dict[str, Any]]:
    variant = _copy_history(request)
    if variant.start_date is not None:
        variant.start_date = _shift_date(variant.start_date, -2)
        return _validated_history(variant), {
            "start_date": variant.start_date.isoformat()
        }
    lookback = float(variant.lookback_years or 10.0)
    new_lookback = min(50.0, lookback + 2.0)
    if new_lookback <= lookback + 1e-9:
        raise SkipVariant
    variant.lookback_years = new_lookback
    return _validated_history(variant), {"lookback_years": new_lookback}


def _mutate_history_rebalance(
    request: HistoryRequest,
) -> tuple[HistoryRequest, dict[str, Any]]:
    variant = _copy_history(request)
    variant.rebalance = "none" if variant.rebalance == "annual" else "annual"
    return _validated_history(variant), {"rebalance": variant.rebalance}


def _history_growth_weights(
    request: HistoryRequest, data: HistoryData, delta: float
) -> tuple[dict[str, float], dict[str, float]]:
    weights = _history_weights(request)
    if len(weights) <= 1:
        raise SkipVariant
    growth = {
        name for name in weights if data.assets[name].role == "growth"
    }
    if not growth:
        raise SkipVariant
    growth_total = sum(weights[name] for name in growth)
    non_growth = set(weights) - growth
    non_total = sum(weights[name] for name in non_growth)
    target = growth_total + delta
    if target < -1e-9 or target > 1.0 + 1e-9:
        raise SkipVariant
    if delta > 0 and growth_total <= 1e-9:
        each = target / len(growth)
        for name in growth:
            weights[name] = each
    elif delta < 0 and growth_total >= 1.0 - 1e-9:
        raise SkipVariant
    else:
        scale = target / growth_total
        for name in growth:
            weights[name] *= scale
    if non_growth:
        non_target = 1.0 - target
        if non_total <= 1e-9:
            each = non_target / len(non_growth)
            for name in non_growth:
                weights[name] = each
        else:
            scale = non_target / non_total
            for name in non_growth:
                weights[name] *= scale
    return weights, {"weights": weights}


def _mutate_history_growth(
    request: HistoryRequest, data: HistoryData, delta: float
) -> tuple[HistoryRequest, dict[str, Any]]:
    weights, changes = _history_growth_weights(request, data, delta)
    variant = _copy_history(request)
    variant.mode = "portfolio"
    variant.weights = weights
    return _validated_history(variant), changes


def _history_plans(
    request: HistoryRequest, data: HistoryData
) -> list[VariantPlan]:
    plans: list[VariantPlan] = []
    if request.monthly_contribution > 0.0:
        plans.append(
            VariantPlan(
                "monthly_up",
                "每月投入 +10%",
                "每月定投金额提高一成，其他假设不变。",
                lambda: _mutate_history_monthly(request),
            )
        )
    if request.initial_capital > 0.0:
        plans.append(
            VariantPlan(
                "initial_up",
                "初始资金 +10%",
                "初始投入增加一成，其他假设不变。",
                lambda: _mutate_history_initial(request),
            )
        )
    if request.start_date is not None:
        plans.append(
            VariantPlan(
                "start_earlier",
                "回测起点提前2年",
                "把回测起点提前两年，观察更长的历史区间；受各资产可用数据起点限制。",
                lambda: _mutate_history_start(request),
            )
        )
    else:
        lookback = float(request.lookback_years or 10.0)
        lookback_delta = min(50.0, lookback + 2.0) - lookback
        if lookback_delta > 0.0:
            plans.append(
                VariantPlan(
                    "start_earlier",
                    f"回测起点提前{lookback_delta:g}年",
                    "拉长回测区间，观察更长的历史区间；受各资产可用数据起点限制。",
                    lambda: _mutate_history_start(request),
                )
            )
    if request.mode == "portfolio":
        plans.append(
            VariantPlan(
                "rebalance_toggle",
                "取消年度再平衡" if request.rebalance == "annual" else "改为年度再平衡",
                "切换再平衡规则，其他假设不变；用于观察再平衡对路径和回撤的影响。",
                lambda: _mutate_history_rebalance(request),
            )
        )
        for delta, key, label in (
            (0.10, "growth_up", "成长资产 +10个百分点"),
            (-0.10, "growth_down", "成长资产 -10个百分点"),
        ):
            try:
                _history_growth_weights(request, data, delta)
            except SkipVariant:
                continue
            plans.append(
                VariantPlan(
                    key,
                    label,
                    "把成长资产权重整体调整十个百分点，防御资产按比例反向调整。",
                    lambda d=delta: _mutate_history_growth(request, data, d),
                )
            )
    return plans[:6]


def _run_history_variants(
    request: HistoryRequest,
    baseline: HistoryResponse,
    data: HistoryData,
    plans: list[VariantPlan],
) -> list[VariantResult]:
    results: list[VariantResult] = []
    for plan in plans:
        try:
            variant_request, changes = plan.mutate()
        except SkipVariant:
            continue
        result = run_history_backtest(variant_request, data)
        if (
            plan.key == "start_earlier"
            and result.effective_start_date == baseline.effective_start_date
        ):
            continue
        values = {
            "terminal_value": float(result.terminal_value),
            "total_invested": float(result.total_invested),
            "profit": float(result.profit),
            "return_on_invested": float(result.return_on_invested),
            "max_drawdown": float(result.max_drawdown),
        }
        if result.irr_annual is not None:
            values["irr_annual"] = float(result.irr_annual)
        results.append(
            VariantResult(
                key=plan.key,
                label=plan.label,
                description=plan.description,
                changes=changes,
                values=values,
                warnings=result.warnings[:3],
            )
        )
    return results


# ---------------------------------------------------------------------------
# Facts, placeholders and prompt
# ---------------------------------------------------------------------------


def _simulation_facts(
    mode: Literal["simple", "full"],
    request: ScenarioRequest,
    metrics: RunMetrics,
    results: list[VariantResult],
) -> dict[str, Any]:
    facts = {
        "mode": mode,
        "note": "所有金额为今日购买力；收益率为实际几何年化收益。",
        "baseline": {
            "name": request.name,
            "horizon_years": request.horizon_years,
            "n_paths": request.n_paths,
            "seed": request.seed,
            "initial_capital": metrics.initial_capital,
            "monthly_income": request.household.monthly_income,
            "monthly_expense": request.household.monthly_expense,
            "monthly_surplus": metrics.monthly_surplus,
            "monthly_debt_payment": metrics.monthly_debt_payment,
            "goal_amount": request.goal_amount,
            "goal_probability": metrics.goal_probability,
            "terminal_assets": metrics.terminal_assets.model_dump(),
            "terminal_net_worth": metrics.terminal_net_worth.model_dump(),
            "max_drawdown": metrics.max_drawdown.model_dump(),
            "annualized_twr": metrics.annualized_twr.model_dump(),
            "joint_success_probability": 1.0 - metrics.joint_shortfall_probability,
            "ruin_probability": metrics.ruin_probability,
            "total_contributions": metrics.total_contributions,
            "strategy": request.strategy.model_dump(mode="json"),
            "events": [
                {
                    "name": event.name,
                    "age": event.age,
                    "amount": event.amount,
                    "success_probability": event.success_probability,
                    "has_goal": event.has_goal,
                    "window_years": event.window_years,
                    "natural_success_probability": event.natural_success_probability,
                    "deadline_success_probability": event.deadline_success_probability,
                    "failure_probability": event.failure_probability,
                }
                for event in metrics.events
            ],
        },
        "what_if": [
            {
                "key": result.key,
                "label": result.label,
                "description": result.description,
                "changes": result.changes,
                "metrics": result.values,
                "warnings": result.warnings,
            }
            for result in results
        ],
        "model_notes": [
            "每次 what-if 只改变一个参数，其他假设保持不变，不是全局最优搜索。",
            "收益、波动、相关性和现金流均为用户假设，不是预测。",
            "未建模失业、降薪、税费和交易成本；资产收益未扣产品费率。",
        ],
    }
    if mode == "simple":
        for key in (
            "monthly_expense",
            "monthly_debt_payment",
            "joint_success_probability",
            "ruin_probability",
            "events",
            "strategy",
        ):
            facts["baseline"].pop(key, None)
        facts["baseline"]["weights"] = request.strategy.weights
        facts["baseline"]["rebalance"] = "annual（固定，简版不可调整）"
        facts["simple_mode_note"] = (
            "简版只包含初始资金、每月投入、资产权重和年限；"
            "再平衡固定为年度再平衡，不包含应急金、负债、人生事件，"
            "也没有单独的现金仓管理。建议只围绕初始资金、每月投入、年限和"
            "资产权重，不要建议设置应急金、调整负债或改变再平衡规则。"
        )
    return facts


def _history_facts(
    request: HistoryRequest,
    response: HistoryResponse,
    data: HistoryData,
    results: list[VariantResult],
) -> dict[str, Any]:
    return {
        "mode": "history",
        "note": "历史回测为已实现路径，不是未来预测；金额为今日购买力。",
        "baseline": {
            "request_mode": request.mode,
            "asset": request.asset if request.mode == "single" else None,
            "weights": request.weights if request.mode == "portfolio" else None,
            "requested_start_date": request.start_date.isoformat()
            if request.start_date
            else None,
            "requested_end_date": request.end_date.isoformat()
            if request.end_date
            else None,
            "lookback_years": request.lookback_years,
            "rebalance": request.rebalance,
            "effective_start_date": response.effective_start_date.isoformat(),
            "effective_end_date": response.effective_end_date.isoformat(),
            "months": response.months,
            "contribution_count": response.contribution_count,
            "initial_capital": response.initial_capital,
            "monthly_contribution": response.monthly_contribution,
            "total_invested": response.total_invested,
            "terminal_value": response.terminal_value,
            "profit": response.profit,
            "return_on_invested": response.return_on_invested,
            "irr_annual": response.irr_annual,
            "max_drawdown": response.max_drawdown,
            "drawdown_peak_date": response.drawdown_peak_date.isoformat()
            if response.drawdown_peak_date
            else None,
            "drawdown_trough_date": response.drawdown_trough_date.isoformat()
            if response.drawdown_trough_date
            else None,
            "final_composition": [
                item.model_dump(mode="json") for item in response.final_composition
            ],
            "data_note": data.source_note,
        },
        "what_if": [
            {
                "key": result.key,
                "label": result.label,
                "description": result.description,
                "changes": result.changes,
                "metrics": result.values,
                "warnings": result.warnings,
            }
            for result in results
        ],
        "model_notes": [
            "每次 what-if 只改变一个参数，其他假设保持不变，不是全局最优搜索。",
            "历史收益是特定区间的实现值，不代表未来。",
            "未计交易费用、税费和产品费率。",
        ],
        "history_mode_note": (
            "历史定投页只包含初始资金、每月投入、回测区间、资产权重和再平衡规则；"
            "不包含应急金、负债、人生事件。建议只围绕这些已建模参数，"
            "不要建议设置应急金、调整负债或规划人生事件。"
        ),
    }


def _history_label(
    request: HistoryRequest, response: HistoryResponse, data: HistoryData
) -> str:
    if request.mode == "single":
        asset = data.assets.get(request.asset)
        return asset.label if asset else request.asset
    labels = [
        data.assets[name].label
        for name in request.weights
        if name in data.assets and request.weights[name] > 0
    ]
    return " + ".join(labels) if labels else "多资产组合"


_EXTRA_VARIANT_METRICS: tuple[tuple[str, str, Literal["money", "pct"]], ...] = (
    ("total_contributions", "累计投入", "money"),
    ("total_invested", "累计投入", "money"),
    ("profit", "累计收益", "money"),
    ("terminal_assets_p5", "期末资产 5 分位", "money"),
    ("terminal_assets_p95", "期末资产 95 分位", "money"),
    ("max_drawdown_p95", "最大回撤 95 分位", "pct"),
    ("ruin_probability", "曾耗尽金融资产概率", "pct"),
    ("joint_success_probability", "目标事件同时通过率", "pct"),
)


def _add_variant_placeholders(
    metric_map: dict[str, str],
    descriptions: dict[str, str],
    baseline: dict[str, float],
    results: list[VariantResult],
    specs: list[MetricSpec],
) -> None:
    spec_keys = {spec.key for spec in specs}
    for result in results:
        prefix = f"whatif_{result.key}"
        metric_map[f"{prefix}_label"] = result.label
        metric_map[f"{prefix}_description"] = result.description
        descriptions[f"{prefix}_label"] = "what-if 情景名称"
        descriptions[f"{prefix}_description"] = "what-if 情景说明"
        for spec in specs:
            if spec.key not in result.values or spec.key not in baseline:
                continue
            value = result.values[spec.key]
            delta = value - baseline[spec.key]
            metric_map[f"{prefix}_{spec.key}"] = _format_metric(value, spec.kind)
            metric_map[f"{prefix}_delta_{spec.key}"] = _format_delta(delta, spec.kind)
            descriptions[f"{prefix}_{spec.key}"] = (
                f"{result.label}情景下的{spec.label}"
            )
            descriptions[f"{prefix}_delta_{spec.key}"] = (
                f"{result.label}情景相对当前方案的{spec.label}变化"
            )
        for key, label, kind in _EXTRA_VARIANT_METRICS:
            if key in spec_keys or key not in result.values or key not in baseline:
                continue
            value = result.values[key]
            delta = value - baseline[key]
            metric_map[f"{prefix}_{key}"] = _format_metric(value, kind)
            metric_map[f"{prefix}_delta_{key}"] = _format_delta(delta, kind)
            descriptions[f"{prefix}_{key}"] = f"{result.label}情景下的{label}"
            descriptions[f"{prefix}_delta_{key}"] = (
                f"{result.label}情景相对当前方案的{label}变化"
            )
    metric_map["whatif_count"] = f"{len(results)}组"
    descriptions["whatif_count"] = "局部 what-if 情景数量"


def _simulation_placeholders(
    mode: Literal["simple", "full"],
    request: ScenarioRequest,
    metrics: RunMetrics,
    baseline: dict[str, float],
    results: list[VariantResult],
    specs: list[MetricSpec],
) -> tuple[dict[str, str], dict[str, str]]:
    metric_map, descriptions = build_metric_context(request, metrics)
    metric_map["analysis_mode"] = "简版定投" if mode == "simple" else "完整情景"
    descriptions["analysis_mode"] = "分析页面类型"
    metric_map["monthly_contribution"] = format_money(
        float(request.household.monthly_income)
    )
    descriptions["monthly_contribution"] = "每月投入或每月收入"
    metric_map["goal_amount"] = (
        format_money(float(request.goal_amount))
        if request.goal_amount > 0.0
        else "未设置"
    )
    descriptions["goal_amount"] = "期末目标金额"
    metric_map["goal_probability"] = (
        format_pct(float(metrics.goal_probability))
        if request.goal_amount > 0.0
        else "未设置"
    )
    descriptions["goal_probability"] = "期末资产达到目标金额的概率"
    _add_variant_placeholders(metric_map, descriptions, baseline, results, specs)
    if mode == "simple":
        # The simple page has no emergency fund, liabilities or life events.
        # Keeping those placeholders would invite advice about controls the
        # user cannot set there.
        drop_exact = {
            "initial_emergency_fund",
            "terminal_emergency_fund_p50",
            "emergency_fund_target_months",
            "initial_illiquid_assets",
            "terminal_illiquid_assets_p50",
            "initial_liabilities",
            "terminal_liabilities_p50",
            "total_event_withdrawals",
            "total_debt_interest",
            "monthly_debt_payment",
            "joint_success_probability",
            "joint_shortfall_probability",
            "ruin_probability",
        }
        drop_fragments = (
            "emergency",
            "illiquid",
            "liabilit",
            "debt",
            "joint_",
            "ruin_",
            "_event_",
        )
        for key in list(metric_map):
            if key in drop_exact or key.startswith("event_") or any(
                fragment in key for fragment in drop_fragments
            ):
                metric_map.pop(key, None)
                descriptions.pop(key, None)
    return metric_map, descriptions


def _history_placeholders(
    request: HistoryRequest,
    response: HistoryResponse,
    data: HistoryData,
    baseline: dict[str, float],
    results: list[VariantResult],
    specs: list[MetricSpec],
) -> tuple[dict[str, str], dict[str, str]]:
    metric_map: dict[str, str] = {
        "analysis_mode": "历史定投",
        "history_label": _history_label(request, response, data),
        "history_start": response.effective_start_date.isoformat(),
        "history_end": response.effective_end_date.isoformat(),
        "history_months": f"{response.months}个月",
        "history_contribution_count": f"{response.contribution_count}次",
        "history_initial_capital": format_money(response.initial_capital),
        "history_monthly_contribution": format_money(response.monthly_contribution),
        "history_total_invested": format_money(response.total_invested),
        "history_terminal_value": format_money(response.terminal_value),
        "history_profit": format_money(response.profit),
        "history_return_on_invested": format_pct(response.return_on_invested),
        "history_irr_annual": (
            format_pct(response.irr_annual)
            if response.irr_annual is not None
            else "不适用"
        ),
        "history_max_drawdown": format_pct(response.max_drawdown),
        "history_peak_date": (
            response.drawdown_peak_date.isoformat()
            if response.drawdown_peak_date
            else "不适用"
        ),
        "history_trough_date": (
            response.drawdown_trough_date.isoformat()
            if response.drawdown_trough_date
            else "不适用"
        ),
        "history_rebalance": (
            "年度再平衡" if request.rebalance == "annual" else "不再平衡"
        ),
    }
    descriptions = {
        "analysis_mode": "分析页面类型",
        "history_label": "回测资产或组合名称",
        "history_start": "实际回测开始日期",
        "history_end": "实际回测结束日期",
        "history_months": "回测月数（含单位）",
        "history_contribution_count": "定投次数（含单位）",
        "history_initial_capital": "初始投入",
        "history_monthly_contribution": "每月定投金额",
        "history_total_invested": "累计投入",
        "history_terminal_value": "期末总资产",
        "history_profit": "累计收益",
        "history_return_on_invested": "累计收益率",
        "history_irr_annual": "实际年化货币加权收益率",
        "history_max_drawdown": "时间加权最大回撤",
        "history_peak_date": "回撤前高日期",
        "history_trough_date": "回撤低点日期",
        "history_rebalance": "再平衡规则",
    }
    _add_variant_placeholders(metric_map, descriptions, baseline, results, specs)
    return metric_map, descriptions


def _build_prompt(
    facts: dict[str, Any],
    metric_map: dict[str, str],
    descriptions: dict[str, str],
    results: list[VariantResult],
    mode: Literal["simple", "full", "history"],
) -> str:
    lines = [
        "基准结果和局部 what-if 结果（仅供理解，不要复制其中的数字）：",
        json.dumps(facts, ensure_ascii=False, indent=2),
        "",
        "可用占位符（key: 说明；当前值仅用于帮助你理解）：",
    ]
    for key, description in descriptions.items():
        lines.append(f"- {key}: {description}（当前值：{metric_map.get(key, '')}）")
    lines.extend(
        [
            "",
            "请输出严格 JSON，字段为 summary、findings、suggestions、caveats、metric_refs。",
            "summary 一句话概括；findings 2-4 条解读结果和风险；"
            "suggestions 2-4 条情景层面的调整方向；caveats 2-4 条说明模型边界。",
            "每条建议必须说明依据、可能的代价或风险，并引用至少一个 what-if 占位符；"
            "如果本次没有 what-if，则引用基准指标并说明没有可比较的局部调整。",
            "建议只能涉及储蓄率、每月投入、年限、资产类别权重、应急金、再平衡规则等情景参数。",
            "不要推荐具体基金、ETF、股票、平台或产品，不要给买卖时点，不要承诺收益，"
            "不要声称某个方案是全局最优。",
            "所有数值、金额、百分比、年月必须使用上面的 {{key}} 占位符；"
            "文本中不要出现阿拉伯数字、百分号、小数或“十年”“八成”“百分之五”等数量表述。"
            "专有名词中的数字可以使用。",
            "可以使用“提高”“降低”“延长”“增加”“减少”“评估”“考虑”等中性词。",
            "不要使用“买入”“卖出”“推荐”“加仓”“减仓”“清仓”“满仓”“梭哈”“抄底”"
            "“稳赚”“必涨”等措辞。",
        ]
    )
    if results:
        first = results[0]
        if mode == "history":
            example = (
                "示例：在{{whatif_"
                + first.key
                + "_label}}情景下，期末资产变化{{whatif_"
                + first.key
                + "_delta_terminal_value}}，最大回撤变化{{whatif_"
                + first.key
                + "_delta_max_drawdown}}。"
            )
        else:
            example = (
                "示例：在{{whatif_"
                + first.key
                + "_label}}情景下，期末资产中位数变化{{whatif_"
                + first.key
                + "_delta_terminal_assets_p50}}，最大回撤变化{{whatif_"
                + first.key
                + "_delta_max_drawdown_p50}}。"
            )
        lines.append(example)
    lines.append("metric_refs 必须列出你在 summary、findings、suggestions、caveats 中用到的全部 key。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _is_whatif_reference(key: str) -> bool:
    return key.startswith("whatif_") and (
        key.endswith("_label") or "_delta_" in key
    )


def validate_analysis_payload(
    payload: Any,
    metric_map: dict[str, str],
    allowed_literals: set[str] | None = None,
    require_whatif: bool = False,
) -> ValidatedAnalysis:
    if not isinstance(payload, dict):
        raise LLMValidationError("LLM 输出必须是 JSON 对象")
    summary = payload.get("summary")
    findings = payload.get("findings")
    suggestions = payload.get("suggestions")
    caveats = payload.get("caveats")
    metric_refs = payload.get("metric_refs")
    if not isinstance(summary, str) or not summary.strip():
        raise LLMValidationError("summary 必须是非空字符串")
    for name, values, low, high in (
        ("findings", findings, 2, 5),
        ("suggestions", suggestions, 2, 5),
        ("caveats", caveats, 2, 5),
    ):
        if (
            not isinstance(values, list)
            or not low <= len(values) <= high
            or not all(isinstance(item, str) and item.strip() for item in values)
        ):
            raise LLMValidationError(f"{name} 必须是 {low}-{high} 条非空字符串")
    if not isinstance(metric_refs, list) or not all(
        isinstance(item, str) for item in metric_refs
    ):
        raise LLMValidationError("metric_refs 必须是字符串数组")

    texts = [summary, *findings, *suggestions, *caveats]
    used: set[str] = set()
    for text in texts:
        _check_no_raw_numbers(text, allowed_literals)
        used.update(extract_placeholders(text))

    unknown = used - set(metric_map)
    if unknown:
        raise LLMValidationError(f"未知占位符：{sorted(unknown)}")
    if set(metric_refs) != used:
        raise LLMValidationError("metric_refs 必须与实际使用的占位符完全一致")

    if require_whatif:
        suggestion_refs: set[str] = set()
        for text in suggestions:
            suggestion_refs.update(extract_placeholders(text))
        if not any(_is_whatif_reference(key) for key in suggestion_refs):
            raise LLMValidationError("建议必须引用至少一个 what-if 占位符")

    return ValidatedAnalysis(
        summary=render_placeholders(summary, metric_map),
        findings=[render_placeholders(item, metric_map) for item in findings],
        suggestions=[render_placeholders(item, metric_map) for item in suggestions],
        caveats=[render_placeholders(item, metric_map) for item in caveats],
        metric_refs=sorted(used),
        templates={
            "summary": summary,
            "findings": findings,
            "suggestions": suggestions,
            "caveats": caveats,
        },
    )


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------


def _rank_variants(
    results: list[VariantResult],
    baseline: dict[str, float],
    mode: Literal["simple", "full", "history"],
) -> list[VariantResult]:
    key = "terminal_value" if mode == "history" else "terminal_assets_p50"
    return sorted(
        results,
        key=lambda result: result.values.get(key, 0.0)
        - baseline.get(key, 0.0),
        reverse=True,
    )


def _template_analysis(
    mode: Literal["simple", "full", "history"],
    request: ScenarioRequest | None,
    history: HistoryResponse | None,
    metrics: RunMetrics | None,
    baseline: dict[str, float],
    specs: list[MetricSpec],
    results: list[VariantResult],
    metric_map: dict[str, str],
) -> ValidatedAnalysis:
    ranked = _rank_variants(results, baseline, mode)
    summary: str
    findings: list[str]
    suggestions: list[str]

    if mode == "history":
        summary = (
            "在{{history_label}}的{{history_start}}到{{history_end}}区间，"
            "定投期末资产约为{{history_terminal_value}}，"
            "累计投入{{history_total_invested}}。"
        )
        findings = [
            "实际年化 IRR 约为{{history_irr_annual}}，最大回撤约为"
            "{{history_max_drawdown}}，累计收益率约为"
            "{{history_return_on_invested}}。",
            "区间共{{history_months}}、{{history_contribution_count}}投入；"
            "回撤从前高{{history_peak_date}}到低点{{history_trough_date}}。",
        ]
        suggestions = []
        for result in ranked[:3]:
            clauses = [
                "期末资产变化{{whatif_"
                + result.key
                + "_delta_terminal_value}}",
                "最大回撤变化{{whatif_"
                + result.key
                + "_delta_max_drawdown}}",
            ]
            if "irr_annual" in result.values and "irr_annual" in baseline:
                clauses.insert(
                    1,
                    "IRR变化{{whatif_"
                    + result.key
                    + "_delta_irr_annual}}",
                )
            suggestions.append(
                "可以评估{{whatif_"
                + result.key
                + "_label}}："
                + "，".join(clauses)
                + "。这只是单参数局部对比，需要同时看收益和回撤的取舍。"
            )
        if not suggestions:
            suggestions.append(
                "本次没有可比较的局部调整；优先复核目标金额、投入节奏和资产权重，"
                "再决定是否改变参数。"
            )
        caveats = [
            "历史回测是已实现路径，过去表现不代表未来。",
            "局部 what-if 一次只改变一个参数，其他假设不变，不代表全局最优。",
            "全部金额为今日购买力；未计税费、交易成本和产品费率。",
            "以上为情景推演，不构成投资建议。",
        ]
    else:
        summary = (
            "当前方案的期末资产中位数约为{{terminal_assets_p50}}，"
            "5%–95%分位约为{{terminal_assets_p5}}到{{terminal_assets_p95}}。"
        )
        findings = [
            "年化时间加权收益中位数约为{{annualized_twr_p50}}，"
            "最大回撤中位数约为{{max_drawdown_p50}}，"
            "95%分位约为{{max_drawdown_p95}}。",
        ]
        if request is not None and request.goal_amount > 0.0:
            findings.append(
                "目标金额为{{goal_amount}}，期末资产达到目标的概率约为"
                "{{goal_probability}}。"
            )
        elif metrics is not None and any(
            event.has_goal for event in metrics.events
        ):
            findings.append(
                "所有目标事件同时通过的概率约为{{joint_success_probability}}，"
                "曾耗尽金融资产的路径占比约为{{ruin_probability}}。"
            )
        elif "ruin_probability" in metric_map:
            findings.append(
                "曾耗尽金融资产的路径占比约为{{ruin_probability}}。"
            )
        else:
            findings.append(
                "期末资产的 5% 分位约为{{terminal_assets_p5}}，用于观察下行风险。"
            )
        suggestions = []
        for result in ranked[:3]:
            clauses = [
                "期末资产中位数变化{{whatif_"
                + result.key
                + "_delta_terminal_assets_p50}}",
                "最大回撤变化{{whatif_"
                + result.key
                + "_delta_max_drawdown_p50}}",
            ]
            suggestions.append(
                "可以评估{{whatif_"
                + result.key
                + "_label}}："
                + "，".join(clauses)
                + "。这只是单参数局部对比，需同时确认现金流和风险承受能力。"
            )
        if not suggestions:
            suggestions.append(
                "本次没有可比较的局部调整；优先复核每月结余、目标金额和应急金，"
                "再决定是否改变参数。"
            )
        caveats = [
            "收益、波动、相关性和现金流均为假设，不是预测。",
            "局部 what-if 一次只改变一个参数，其他假设不变，不代表全局最优。",
            "全部金额为今日购买力；未计税费、交易成本和产品费率。",
            "以上为情景推演，不构成投资建议。",
        ]

    if ranked:
        best = ranked[0]
        if mode == "history":
            findings.append(
                "在局部 what-if 中，{{whatif_"
                + best.key
                + "_label}}的期末资产为{{whatif_"
                + best.key
                + "_terminal_value}}，相对当前方案变化{{whatif_"
                + best.key
                + "_delta_terminal_value}}。"
            )
        else:
            findings.append(
                "在局部 what-if 中，{{whatif_"
                + best.key
                + "_label}}的期末资产中位数为{{whatif_"
                + best.key
                + "_terminal_assets_p50}}，相对当前方案变化{{whatif_"
                + best.key
                + "_delta_terminal_assets_p50}}。"
            )

    used = extract_placeholders(" ".join([summary, *findings, *suggestions, *caveats]))
    return ValidatedAnalysis(
        summary=render_placeholders(summary, metric_map),
        findings=[render_placeholders(item, metric_map) for item in findings],
        suggestions=[render_placeholders(item, metric_map) for item in suggestions],
        caveats=[render_placeholders(item, metric_map) for item in caveats],
        metric_refs=sorted(used),
        templates={
            "summary": summary,
            "findings": findings,
            "suggestions": suggestions,
            "caveats": caveats,
        },
    )


# ---------------------------------------------------------------------------
# LLM orchestration
# ---------------------------------------------------------------------------


def _analysis_id(
    mode: str,
    run_id: str,
    variant_keys: list[str],
    settings: Any,
    code_version: str,
    fingerprint: str,
    data_version: str,
) -> str:
    payload = {
        "mode": mode,
        "run_id": run_id,
        "variant_keys": variant_keys,
        "advice_version": ADVICE_VERSION,
        "code_version": code_version,
        "code_fingerprint": fingerprint,
        "data_version": data_version,
        "model": settings.llm_model if getattr(settings, "llm_enabled", False) else "template",
    }
    return sha256_hex(canonical_json(payload))[:16]


def _build_response(
    *,
    analysis_id: str,
    mode: Literal["simple", "full", "history"],
    run_id: str,
    source: Literal["template", "llm"],
    model: str | None,
    validated: ValidatedAnalysis,
    metric_order: list[str],
    metric_labels: dict[str, str],
    variants: list[WhatIfVariant],
    facts: dict[str, Any],
    warnings: list[str],
    code_version: str,
    fingerprint: str,
    data_version: str,
) -> AnalysisResponse:
    from datetime import datetime, timezone

    return AnalysisResponse(
        analysis_id=analysis_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        mode=mode,
        run_id=run_id,
        source=source,
        model=model,
        summary=validated.summary,
        findings=validated.findings,
        suggestions=validated.suggestions,
        caveats=validated.caveats,
        metric_refs=validated.metric_refs,
        metric_order=metric_order,
        metric_labels=metric_labels,
        variants=variants,
        facts=facts,
        templates=validated.templates,
        warnings=warnings,
        code_version=code_version,
        code_fingerprint=fingerprint,
        data_version=data_version,
    )


def analyze(
    *,
    mode: Literal["simple", "full", "history"],
    run: RunResponse | None,
    history: HistoryResponse | None,
    settings: Any,
    code_version: str,
    code_fingerprint: str,
    data_version: str,
    cache_get: Callable[[str], AnalysisResponse | None] | None = None,
    cache_save: Callable[[AnalysisResponse], None] | None = None,
    force: bool = False,
) -> AnalysisResponse:
    if mode in ("simple", "full"):
        if run is None:
            raise ValueError("run is required for a simulation analysis")
        request = run.request
        metrics = run.metrics
        baseline = _simulation_values(metrics)
        plans = _simulation_plans(mode, request, metrics)
        run_id = run.run_id
    else:
        if history is None:
            raise ValueError("history response is required for a history analysis")
        request = history.request
        metrics = None
        baseline = _history_values(history)
        data = load_history_data()
        plans = _history_plans(request, data)
        run_id = history.run_id

    analysis_id = _analysis_id(
        mode,
        run_id,
        [plan.key for plan in plans],
        settings,
        code_version,
        code_fingerprint,
        data_version,
    )
    if not force and cache_get is not None:
        cached = cache_get(analysis_id)
        if cached is not None:
            return cached

    if mode in ("simple", "full"):
        assert request is not None and metrics is not None
        results = _run_simulation_variants(request, plans)
        specs = _simulation_metric_specs(mode, request, metrics)
        facts = _simulation_facts(mode, request, metrics, results)
        metric_map, descriptions = _simulation_placeholders(
            mode, request, metrics, baseline, results, specs
        )
        allowed = _allowed_literals(request)
    else:
        assert history is not None and request is not None
        data = load_history_data()
        results = _run_history_variants(request, history, data, plans)
        specs = _history_metric_specs(baseline)
        facts = _history_facts(request, history, data, results)
        metric_map, descriptions = _history_placeholders(
            request, history, data, baseline, results, specs
        )
        allowed = {asset.label for asset in data.assets.values()}
        allowed.update({"纳斯达克100", "纳指100"})

    variants = [
        WhatIfVariant(
            key="baseline",
            label="当前方案",
            description="本次推演结果，作为所有 what-if 的对照基准。",
            changes={},
            metrics=_metrics_for_values(baseline, baseline, specs, with_delta=False),
            warnings=[],
        )
    ]
    for result in results:
        variants.append(
            WhatIfVariant(
                key=result.key,
                label=result.label,
                description=result.description,
                changes=result.changes,
                metrics=_metrics_for_values(
                    result.values, baseline, specs, with_delta=True
                ),
                warnings=result.warnings,
            )
        )

    metric_order = [spec.key for spec in specs]
    metric_labels = {spec.key: spec.label for spec in specs}
    warnings: list[str] = []
    source: Literal["template", "llm"] = "template"
    model: str | None = None
    validated: ValidatedAnalysis

    if getattr(settings, "llm_enabled", False):
        prompt = _build_prompt(facts, metric_map, descriptions, results, mode)
        try:
            raw = _call_llm(
                prompt,
                settings,
                ADVICE_SYSTEM_PROMPT,
                max_tokens=2600,
            )
            payload = _parse_json_object(raw)
            validated = validate_analysis_payload(
                payload,
                metric_map,
                allowed,
                require_whatif=bool(results),
            )
            source = "llm"
            model = settings.llm_model
        except Exception as exc:  # noqa: BLE001 - fallback must be total
            warning = (
                "AI 分析不可用，已回退到模板分析："
                + sanitize_error(str(exc), settings.llm_api_key)
            )
            warnings.append(warning)
            validated = _template_analysis(
                mode, request, history, metrics, baseline, specs, results, metric_map
            )
    else:
        warnings.append("未配置 LLM API key，已使用模板分析。")
        validated = _template_analysis(
            mode, request, history, metrics, baseline, specs, results, metric_map
        )

    response = _build_response(
        analysis_id=analysis_id,
        mode=mode,
        run_id=run_id,
        source=source,
        model=model,
        validated=validated,
        metric_order=metric_order,
        metric_labels=metric_labels,
        variants=variants,
        facts=facts,
        warnings=warnings,
        code_version=code_version,
        fingerprint=code_fingerprint,
        data_version=data_version,
    )
    # Do not cache a fallback caused by an LLM error: the next click should
    # retry instead of returning the same degraded result.
    if cache_save is not None and (source == "llm" or not warnings or not getattr(settings, "llm_enabled", False)):
        cache_save(response)
    return response
