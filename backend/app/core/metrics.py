from __future__ import annotations

import math

import numpy as np

from ..models import (
    CompositionItem,
    DrawdownSummary,
    EventResult,
    PercentileBand,
    PercentilePoint,
    RunMetrics,
    ScenarioRequest,
    TimingPoint,
)
from .engine import SimulationOutput


def percentile_point(values: np.ndarray) -> PercentilePoint:
    q = np.percentile(np.asarray(values, dtype=float), [5, 25, 50, 75, 95])
    return PercentilePoint(
        p5=float(q[0]),
        p25=float(q[1]),
        p50=float(q[2]),
        p75=float(q[3]),
        p95=float(q[4]),
    )


def percentile_band(values: np.ndarray) -> PercentileBand:
    q = np.percentile(np.asarray(values, dtype=float), [5, 25, 50, 75, 95], axis=0)
    return PercentileBand(
        p5=q[0].tolist(),
        p25=q[1].tolist(),
        p50=q[2].tolist(),
        p75=q[3].tolist(),
        p95=q[4].tolist(),
    )


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = successes / n
    denominator = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denominator
    half = (
        z
        * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
        / denominator
    )
    return max(0.0, center - half), min(1.0, center + half)


def drawdown_summary(twr_index: np.ndarray) -> DrawdownSummary:
    series = np.concatenate(
        [np.ones((twr_index.shape[0], 1), dtype=float), twr_index], axis=1
    )
    running_max = np.maximum.accumulate(series, axis=1)
    drawdowns = 1.0 - series / np.maximum(running_max, 1e-12)
    max_drawdown = np.clip(drawdowns.max(axis=1), 0.0, 1.0)
    q = np.percentile(max_drawdown, [5, 25, 50, 75, 95])
    counts, edges = np.histogram(max_drawdown, bins=np.linspace(0.0, 1.0, 21))
    return DrawdownSummary(
        p5=float(q[0]),
        p25=float(q[1]),
        p50=float(q[2]),
        p75=float(q[3]),
        p95=float(q[4]),
        hist_edges=edges.tolist(),
        hist_counts=[int(count) for count in counts],
    )


