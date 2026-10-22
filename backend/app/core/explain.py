from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..models import Explanation, RunMetrics, ScenarioRequest
from .strategy import target_weights

PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

SYSTEM_PROMPT = """你是家庭财务情景推演的解释层，不是投资顾问。
你只能使用给定的指标摘要和占位符，不得自行计算、推断或生成任何数字。

规则：
1. 只输出一个 JSON 对象，字段为 summary（字符串）、bullets（字符串数组，3-5 条）、caveats（字符串数组，2-4 条）、metric_refs（字符串数组）。
2. 任何数值都必须写成 {{key}} 占位符，key 必须来自给定的占位符列表。文本中不得出现阿拉伯数字、百分号、小数，也不得用“十年”“八成”“百分之五”等数量表述；需要表达数量时一律使用占位符。
3. 不得给出交易指令、具体基金或 ETF 推荐、收益承诺或择时建议。
4. 语气克制，强调这是假设推演而不是预测；解释数值的生活含义：最可能的结果、下行风险、事件通过率、最敏感的假设。
5. 不要输出 Markdown 代码围栏或 JSON 之外的任何文字。"""


class LLMValidationError(ValueError):
    pass


@dataclass
class ValidatedContent:
    summary: str
    bullets: list[str]
    caveats: list[str]
    metric_refs: list[str]
    templates: dict


def format_money(value: float) -> str:
    if abs(value) >= 10_000.0:
        return f"{value / 10_000.0:.1f}万元"
    return f"{value:.0f}元"


def format_pct(value: float) -> str:
    return f"{value * 100.0:.1f}%"


def format_age(value: float) -> str:
    return f"{value:g}岁"


def placeholder(key: str) -> str:
    return "{{" + key + "}}"


def extract_placeholders(text: str) -> list[str]:
    return sorted({match.group(1) for match in PLACEHOLDER_PATTERN.finditer(text)})


def render_placeholders(text: str, metric_map: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in metric_map:
            raise LLMValidationError(f"unknown placeholder {key!r}")
        return metric_map[key]

    return PLACEHOLDER_PATTERN.sub(replace, text)


def _growth_weight_at(request: ScenarioRequest, age: float) -> float:
    try:
        weights = target_weights(
            request.strategy,
            [asset.name for asset in request.market.assets],
            age,
        )
    except Exception:
        return 0.0
    total = 0.0
    for index, asset in enumerate(request.market.assets):
        if asset.role == "growth":
            total += float(weights[index])
    if total <= 0.0:
        for index, asset in enumerate(request.market.assets):
            if asset.name == request.strategy.equity_asset:
                total += float(weights[index])
    return total


def build_metric_context(
    request: ScenarioRequest, metrics: RunMetrics
) -> tuple[dict[str, str], dict[str, str]]:
    """Return formatted placeholder values and their human descriptions."""
    horizon_end_age = request.household.current_age + request.horizon_years
    equity_start = _growth_weight_at(request, request.household.current_age)
    equity_end = _growth_weight_at(request, horizon_end_age)
    joint_success = max(0.0, 1.0 - metrics.joint_shortfall_probability)
    terminal_emergency = (
        metrics.terminal_emergency_fund.p50
        if metrics.terminal_emergency_fund is not None
        else 0.0
    )
    terminal_illiquid = (
        metrics.terminal_illiquid_assets.p50
        if metrics.terminal_illiquid_assets is not None
        else 0.0
    )
    terminal_liabilities = (
        metrics.terminal_liabilities.p50
        if metrics.terminal_liabilities is not None
        else 0.0
    )

    metric_map: dict[str, str] = {
        "scenario_name": request.name,
        "horizon_years": f"{request.horizon_years}年",
        "n_paths": f"{request.n_paths}条路径",
        "seed": str(request.seed),
        "initial_capital": format_money(metrics.initial_capital),
        "initial_emergency_fund": format_money(metrics.initial_emergency_fund or 0.0),
        "initial_illiquid_assets": format_money(metrics.initial_illiquid_assets or 0.0),
        "initial_liabilities": format_money(metrics.initial_liabilities or 0.0),
        "monthly_surplus": format_money(metrics.monthly_surplus),
        "monthly_debt_payment": format_money(metrics.monthly_debt_payment),
        "total_contributions": format_money(metrics.total_contributions),
        "total_event_withdrawals": format_money(metrics.total_event_withdrawals),
        "total_debt_interest": format_money(metrics.total_debt_interest),
        "terminal_assets_p5": format_money(metrics.terminal_assets.p5),
        "terminal_assets_p25": format_money(metrics.terminal_assets.p25),
        "terminal_assets_p50": format_money(metrics.terminal_assets.p50),
        "terminal_assets_p75": format_money(metrics.terminal_assets.p75),
        "terminal_assets_p95": format_money(metrics.terminal_assets.p95),
        "terminal_net_worth_p50": format_money(metrics.terminal_net_worth.p50),
        "terminal_emergency_fund_p50": format_money(terminal_emergency),
        "terminal_illiquid_assets_p50": format_money(terminal_illiquid),
        "terminal_liabilities_p50": format_money(terminal_liabilities),
        "emergency_fund_target_months": f"{request.household.emergency_fund_months:g}个月",
        "max_drawdown_p50": format_pct(metrics.max_drawdown.p50),
        "max_drawdown_p95": format_pct(metrics.max_drawdown.p95),
        "annualized_twr_p50": format_pct(metrics.annualized_twr.p50),
        "joint_success_probability": format_pct(joint_success),
        "joint_shortfall_probability": format_pct(
            metrics.joint_shortfall_probability
        ),
        "ruin_probability": format_pct(metrics.ruin_probability),
        "equity_start_weight": format_pct(equity_start),
        "equity_end_weight": format_pct(equity_end),
        "growth_start_weight": format_pct(equity_start),
        "growth_end_weight": format_pct(equity_end),
    }
    descriptions: dict[str, str] = {
        "scenario_name": "情景名称",
        "horizon_years": "推演年限（含单位）",
        "n_paths": "蒙特卡洛路径数（含单位）",
        "seed": "随机种子",
        "initial_capital": "初始流动资产",
        "initial_emergency_fund": "初始应急金",
        "initial_illiquid_assets": "初始非流动资产",
        "initial_liabilities": "初始负债",
        "monthly_surplus": "首月结余（收入减支出减月供）",
        "monthly_debt_payment": "首月月供",
        "total_contributions": "推演期内累计投入",
        "total_event_withdrawals": "实际事件支出合计（已完成的事件支出）",
        "total_debt_interest": "推演期内累计利息",
        "terminal_assets_p5": "期末流动资产的下五分位",
        "terminal_assets_p25": "期末流动资产的下四分位",
        "terminal_assets_p50": "期末流动资产中位数",
        "terminal_assets_p75": "期末流动资产的上四分位",
        "terminal_assets_p95": "期末流动资产的上五分位",
        "terminal_net_worth_p50": "期末净资产中位数",
        "terminal_emergency_fund_p50": "期末应急金中位数",
        "terminal_illiquid_assets_p50": "期末非流动资产中位数",
        "terminal_liabilities_p50": "期末负债中位数",
        "emergency_fund_target_months": "应急金目标月数",
        "max_drawdown_p50": "时间加权最大回撤中位数",
        "max_drawdown_p95": "时间加权最大回撤的上五分位",
        "annualized_twr_p50": "时间加权年化收益中位数",
        "joint_success_probability": "所有目标事件同时通过的概率",
        "joint_shortfall_probability": "至少一个目标事件未通过的概率",
        "ruin_probability": "曾耗尽金融资产的路径占比",
        "equity_start_weight": "期初成长资产目标权重",
        "equity_end_weight": "期末成长资产目标权重",
        "growth_start_weight": "期初成长资产目标权重",
        "growth_end_weight": "期末成长资产目标权重",
    }

    for index, event in enumerate(metrics.events):
        prefix = f"event_{index}"
        metric_map[f"{prefix}_name"] = event.name
        metric_map[f"{prefix}_age"] = format_age(event.age)
        metric_map[f"{prefix}_amount"] = format_money(event.amount)
        metric_map[f"{prefix}_success_probability"] = format_pct(
            event.success_probability
        )
        metric_map[f"{prefix}_mean_gap"] = format_money(event.mean_gap)
        metric_map[f"{prefix}_p50_gap"] = format_money(event.p50_gap)
        metric_map[f"{prefix}_window"] = (
            f"{event.window_start_age:g}–{event.window_end_age:g}岁"
            f"（{event.window_years:g}年窗口）"
            if event.window_years > 0
            and event.window_start_age is not None
            and event.window_end_age is not None
            else "无窗口"
        )
        metric_map[f"{prefix}_median_action_age"] = (
            format_age(event.median_action_age)
            if event.median_action_age is not None
            else "未完成"
        )
        metric_map[f"{prefix}_action_age_p25"] = (
            format_age(event.action_age_p25)
            if event.action_age_p25 is not None
            else "未完成"
        )
        metric_map[f"{prefix}_action_age_p75"] = (
            format_age(event.action_age_p75)
            if event.action_age_p75 is not None
            else "未完成"
        )
        metric_map[f"{prefix}_natural_success_probability"] = (
            format_pct(event.natural_success_probability)
            if event.natural_success_probability is not None
            else "不适用"
        )
        metric_map[f"{prefix}_deadline_success_probability"] = (
            format_pct(event.deadline_success_probability)
            if event.deadline_success_probability is not None
            else "不适用"
        )
        metric_map[f"{prefix}_failure_probability"] = (
            format_pct(event.failure_probability)
            if event.failure_probability is not None
            else "不适用"
        )
        metric_map[f"{prefix}_median_cost"] = (
            format_money(event.median_cost)
            if event.median_cost is not None
            else "无"
        )
        metric_map[f"{prefix}_funding_investable"] = (
            format_money(event.funding_investable_mean)
            if event.funding_investable_mean is not None
            else "无"
        )
        metric_map[f"{prefix}_funding_emergency"] = (
            format_money(event.funding_emergency_mean)
            if event.funding_emergency_mean is not None
            else "无"
        )
        descriptions[f"{prefix}_name"] = f"第 {index + 1} 个人生事件的名称"
        descriptions[f"{prefix}_age"] = f"第 {index + 1} 个人生事件的发生年龄（含单位）"
        descriptions[f"{prefix}_amount"] = f"第 {index + 1} 个人生事件的目标金额"
        descriptions[f"{prefix}_success_probability"] = (
            f"第 {index + 1} 个人生事件的通过率"
        )
        descriptions[f"{prefix}_mean_gap"] = (
            f"第 {index + 1} 个人生事件失败路径的平均缺口"
        )
        descriptions[f"{prefix}_p50_gap"] = (
            f"第 {index + 1} 个人生事件缺口的中位数"
        )
        descriptions[f"{prefix}_window"] = (
            f"第 {index + 1} 个人生事件的时间窗（含年龄和年数）"
        )
        descriptions[f"{prefix}_median_action_age"] = (
            f"第 {index + 1} 个人生事件完成时点的中位数"
        )
        descriptions[f"{prefix}_action_age_p25"] = (
            f"第 {index + 1} 个人生事件完成时点的下四分位"
        )
        descriptions[f"{prefix}_action_age_p75"] = (
            f"第 {index + 1} 个人生事件完成时点的上四分位"
        )
        descriptions[f"{prefix}_natural_success_probability"] = (
            f"第 {index + 1} 个人生事件在窗口内（末月之前）完成的概率"
        )
        descriptions[f"{prefix}_deadline_success_probability"] = (
            f"第 {index + 1} 个人生事件在窗口末月完成的概率"
        )
        descriptions[f"{prefix}_failure_probability"] = (
            f"第 {index + 1} 个人生事件未完成的概率"
        )
        descriptions[f"{prefix}_median_cost"] = (
            f"第 {index + 1} 个人生事件完成时的实际金额中位数"
        )
        descriptions[f"{prefix}_funding_investable"] = (
            f"第 {index + 1} 个人生事件平均从投资资产动用的金额"
        )
        descriptions[f"{prefix}_funding_emergency"] = (
            f"第 {index + 1} 个人生事件平均从应急金动用的金额"
        )

    return metric_map, descriptions


def build_numeric_summary(
    request: ScenarioRequest, metrics: RunMetrics
) -> dict[str, Any]:
    def point_or_none(point):
        return point.model_dump() if point is not None else None

    return {
        "note": "所有金额均为今日购买力；收益率为实际几何年化收益。",
        "scenario": request.name,
        "calibration_window": request.calibration_window,
        "data_version": request.data_version,
        "horizon_years": request.horizon_years,
        "n_paths": request.n_paths,
        "seed": request.seed,
        "strategy": request.strategy.model_dump(),
        "assets": [
            {
                "name": asset.name,
                "label": asset.label,
                "role": asset.role,
                "expected_real_return": asset.expected_real_return,
                "volatility": asset.volatility,
                "expense_ratio": asset.expense_ratio,
            }
            for asset in request.market.assets
        ],
        "household": {
            "current_age": request.household.current_age,
            "initial_liquid": metrics.initial_capital,
            "initial_emergency": metrics.initial_emergency_fund,
            "initial_illiquid": metrics.initial_illiquid_assets,
            "initial_liabilities": metrics.initial_liabilities,
            "monthly_income": request.household.monthly_income,
            "monthly_expense": request.household.monthly_expense,
            "monthly_debt_payment": metrics.monthly_debt_payment,
            "monthly_surplus": metrics.monthly_surplus,
            "emergency_fund_months": request.household.emergency_fund_months,
            "emergency_fund_includes_debt": request.household.emergency_fund_includes_debt,
            "event_withdrawal_order": request.household.event_withdrawal_order,
            "holdings": [holding.model_dump() for holding in request.household.holdings],
            "liabilities": [
                liability.model_dump()
                for liability in request.household.liabilities
            ],
            "events": [event.model_dump() for event in request.household.events],
        },
        "results": {
            "terminal_assets": metrics.terminal_assets.model_dump(),
            "terminal_net_worth": metrics.terminal_net_worth.model_dump(),
            "terminal_emergency": point_or_none(metrics.terminal_emergency_fund),
            "terminal_illiquid": point_or_none(metrics.terminal_illiquid_assets),
            "terminal_liabilities": point_or_none(metrics.terminal_liabilities),
            "max_drawdown": metrics.max_drawdown.model_dump(),
            "annualized_twr": metrics.annualized_twr.model_dump(),
            "events": [event.model_dump() for event in metrics.events],
            "joint_shortfall_probability": metrics.joint_shortfall_probability,
            "ruin_probability": metrics.ruin_probability,
            "total_contributions": metrics.total_contributions,
            "total_event_withdrawals": metrics.total_event_withdrawals,
            "total_debt_interest": metrics.total_debt_interest,
            "terminal_composition": [
                item.model_dump() for item in metrics.terminal_composition
            ],
        },
        "model_notes": [
            "收益、波动、相关性、收入与支出均为用户假设，不是预测。",
            "历史校准的收益是特定窗口的实现值，不是未来预期。",
            "未单独建模通胀；全部数字按今日购买力计算。",
            "未建模失业、降薪以及收入与市场波动的相关性。",
            "资产收益使用官方全收益/财富指数，未扣产品费率；纳指100 为人民币、含汇率、未对冲。",
            "黄金无分红，价格即总收益；现金为 0% 实际收益假设。",
            "应急金优先补足；计划性事件默认先用投资资产、后动应急金。",
            "时间窗事件在窗口内每月检查一次，使用全部流动资产（投资资产、现金和应急金）；首次买得起/付得起时执行。",
            "窗口末月会用全部流动资产再试一次：购置资产仍不足则记未通过；一次性支出会赎回全部流动资产并记录缺口。",
            "非流动资产不会为了凑首付自动变现；非流动资产按固定增长率估值，未建模房价/车价波动。",
            "最大回撤为时间加权净值的路径最大值，已剔除外部现金流影响。",
            "参数不确定性和模型选择不确定性未单独量化。",
        ],
    }


def template_explanation(
    request: ScenarioRequest, metrics: RunMetrics
) -> Explanation:
    metric_map, _ = build_metric_context(request, metrics)
    summary = (
        f"在{placeholder('scenario_name')}情景下，未来{placeholder('horizon_years')}的推演里，"
        f"期末金融资产中位数约为{placeholder('terminal_assets_p50')}，"
        f"5%–95%分位区间约为{placeholder('terminal_assets_p5')}到{placeholder('terminal_assets_p95')}。"
    )
    bullets = [
        f"25%–75%分位区间约为{placeholder('terminal_assets_p25')}到"
        f"{placeholder('terminal_assets_p75')}，也就是说一半路径落在这个范围；"
        f"期末净资产中位数约为{placeholder('terminal_net_worth_p50')}。",
        f"时间加权最大回撤的中位数约为{placeholder('max_drawdown_p50')}，"
        f"95%分位约为{placeholder('max_drawdown_p95')}。这个口径已经剔除投入和赎回现金流的影响。",
        f"首月结余约为{placeholder('monthly_surplus')}，其中月供约为"
        f"{placeholder('monthly_debt_payment')}；推演期内累计投入约为"
        f"{placeholder('total_contributions')}。",
        f"应急金目标为{placeholder('emergency_fund_target_months')}的开销；"
        f"期末应急金中位数约为{placeholder('terminal_emergency_fund_p50')}，"
        f"非流动资产中位数约为{placeholder('terminal_illiquid_assets_p50')}，"
        f"负债中位数约为{placeholder('terminal_liabilities_p50')}。",
    ]
    goal_indices = [
        index for index, event in enumerate(metrics.events) if event.has_goal
    ]
    if goal_indices:
        for index in goal_indices:
            event = metrics.events[index]
            if event.window_years > 0 and event.has_goal:
                if event.median_action_age is None:
                    bullets.append(
                        f"事件“{placeholder(f'event_{index}_name')}”的时间窗为"
                        f"{placeholder(f'event_{index}_window')}；窗口内（末月之前）完成概率约"
                        f"{placeholder(f'event_{index}_natural_success_probability')}，"
                        f"末月完成概率约"
                        f"{placeholder(f'event_{index}_deadline_success_probability')}，"
                        f"未完成概率约"
                        f"{placeholder(f'event_{index}_failure_probability')}；"
                        f"本次推演中没有路径完成该事件，失败路径的平均缺口约为"
                        f"{placeholder(f'event_{index}_mean_gap')}。"
                    )
                else:
                    bullets.append(
                        f"事件“{placeholder(f'event_{index}_name')}”的时间窗为"
                        f"{placeholder(f'event_{index}_window')}；窗口内（末月之前）完成概率约"
                        f"{placeholder(f'event_{index}_natural_success_probability')}，"
                        f"末月完成概率约"
                        f"{placeholder(f'event_{index}_deadline_success_probability')}，"
                        f"未完成概率约"
                        f"{placeholder(f'event_{index}_failure_probability')}。完成时点中位数约"
                        f"{placeholder(f'event_{index}_median_action_age')}，"
                        f"25%–75%分位约"
                        f"{placeholder(f'event_{index}_action_age_p25')}到"
                        f"{placeholder(f'event_{index}_action_age_p75')}；"
                        f"平均从投资资产动用"
                        f"{placeholder(f'event_{index}_funding_investable')}、"
                        f"从应急金动用"
                        f"{placeholder(f'event_{index}_funding_emergency')}。"
                    )
            else:
                bullets.append(
                    f"事件“{placeholder(f'event_{index}_name')}”发生在"
                    f"{placeholder(f'event_{index}_age')}，目标金额"
                    f"{placeholder(f'event_{index}_amount')}，通过率约为"
                    f"{placeholder(f'event_{index}_success_probability')}，失败路径的平均缺口约为"
                    f"{placeholder(f'event_{index}_mean_gap')}。"
                )
        bullets.append(
            f"所有目标事件同时通过的概率约为{placeholder('joint_success_probability')}；"
            f"曾耗尽金融资产的路径占比约为{placeholder('ruin_probability')}。"
        )
    else:
        bullets.append(
            "本次没有设置需要一次性资金的目标事件；持续收入/支出已并入现金流。"
        )

    caveats = [
        "收益、波动、相关性、收入与支出都是假设，不是预测；历史校准的收益是特定窗口的实现值。",
        "所有数字为今日购买力，未单独建模通胀。",
        "未建模失业、降薪及收入与市场的相关性，也未建模税费和交易成本。",
        "资产收益来自官方全收益/财富指数，未扣产品费率；纳指100 含汇率、未对冲。",
        "应急金优先补足；计划性事件默认先用投资资产、后动应急金，顺序可在表单中调整。",
        "时间窗内每月用全部流动资产（投资资产、现金和应急金）检查一次；窗口末月会用全部流动资产再试一次，仍不足时买入资产记未通过，一次性支出会赎回全部流动资产并记录缺口。",
        "非流动资产不会为了凑首付自动卖出；需要先显式设置卖出年龄。",
        "非流动资产按固定增长率估值，未建模房价/车价波动，也不能在事件中自动变现。",
        "最大回撤按时间加权净值计算，已剔除投入和赎回的现金流影响。",
        "本工具仅用于情景推演，不构成投资建议。",
    ]

    raw_templates = {"summary": summary, "bullets": bullets, "caveats": caveats}
    refs = extract_placeholders(
        " ".join([summary, *bullets, *caveats])
    )
    return Explanation(
        summary=render_placeholders(summary, metric_map),
        bullets=[render_placeholders(item, metric_map) for item in bullets],
        caveats=[render_placeholders(item, metric_map) for item in caveats],
        metric_refs=refs,
        source="template",
        templates=raw_templates,
    )


def _check_no_raw_numbers(
    text: str, allowed_literals: set[str] | None = None
) -> None:
    # Proper names such as "纳斯达克100" or "中证500" contain digits but are
    # not financial quantities. Remove the known names before checking.
    stripped = text
    for literal in sorted(allowed_literals or set(), key=len, reverse=True):
        if literal:
            stripped = stripped.replace(literal, "")
    stripped = PLACEHOLDER_PATTERN.sub("", stripped)
    if re.search(r"\d", stripped):
        raise LLMValidationError("LLM 文本包含未经占位符引用的阿拉伯数字")
    if "%" in stripped:
        raise LLMValidationError("LLM 文本包含未经占位符引用的百分号")
    if "百分之" in stripped:
        raise LLMValidationError("LLM 文本包含未经占位符引用的百分比表述")
    if re.search(r"[一二三四五六七八九十百千万亿]+(?:年|岁|元|万|成|倍|个月)", stripped):
        raise LLMValidationError("LLM 文本包含未经占位符引用的数量表述")
    forbidden = [
        "买入",
        "卖出",
        "稳赚",
        "必涨",
        "抄底",
        "满仓",
        "梭哈",
        "加仓",
        "减仓",
        "清仓",
    ]
    for phrase in forbidden:
        if phrase in stripped:
            raise LLMValidationError(f"LLM 文本包含不当建议措辞：{phrase}")

    def negated_in_clause(text: str, position: int) -> bool:
        # Look at the current clause, not the whole sentence: "不保证收益，
        # 但承诺保本" must still reject the promise in the second clause.
        boundary = max(
            (text.rfind(char, 0, position) for char in "，,。！？；\n"),
            default=-1,
        )
        prefix = text[boundary + 1 : position]
        return any(
            word in prefix
            for word in ("不", "未", "无", "非", "无法", "不能", "难以", "不会", "没有", "并非")
        )

    # "不保证收益" and "不推荐具体产品" are legitimate caveats; the positive
    # forms are promises or product recommendations.
    for phrase in ("保证", "承诺", "推荐"):
        for match in re.finditer(phrase, stripped):
            if negated_in_clause(stripped, match.start()):
                continue
            raise LLMValidationError(f"LLM 文本包含不当建议措辞：{phrase}")


def _allowed_literals(request: ScenarioRequest) -> set[str]:
    literals: set[str] = {request.name}
    for asset in request.market.assets:
        label = asset.label or asset.name
        literals.add(label)
        if "（" in label:
            literals.add(label.split("（", 1)[0])
        if asset.name == "ndx100":
            literals.update({"纳指100", "纳指"})
    for event in request.household.events:
        literals.add(event.name)
    for holding in request.household.holdings:
        literals.add(holding.label)
    for liability in request.household.liabilities:
        literals.add(liability.name)
    return {item.strip() for item in literals if item and item.strip()}


def validate_llm_payload(
    payload: Any,
    metric_map: dict[str, str],
    allowed_literals: set[str] | None = None,
) -> ValidatedContent:
    if not isinstance(payload, dict):
        raise LLMValidationError("LLM 输出必须是 JSON 对象")
    summary = payload.get("summary")
    bullets = payload.get("bullets")
    caveats = payload.get("caveats")
    metric_refs = payload.get("metric_refs")
    if not isinstance(summary, str) or not summary.strip():
        raise LLMValidationError("summary 必须是非空字符串")
    if not isinstance(bullets, list) or not bullets or not all(
        isinstance(item, str) and item.strip() for item in bullets
    ):
        raise LLMValidationError("bullets 必须是非空字符串数组")
    if not isinstance(caveats, list) or not all(
        isinstance(item, str) and item.strip() for item in caveats
    ):
        raise LLMValidationError("caveats 必须是字符串数组")
    if not isinstance(metric_refs, list) or not all(
        isinstance(item, str) for item in metric_refs
    ):
        raise LLMValidationError("metric_refs 必须是字符串数组")

    texts = [summary, *bullets, *caveats]
    used: set[str] = set()
    for text in texts:
        _check_no_raw_numbers(text, allowed_literals)
        used.update(extract_placeholders(text))

    unknown = used - set(metric_map)
    if unknown:
        raise LLMValidationError(f"未知占位符：{sorted(unknown)}")
    if set(metric_refs) != used:
        raise LLMValidationError("metric_refs 必须与实际使用的占位符完全一致")
    if len(bullets) > 8:
        raise LLMValidationError("bullets 过多")

    return ValidatedContent(
        summary=render_placeholders(summary, metric_map),
        bullets=[render_placeholders(item, metric_map) for item in bullets],
        caveats=[render_placeholders(item, metric_map) for item in caveats],
        metric_refs=sorted(used),
        templates={"summary": summary, "bullets": bullets, "caveats": caveats},
    )


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LLMValidationError("LLM 输出不是合法 JSON") from None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMValidationError("LLM 输出不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise LLMValidationError("LLM 输出必须是 JSON 对象")
    return value


def _build_llm_prompt(
    numeric_summary: dict[str, Any],
    metric_map: dict[str, str],
    descriptions: dict[str, str],
) -> str:
    lines = [
        "指标摘要（仅供理解，不要复制其中的数字）：",
        json.dumps(numeric_summary, ensure_ascii=False, indent=2),
        "",
        "可用占位符（key: 说明；当前值仅用于帮助你理解）：",
    ]
    for key, description in descriptions.items():
        lines.append(f"- {key}: {description}（当前值：{metric_map.get(key, '')}）")
    lines.extend(
        [
            "",
            "请输出严格 JSON，字段为 summary、bullets、caveats、metric_refs。",
            "summary 一句话概括；bullets 3-5 条解释生活含义；caveats 2-4 条说明模型边界。",
            "如果事件有 window_years > 0，请优先用该事件的 window、median_action_age、natural_success_probability、deadline_success_probability、failure_probability、funding_investable、funding_emergency 占位符说明完成时点和概率。",
            "分位数请使用对应的 p25/p75/p95 占位符，不要写带阿拉伯数字的分位表述。",
            "描述资金动作时使用“执行”“支付”“变现”“投入”等中性词。",
            "所有数值必须使用上面的 {{key}} 占位符；metric_refs 必须列出你用到的全部 key。",
            "不要给出投资建议或具体产品推荐。",
        ]
    )
    return "\n".join(lines)


def _call_llm(
    prompt: str,
    settings: Any,
    system_prompt: str = SYSTEM_PROMPT,
    max_tokens: int = 2000,
) -> str:
    """Call an OpenAI-compatible endpoint with requests.

    The openai SDK in this environment pulls in an httpx2 version with a broken
    decompressor, so speaking the HTTP protocol directly is both simpler and
    more portable across DeepSeek/SiliconFlow-style providers.
    """
    import requests

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        # Window explanations include several placeholders per event; 900
        # tokens can truncate the JSON mid-string and force a template
        # fallback.
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=settings.llm_timeout_seconds,
    )
    if response.status_code == 400:
        # Some OpenAI-compatible providers reject response_format.
        payload.pop("response_format", None)
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=settings.llm_timeout_seconds,
        )
    response.raise_for_status()
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMValidationError("LLM 返回结构异常") from exc
    if not content:
        raise LLMValidationError("LLM 返回空内容")
    return content