def build_metrics(request: ScenarioRequest, simulation: SimulationOutput) -> RunMetrics:
    n_paths = request.n_paths
    horizon_years = request.horizon_years

    terminal_twr = simulation.twr_index[:, -1]
    annualized_twr = np.where(
        terminal_twr > 0.0,
        np.power(terminal_twr, 1.0 / horizon_years) - 1.0,
        -1.0,
    )

    event_results: list[EventResult] = []
    goal_success: list[np.ndarray] = []
    for index, event in enumerate(simulation.events):
        success_count = int(simulation.event_success[:, index].sum())
        success_probability = success_count / n_paths
        low, high = wilson_interval(success_count, n_paths)
        gaps = simulation.event_gaps[:, index]
        failed_gaps = gaps[~simulation.event_success[:, index]]
        mean_gap = float(np.mean(failed_gaps)) if failed_gaps.size else 0.0
        p50_gap = float(np.median(failed_gaps)) if failed_gaps.size else 0.0
        action_month = simulation.event_action_month[:, index]
        completed = action_month > 0
        action_age = simulation.event_action_age[:, index]
        has_window = event.has_goal and event.window_years > 0.0

        if has_window:
            window_end_month = event.window_end_month or event.month
            natural_count = int(
                np.sum(completed & (action_month < window_end_month))
            )
            deadline_count = int(
                np.sum(completed & (action_month == window_end_month))
            )
            natural_probability = natural_count / n_paths
            deadline_probability = deadline_count / n_paths
            failure_probability = 1.0 - success_probability
            timing: list[TimingPoint] = []
            for month in range(event.month, window_end_month + 1):
                cumulative = float(
                    np.mean(completed & (action_month <= month))
                )
                timing.append(
                    TimingPoint(
                        age=request.household.current_age + (month - 1) / 12.0,
                        probability=cumulative,
                    )
                )
        elif event.has_goal:
            natural_probability = success_probability
            deadline_probability = 0.0
            failure_probability = 1.0 - success_probability
            timing = []
        else:
            natural_probability = None
            deadline_probability = None
            failure_probability = None
            timing = []

        valid_ages = action_age[completed]
        if valid_ages.size:
            age_q = np.percentile(valid_ages, [25, 50, 75])
            median_action_age = float(age_q[1])
            action_age_p25 = float(age_q[0])
            action_age_p75 = float(age_q[2])
        else:
            median_action_age = None
            action_age_p25 = None
            action_age_p75 = None

        costs = simulation.event_costs[completed, index]
        median_cost = float(np.median(costs)) if costs.size else None

        investable_funding = simulation.event_funding_investable[:, index]
        emergency_funding = simulation.event_funding_emergency[:, index]
        funding_mask = (investable_funding + emergency_funding) > 1e-9
        if np.any(funding_mask):
            funding_investable_mean = float(
                np.mean(investable_funding[funding_mask])
            )
            funding_emergency_mean = float(
                np.mean(emergency_funding[funding_mask])
            )
            total_funding = investable_funding[funding_mask] + emergency_funding[
                funding_mask
            ]
            funding_emergency_share_mean = float(
                np.mean(
                    np.where(
                        total_funding > 0.0,
                        emergency_funding[funding_mask]
                        / np.maximum(total_funding, 1e-12),
                        0.0,
                    )
                )
            )
        else:
            funding_investable_mean = None
            funding_emergency_mean = None
            funding_emergency_share_mean = None

        event_results.append(
            EventResult(
                name=event.name,
                age=event.start_age,
                amount=event.amount,
                month=event.month,
                success_probability=success_probability,
                success_ci95_low=low,
                success_ci95_high=high,
                mean_gap=mean_gap,
                p50_gap=p50_gap,
                event_type=event.event_type,
                has_goal=event.has_goal,
                window_years=event.window_years,
                window_start_age=event.start_age if has_window else None,
                window_end_age=event.window_end_age if has_window else None,
                natural_success_probability=natural_probability,
                deadline_success_probability=deadline_probability,
                failure_probability=failure_probability,
                median_action_age=median_action_age,
                action_age_p25=action_age_p25,
                action_age_p75=action_age_p75,
                median_cost=median_cost,
                funding_investable_mean=funding_investable_mean,
                funding_emergency_mean=funding_emergency_mean,
                funding_emergency_share_mean=funding_emergency_share_mean,
                timing=timing,
            )
        )
        if event.has_goal:
            goal_success.append(simulation.event_success[:, index])

    if goal_success:
        all_success = np.all(np.stack(goal_success, axis=1), axis=1)
        joint_success_count = int(all_success.sum())
        joint_shortfall = 1.0 - joint_success_count / n_paths
        success_low, success_high = wilson_interval(joint_success_count, n_paths)
        joint_low, joint_high = 1.0 - success_high, 1.0 - success_low
    else:
        joint_shortfall = 0.0
        joint_low, joint_high = 0.0, 0.0

    ruin_count = int(simulation.ruin.sum())
    ruin_probability = ruin_count / n_paths
    ruin_low, ruin_high = wilson_interval(ruin_count, n_paths)

    goal_amount = float(request.goal_amount)
    if goal_amount > 0.0:
        goal_hits = simulation.total_assets[:, -1] >= goal_amount - 1e-9
        goal_count = int(goal_hits.sum())
        goal_probability = goal_count / n_paths
        goal_low, goal_high = wilson_interval(goal_count, n_paths)
    else:
        goal_probability = 0.0
        goal_low, goal_high = 0.0, 0.0

    monthly_debt_payment = float(simulation.debt_payments[0])
    monthly_surplus = (
        request.household.monthly_income
        - request.household.monthly_expense
        - monthly_debt_payment
    )

    composition: list[CompositionItem] = []
    for index, asset in enumerate(request.market.assets):
        composition.append(
            CompositionItem(
                label=asset.label or asset.name,
                value=float(np.median(simulation.final_holdings[:, index])),
                kind="investable",
            )
        )
    composition.append(
        CompositionItem(
            label="应急金",
            value=float(np.median(simulation.final_emergency)),
            kind="emergency",
        )
    )
    composition.append(
        CompositionItem(
            label="非流动资产",
            value=float(np.median(simulation.final_illiquid)),
            kind="illiquid",
        )
    )
    composition.append(
        CompositionItem(
            label="负债",
            value=float(np.median(simulation.final_liabilities)),
            kind="liability",
        )
    )

    return RunMetrics(
        months=[int(month) for month in simulation.months],
        years=[float(month) / 12.0 for month in simulation.months],
        assets=percentile_band(simulation.total_assets),
        net_worth=percentile_band(simulation.net_worth),
        terminal_assets=percentile_point(simulation.total_assets[:, -1]),
        terminal_net_worth=percentile_point(simulation.net_worth[:, -1]),
        max_drawdown=drawdown_summary(simulation.twr_index),
        annualized_twr=percentile_point(annualized_twr),
        events=event_results,
        joint_shortfall_probability=joint_shortfall,
        joint_shortfall_ci95_low=joint_low,
        joint_shortfall_ci95_high=joint_high,
        ruin_probability=ruin_probability,
        ruin_ci95_low=ruin_low,
        ruin_ci95_high=ruin_high,
        total_contributions=simulation.total_contributions,
        total_event_withdrawals=simulation.total_event_withdrawals,
        total_debt_interest=simulation.total_debt_interest,
        initial_capital=simulation.initial_liquid,
        monthly_surplus=monthly_surplus,
        monthly_debt_payment=monthly_debt_payment,
        goal_amount=goal_amount,
        goal_probability=goal_probability,
        goal_ci95_low=goal_low,
        goal_ci95_high=goal_high,
        emergency_fund=percentile_band(simulation.emergency_fund),
        illiquid_assets=percentile_band(simulation.illiquid_assets),
        liabilities=percentile_band(simulation.liabilities),
        terminal_emergency_fund=percentile_point(simulation.emergency_fund[:, -1]),
        terminal_illiquid_assets=percentile_point(simulation.illiquid_assets[:, -1]),
        terminal_liabilities=percentile_point(simulation.liabilities[:, -1]),
        terminal_composition=composition,
        emergency_fund_target_months=request.household.emergency_fund_months,
        initial_net_worth=simulation.initial_net_worth,
        initial_emergency_fund=simulation.initial_emergency,
        initial_illiquid_assets=simulation.initial_illiquid,
        initial_liabilities=simulation.initial_liabilities,
    )