def llm_explanation(
    request: ScenarioRequest, metrics: RunMetrics, settings: Any
) -> Explanation:
    metric_map, descriptions = build_metric_context(request, metrics)
    numeric_summary = build_numeric_summary(request, metrics)
    prompt = _build_llm_prompt(numeric_summary, metric_map, descriptions)
    raw = _call_llm(prompt, settings)
    payload = _parse_json_object(raw)
    validated = validate_llm_payload(
        payload, metric_map, _allowed_literals(request)
    )
    return Explanation(
        summary=validated.summary,
        bullets=validated.bullets,
        caveats=validated.caveats,
        metric_refs=validated.metric_refs,
        source="llm",
        model=settings.llm_model,
        templates=validated.templates,
    )


def sanitize_error(message: str, api_key: str) -> str:
    if api_key:
        message = message.replace(api_key, "[redacted]")
    message = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[redacted]", message)
    return message[:500]


def explain_run(
    request: ScenarioRequest, metrics: RunMetrics, settings: Any
) -> tuple[Explanation, list[str]]:
    template = template_explanation(request, metrics)
    if not request.include_explanation:
        return template, []
    if not getattr(settings, "llm_enabled", False):
        warning = "未配置 LLM API key，已使用模板解释。"
        template.warnings = [warning]
        return template, [warning]
    try:
        return llm_explanation(request, metrics, settings), []
    except Exception as exc:  # noqa: BLE001 - fallback must be total
        warning = f"LLM 解释不可用，已回退到模板解释：{sanitize_error(str(exc), settings.llm_api_key)}"
        template.warnings = [warning]
        return template, [warning]
