from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from ..models import LifeEvent, ScenarioRequest
from .liabilities import LoanSchedule, amortization_schedule
from .returns import (
    cholesky_with_jitter,
    draw_standardized_shocks,
    monthly_fee_log,
    monthly_log_params,
)
from .strategy import target_weights


@dataclass(frozen=True)
class SimulatedEvent:
    name: str
    event_type: Literal["cashflow", "purchase"]
    start_age: float
    month: int
    end_month: int | None
    amount: float
    has_goal: bool
    window_years: float = 0.0
    window_end_month: int | None = None
    window_end_age: float | None = None


@dataclass
class ProjectedLoan:
    label: str
    schedule: LoanSchedule
    active: np.ndarray
    event_index: int | None = None
    linked_asset_index: int | None = None


@dataclass
class ProjectedAsset:
    label: str
    asset_kind: str
    values: np.ndarray
    selling_cost_rate: float
    monthly_income: np.ndarray
    monthly_expense: np.ndarray
    active: np.ndarray
    linked_loans: list[int] = field(default_factory=list)
    event_index: int | None = None
    purchase_month: int | None = None
    sale_month: int | None = None


@dataclass
class EventPlan:
    index: int
    name: str
    event_type: Literal["cashflow", "purchase"]
    start_month: int
    end_month: int | None
    start_age: float
    one_off_expense: float
    has_goal: bool
    window_months: int = 0
    window_end_month: int | None = None
    # Months at which the event may be completed. For a window this spans the
    # whole range; without a window it contains only the start month.
    action_months: list[int] = field(default_factory=list)
    action_costs: dict[int, float] = field(default_factory=dict)
    purchase_asset_index: int | None = None
    purchase_loan_indices: dict[int, int] = field(default_factory=dict)
    purchase_cost: float = 0.0
    income: np.ndarray = field(default_factory=lambda: np.zeros(0))
    expense: np.ndarray = field(default_factory=lambda: np.zeros(0))
    completed: np.ndarray | None = None
    failed: np.ndarray | None = None


@dataclass
class SimulationOutput:
    months: np.ndarray
    total_assets: np.ndarray
    investable_assets: np.ndarray
    emergency_fund: np.ndarray
    illiquid_assets: np.ndarray
    liabilities: np.ndarray
    net_worth: np.ndarray
    twr_index: np.ndarray
    event_success: np.ndarray
    event_gaps: np.ndarray
    # Month (1-based) at which each event was completed, -1 otherwise. For a
    # purchase this is the purchase month; for a one-off expense, the payment
    # month.
    event_action_month: np.ndarray
    event_action_age: np.ndarray
    event_deadline: np.ndarray
    event_funding_investable: np.ndarray
    event_funding_emergency: np.ndarray
    event_costs: np.ndarray
    events: list[SimulatedEvent]
    ruin: np.ndarray
    debt_payments: np.ndarray
    debt_balances: np.ndarray
    total_contributions: float
    total_event_withdrawals: float
    total_debt_interest: float
    initial_liquid: float
    initial_emergency: float
    initial_illiquid: float
    initial_liabilities: float
    initial_net_worth: float
    final_holdings: np.ndarray
    final_emergency: np.ndarray
    final_illiquid: np.ndarray
    final_liabilities: np.ndarray
    warnings: list[str]


def _event_month(age: float, current_age: float, horizon_months: int) -> int | None:
    # Month 1 is the current age: age_at_month = current_age + (month - 1)/12.
    month = int(round((age - current_age) * 12.0)) + 1
    if month < 1 or month > horizon_months:
        return None
    return month


def _growth_curve(base_value: float, annual_rate: float, start_month: int, horizon: int) -> np.ndarray:
    values = np.zeros(horizon, dtype=float)
    if start_month > horizon:
        return values
    for month in range(start_month, horizon + 1):
        values[month - 1] = base_value * (1.0 + annual_rate) ** ((month - start_month) / 12.0)
    return values


@dataclass
class WithdrawalResult:
    shortfall: np.ndarray
    from_investable: np.ndarray
    from_emergency: np.ndarray


def _withdraw_from_liquid(
    holdings: np.ndarray,
    emergency: np.ndarray,
    amount: float,
    order: str,
    mask: np.ndarray,
) -> WithdrawalResult:
    """Withdraw a fixed amount from all liquid money.

    The two pools are the investable portfolio (which already includes the cash
    asset) and the emergency fund. ``order`` only changes which pool is used
    first; both are available. Arrays are modified in place.
    """
    need = np.where(mask, amount, 0.0)
    available_investable = holdings.sum(axis=1)

    def take_from_investable(requested: np.ndarray) -> np.ndarray:
        nonlocal holdings
        taken = np.minimum(available_investable, requested)
        ratio = np.where(
            available_investable > 0.0,
            taken / np.maximum(available_investable, 1e-12),
            0.0,
        )
        holdings *= (1.0 - ratio)[:, None]
        return taken

    if order == "emergency_first":
        from_emergency = np.minimum(emergency, need)
        emergency -= from_emergency
        need -= from_emergency
        from_investable = take_from_investable(need)
        need -= from_investable
    else:
        from_investable = take_from_investable(need)
        need -= from_investable
        from_emergency = np.minimum(emergency, need)
        emergency -= from_emergency
        need -= from_emergency
    return WithdrawalResult(
        shortfall=need,
        from_investable=from_investable,
        from_emergency=from_emergency,
    )


def run_simulation(request: ScenarioRequest) -> SimulationOutput:
    household = request.household
    market = request.market
    strategy = request.strategy
    horizon_months = request.horizon_years * 12
    n_paths = request.n_paths
    asset_names = [asset.name for asset in market.assets]
    asset_labels = [asset.label or asset.name for asset in market.assets]
    n_assets = len(asset_names)
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # Market parameters
    # ------------------------------------------------------------------
    mu, sigma = monthly_log_params(
        [asset.expected_real_return for asset in market.assets],
        [asset.volatility for asset in market.assets],
    )
    fee_log = monthly_fee_log([asset.expense_ratio for asset in market.assets])
    chol = cholesky_with_jitter(np.asarray(market.correlation, dtype=float))
    rng = np.random.default_rng(request.seed)
    cash_index = (
        asset_names.index(strategy.cash_asset)
        if strategy.cash_asset in asset_names
        else None
    )

    # ------------------------------------------------------------------
    # Initial balance sheet
    # ------------------------------------------------------------------
    init_liabilities: list[ProjectedLoan] = []
    for liability in household.liabilities:
        schedule = amortization_schedule(
            liability.balance,
            liability.annual_rate,
            liability.remaining_months,
            horizon_months,
            origination_month=1,
            first_payment_month=1,
        )
        init_liabilities.append(
            ProjectedLoan(
                label=liability.name,
                schedule=schedule,
                active=np.ones(n_paths, dtype=bool),
            )
        )

    debt_payment_month_one = sum(
        float(loan.schedule.payments[0]) for loan in init_liabilities
    )

    new_mode = bool(household.holdings) or household.initial_capital <= 0.0
    use_emergency = new_mode and household.emergency_fund_months > 0.0
    projected_assets: list[ProjectedAsset] = []
    initial_illiquid = 0.0
    initial_liquid = 0.0
    initial_emergency = 0.0

    if not new_mode:
        # Legacy single-capital request: no emergency fund, no illiquid assets.
        initial_liquid = float(household.initial_capital)
        weights = target_weights(strategy, asset_names, household.current_age)
        holdings = np.tile(weights * initial_liquid, (n_paths, 1))
        emergency = np.zeros(n_paths, dtype=float)
    else:
        liquid_values = {name: 0.0 for name in asset_names}
        for holding in household.holdings:
            if holding.liquidity == "illiquid" or holding.asset not in asset_names:
                values = _growth_curve(
                    float(holding.value),
                    float(holding.growth_rate),
                    1,
                    horizon_months,
                )
                sale_month = (
                    _event_month(holding.sell_age, household.current_age, horizon_months)
                    if holding.sell_age is not None
                    else None
                )
                income = np.zeros(horizon_months, dtype=float)
                end_income = sale_month - 1 if sale_month is not None else horizon_months
                if end_income >= 1 and holding.monthly_income > 0:
                    income[:end_income] = holding.monthly_income
                asset_index = len(projected_assets)
                linked_loan_indices: list[int] = []
                for loan_index, loan in enumerate(init_liabilities):
                    liability = household.liabilities[loan_index]
                    if (
                        holding.liability_name == liability.name
                        or liability.linked_holding in (holding.label, holding.asset)
                    ):
                        linked_loan_indices.append(loan_index)
                        loan.linked_asset_index = asset_index
                projected_assets.append(
                    ProjectedAsset(
                        label=holding.label or asset_labels[asset_names.index(holding.asset)] if holding.asset in asset_names else (holding.label or holding.asset),
                        asset_kind=holding.asset,
                        values=values,
                        selling_cost_rate=holding.selling_cost_rate,
                        monthly_income=income,
                        monthly_expense=np.zeros(horizon_months, dtype=float),
                        active=np.ones(n_paths, dtype=bool),
                        linked_loans=linked_loan_indices,
                        sale_month=sale_month,
                    )
                )
                initial_illiquid += float(holding.value)
            else:
                liquid_values[holding.asset] += float(holding.value)

        initial_liquid = sum(liquid_values.values())
        initial_event_income = sum(
            float(asset.monthly_income[0]) for asset in projected_assets
        )
        initial_event_expense = sum(
            float(asset.monthly_expense[0]) for asset in projected_assets
        )
        target_zero = household.emergency_fund_months * max(
            0.0,
            household.monthly_expense
            + (debt_payment_month_one if household.emergency_fund_includes_debt else 0.0)
            + initial_event_expense
            - initial_event_income,
        )
        cash_value = liquid_values.get(strategy.cash_asset, 0.0)
        initial_emergency = min(cash_value, max(0.0, target_zero))
        if strategy.cash_asset in liquid_values:
            liquid_values[strategy.cash_asset] -= initial_emergency
        holdings = np.tile(
            np.array([liquid_values[name] for name in asset_names], dtype=float),
            (n_paths, 1),
        )
        emergency = np.full(n_paths, initial_emergency, dtype=float)
        if initial_emergency + 1e-9 < target_zero:
            warnings.append(
                "初始现金低于应急金目标；月结余将优先补足应急金，再投入金融资产。"
            )

    initial_liabilities = sum(
        float(liability.balance) for liability in household.liabilities
    )
    initial_net_worth = initial_liquid + initial_illiquid - initial_liabilities
    initial_investable = float(holdings[0].sum())

    # ------------------------------------------------------------------
    # Life events: purchases, sales, recurring cash flows
    # ------------------------------------------------------------------
    events: list[SimulatedEvent] = []
    event_plans: list[EventPlan] = []
    for event in household.events:
        start_month = _event_month(event.start_age, household.current_age, horizon_months)
        if start_month is None:
            warnings.append(
                f"事件“{event.name}”落在推演区间外"
                f"（当前年龄 {household.current_age:.1f}，事件年龄 {event.start_age:.1f}），已忽略。"
            )
            continue
        end_month = (
            _event_month(event.end_age, household.current_age, horizon_months)
            if event.end_age is not None
            else None
        )
        if end_month is not None and end_month < start_month:
            warnings.append(f"事件“{event.name}”的结束年龄早于开始年龄，已按开始月处理。")
            end_month = start_month

        event_index = len(events)
        requested_window_months = int(round(float(event.window_years) * 12.0))
        if requested_window_months > 0 and start_month + requested_window_months > horizon_months:
            warnings.append(
                f"事件“{event.name}”的时间窗超出推演区间，已截断到期末。"
            )

        if event.purchase is not None:
            purchase = event.purchase
            window_months = requested_window_months
            window_end_month = min(
                horizon_months, start_month + window_months
            )
            action_months = list(range(start_month, window_end_month + 1))
            sale_month = (
                _event_month(purchase.sell_age, household.current_age, horizon_months)
                if purchase.sell_age is not None
                else None
            )
            if sale_month is not None and sale_month <= window_end_month:
                warnings.append(
                    f"事件“{event.name}”的卖出时间不晚于最晚买入时间，已忽略卖出。"
                )
                sale_month = None
            values = _growth_curve(
                float(purchase.price),
                float(purchase.appreciation_rate),
                start_month,
                horizon_months,
            )
            down_payment_ratio = float(purchase.down_payment) / float(purchase.price)
            action_costs = {
                month: down_payment_ratio * float(values[month - 1])
                + float(event.one_off_expense)
                for month in action_months
            }
            purchase_cost = action_costs[start_month]
            income = np.zeros(horizon_months, dtype=float)
            expense = np.zeros(horizon_months, dtype=float)
            recurring_start = start_month + 1
            recurring_end = min(
                end_month if end_month is not None else horizon_months,
                (sale_month - 1) if sale_month is not None else horizon_months,
            )
            if recurring_start <= recurring_end:
                income[recurring_start - 1 : recurring_end] = (
                    float(purchase.monthly_rent) + float(event.monthly_income)
                )
                expense[recurring_start - 1 : recurring_end] = float(
                    event.monthly_expense
                )
            asset_index = len(projected_assets)
            projected_assets.append(
                ProjectedAsset(
                    label=purchase.label or event.name,
                    asset_kind=purchase.asset,
                    values=values,
                    selling_cost_rate=purchase.selling_cost_rate,
                    monthly_income=income,
                    monthly_expense=expense,
                    active=np.zeros(n_paths, dtype=bool),
                    event_index=event_index,
                    purchase_month=start_month,
                    sale_month=sale_month,
                )
            )
            purchase_loan_indices: dict[int, int] = {}
            if purchase.loan_months > 0:
                for action_month in action_months:
                    price_at_purchase = float(values[action_month - 1])
                    loan_principal = max(
                        0.0,
                        price_at_purchase
                        - down_payment_ratio * price_at_purchase,
                    )
                    if loan_principal <= 0.0:
                        continue
                    schedule = amortization_schedule(
                        loan_principal,
                        purchase.loan_annual_rate,
                        purchase.loan_months,
                        horizon_months,
                        origination_month=action_month,
                        first_payment_month=action_month + 1,
                    )
                    loan_index = len(init_liabilities)
                    init_liabilities.append(
                        ProjectedLoan(
                            label=f"{event.name}贷款",
                            schedule=schedule,
                            active=np.zeros(n_paths, dtype=bool),
                            event_index=event_index,
                            linked_asset_index=asset_index,
                        )
                    )
                    projected_assets[asset_index].linked_loans.append(loan_index)
                    purchase_loan_indices[action_month] = loan_index
            events.append(
                SimulatedEvent(
                    name=event.name,
                    event_type="purchase",
                    start_age=float(event.start_age),
                    month=start_month,
                    end_month=end_month,
                    amount=purchase_cost,
                    has_goal=True,
                    window_years=float(event.window_years),
                    window_end_month=window_end_month,
                    window_end_age=household.current_age
                    + (window_end_month - 1) / 12.0,
                )
            )
            event_plans.append(
                EventPlan(
                    index=event_index,
                    name=event.name,
                    event_type="purchase",
                    start_month=start_month,
                    end_month=end_month,
                    start_age=float(event.start_age),
                    one_off_expense=float(event.one_off_expense),
                    has_goal=True,
                    window_months=window_months,
                    window_end_month=window_end_month,
                    action_months=action_months,
                    action_costs=action_costs,
                    purchase_asset_index=asset_index,
                    purchase_loan_indices=purchase_loan_indices,
                    purchase_cost=purchase_cost,
                    completed=np.zeros(n_paths, dtype=bool),
                    failed=np.zeros(n_paths, dtype=bool),
                )
            )
        else:
            income = np.zeros(horizon_months, dtype=float)
            expense = np.zeros(horizon_months, dtype=float)
            last = end_month if end_month is not None else horizon_months
            if last >= start_month and event.monthly_income > 0:
                income[start_month - 1 : last] = float(event.monthly_income)
            if last >= start_month and event.monthly_expense > 0:
                expense[start_month - 1 : last] = float(event.monthly_expense)
            has_goal = event.one_off_expense > 0
            window_months = requested_window_months if has_goal else 0
            if requested_window_months > 0 and not has_goal:
                warnings.append(
                    f"事件“{event.name}”没有一次性支出，时间窗已忽略。"
                )
            window_end_month = min(
                horizon_months, start_month + window_months
            )
            action_months = (
                list(range(start_month, window_end_month + 1))
                if has_goal
                else []
            )
            action_costs = {
                month: float(event.one_off_expense) for month in action_months
            }
            events.append(
                SimulatedEvent(
                    name=event.name,
                    event_type="cashflow",
                    start_age=float(event.start_age),
                    month=start_month,
                    end_month=end_month,
                    amount=float(event.one_off_expense),
                    has_goal=has_goal,
                    window_years=float(event.window_years) if has_goal else 0.0,
                    window_end_month=window_end_month if has_goal else None,
                    window_end_age=(
                        household.current_age + (window_end_month - 1) / 12.0
                        if has_goal
                        else None
                    ),
                )
            )
            event_plans.append(
                EventPlan(
                    index=event_index,
                    name=event.name,
                    event_type="cashflow",
                    start_month=start_month,
                    end_month=end_month,
                    start_age=float(event.start_age),
                    one_off_expense=float(event.one_off_expense),
                    has_goal=has_goal,
                    window_months=window_months,
                    window_end_month=window_end_month if has_goal else None,
                    action_months=action_months,
                    action_costs=action_costs,
                    income=income,
                    expense=expense,
                    completed=(
                        np.zeros(n_paths, dtype=bool) if has_goal else None
                    ),
                    failed=(
                        np.zeros(n_paths, dtype=bool) if has_goal else None
                    ),
                )
            )

    n_events = len(events)
    event_success = np.ones((n_paths, n_events), dtype=bool)
    event_gaps = np.zeros((n_paths, n_events), dtype=float)
    event_action_month = np.full((n_paths, n_events), -1, dtype=int)
    event_action_age = np.full((n_paths, n_events), np.nan, dtype=float)
    event_deadline = np.zeros((n_paths, n_events), dtype=bool)
    event_funding_investable = np.zeros((n_paths, n_events), dtype=float)
    event_funding_emergency = np.zeros((n_paths, n_events), dtype=float)
    event_costs = np.zeros((n_paths, n_events), dtype=float)
    for plan in event_plans:
        if plan.event_type == "purchase" or (
            plan.event_type == "cashflow" and plan.has_goal
        ):
            event_success[:, plan.index] = False

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------
    twr = np.ones(n_paths, dtype=float)
    ruin = np.zeros(n_paths, dtype=bool)
    total_assets = np.empty((n_paths, horizon_months), dtype=float)
    investable_assets = np.empty((n_paths, horizon_months), dtype=float)
    emergency_fund = np.empty((n_paths, horizon_months), dtype=float)
    illiquid_assets = np.empty((n_paths, horizon_months), dtype=float)
    liabilities = np.empty((n_paths, horizon_months), dtype=float)
    net_worth = np.empty((n_paths, horizon_months), dtype=float)
    twr_index = np.empty((n_paths, horizon_months), dtype=float)
    debt_payments = np.empty(horizon_months, dtype=float)
    debt_balances = np.empty(horizon_months, dtype=float)

    total_contributions = 0.0
    total_event_withdrawals = 0.0
    total_debt_interest = 0.0

    for month in range(1, horizon_months + 1):
        age = household.current_age + (month - 1) / 12.0

        # 1) Sales at the start of the month. The sold asset and its linked
        #    loans leave the balance sheet; net proceeds enter the cash pool.
        sale_pool = np.zeros(n_paths, dtype=float)
        for asset_index, asset in enumerate(projected_assets):
            if asset.sale_month != month:
                continue
            active_before = asset.active.copy()
            proceeds = np.full(
                n_paths,
                asset.values[month - 1] * (1.0 - asset.selling_cost_rate),
                dtype=float,
            )
            for loan_index in asset.linked_loans:
                loan = init_liabilities[loan_index]
                # A time-window purchase creates one possible loan per month.
                # Only the loan belonging to a path's actual purchase month is
                # active and may be repaid from the sale proceeds.
                proceeds -= (
                    float(loan.schedule.balances_start[month - 1])
                    * loan.active.astype(float)
                )
                loan.active[:] = False
            sale_pool += proceeds * active_before
            asset.active[:] = False

        # 2) Debt service and recurring cash flows.
        debt_payment = sum(
            float(loan.schedule.payments[month - 1]) * loan.active
            for loan in init_liabilities
        )
        debt_interest = sum(
            float(loan.schedule.interest[month - 1]) * loan.active
            for loan in init_liabilities
        )
        income = household.monthly_income * (
            1.0 + household.income_growth_real
        ) ** ((month - 1) / 12.0)
        expense = household.monthly_expense * (
            1.0 + household.expense_growth_real
        ) ** ((month - 1) / 12.0)

        event_income = np.zeros(n_paths, dtype=float)
        event_expense = np.zeros(n_paths, dtype=float)
        for plan in event_plans:
            if plan.event_type == "cashflow":
                event_income += plan.income[month - 1]
                event_expense += plan.expense[month - 1]
        for asset in projected_assets:
            event_income += asset.monthly_income[month - 1] * asset.active
            event_expense += asset.monthly_expense[month - 1] * asset.active

        debt_payment_total = np.asarray(debt_payment, dtype=float)
        if debt_payment_total.ndim == 0:
            debt_payment_total = np.full(n_paths, float(debt_payment_total))
        net_cash = income - expense - debt_payment_total + event_income - event_expense

        if use_emergency:
            target = household.emergency_fund_months * np.maximum(
                0.0,
                expense
                + (debt_payment_total if household.emergency_fund_includes_debt else 0.0)
                + event_expense
                - event_income,
            )
            target = np.asarray(target, dtype=float)
            if target.ndim == 0:
                target = np.full(n_paths, float(target))
        else:
            target = np.zeros(n_paths, dtype=float)

        # 3) Apply monthly surplus/deficit and sale proceeds.
        cash = net_cash + sale_pool
        positive = cash >= 0.0
        topup = np.where(positive, np.minimum(cash, np.maximum(0.0, target - emergency)), 0.0)
        emergency += topup
        invest = np.where(positive, cash - topup, 0.0)
        if np.any(invest > 0.0):
            weights = target_weights(strategy, asset_names, age)
            holdings += invest[:, None] * weights[None, :]
            total_contributions += float(np.mean(invest))

        need = np.where(~positive, -cash, 0.0)
        if np.any(need > 0.0):
            from_emergency = np.minimum(emergency, need)
            emergency -= from_emergency
            need -= from_emergency
            available = holdings.sum(axis=1)
            take = np.minimum(available, need)
            ratio = np.where(available > 0.0, take / np.maximum(available, 1e-12), 0.0)
            holdings *= (1.0 - ratio)[:, None]
            need -= take
            ruin |= need > 1e-9

        # 4) Planned events at this month. Goal events with a time window are
        #    checked every month; the first affordable month completes them.
        #    At the last action month the engine falls back to selling all
        #    available financial assets (investable assets + emergency fund).
        for plan in event_plans:
            if not plan.has_goal or month not in plan.action_months:
                continue
            if plan.completed is None or plan.failed is None:
                continue
            pending = ~plan.completed & ~plan.failed
            if not np.any(pending):
                continue
            cost = float(plan.action_costs.get(month, plan.one_off_expense))
            liquid_total = holdings.sum(axis=1) + emergency
            can_pay = pending & (liquid_total >= cost - 1e-9)
            is_last_action = month == plan.action_months[-1]
            is_window_deadline = (
                plan.window_months > 0 and month == plan.window_end_month
            )

            if np.any(can_pay):
                withdrawal = _withdraw_from_liquid(
                    holdings,
                    emergency,
                    cost,
                    household.event_withdrawal_order,
                    can_pay,
                )
                event_success[can_pay, plan.index] = True
                event_gaps[can_pay, plan.index] = 0.0
                event_action_month[can_pay, plan.index] = month
                event_action_age[can_pay, plan.index] = age
                event_deadline[can_pay, plan.index] = is_window_deadline
                event_funding_investable[can_pay, plan.index] = (
                    withdrawal.from_investable[can_pay]
                )
                event_funding_emergency[can_pay, plan.index] = (
                    withdrawal.from_emergency[can_pay]
                )
                event_costs[can_pay, plan.index] = cost
                if plan.event_type == "purchase":
                    asset = projected_assets[plan.purchase_asset_index]  # type: ignore[index]
                    asset.active[can_pay] = True
                    loan_index = plan.purchase_loan_indices.get(month)
                    if loan_index is not None:
                        init_liabilities[loan_index].active[can_pay] = True
                plan.completed[can_pay] = True
                total_event_withdrawals += float(
                    np.mean(np.where(can_pay, cost, 0.0))
                )

            if is_last_action:
                forced = pending & ~can_pay
                if not np.any(forced):
                    continue
                if plan.event_type == "purchase":
                    # A purchase needs the full down payment. All financial
                    # assets were available and still insufficient, so this
                    # path does not buy. Non-liquid assets are not auto-sold.
                    event_gaps[forced, plan.index] = np.maximum(
                        0.0, cost - liquid_total[forced]
                    )
                    event_success[forced, plan.index] = False
                    event_costs[forced, plan.index] = cost
                    plan.failed[forced] = True
                else:
                    # A one-off expense is paid as far as possible by selling
                    # all financial assets; the rest is a recorded gap. A
                    # partial payment is a failure and does not enter the
                    # timing distribution.
                    withdrawal = _withdraw_from_liquid(
                        holdings,
                        emergency,
                        cost,
                        household.event_withdrawal_order,
                        forced,
                    )
                    event_gaps[forced, plan.index] = withdrawal.shortfall[forced]
                    event_success[forced, plan.index] = (
                        withdrawal.shortfall[forced] <= 1e-9
                    )
                    event_costs[forced, plan.index] = cost
                    event_funding_investable[forced, plan.index] = (
                        withdrawal.from_investable[forced]
                    )
                    event_funding_emergency[forced, plan.index] = (
                        withdrawal.from_emergency[forced]
                    )
                    fully_paid = forced & (withdrawal.shortfall <= 1e-9)
                    if np.any(fully_paid):
                        event_action_month[fully_paid, plan.index] = month
                        event_action_age[fully_paid, plan.index] = age
                        event_deadline[fully_paid, plan.index] = is_window_deadline
                        plan.completed[fully_paid] = True
                    plan.failed[forced & ~fully_paid] = True
                    total_event_withdrawals += float(
                        np.mean(np.where(forced, cost - withdrawal.shortfall, 0.0))
                    )

        # 5) If the emergency fund is above target (e.g. after a sale or a
        #    paid-off loan), invest the excess.
        excess = np.maximum(0.0, emergency - target)
        if np.any(excess > 0.0):
            emergency -= excess
            weights = target_weights(strategy, asset_names, age)
            holdings += excess[:, None] * weights[None, :]
            total_contributions += float(np.mean(excess))

        # 6) Rebalance.
        should_rebalance = strategy.rebalance == "monthly" or (
            strategy.rebalance == "annual" and month % 12 == 0
        )
        if should_rebalance:
            total = holdings.sum(axis=1)
            weights = target_weights(strategy, asset_names, age)
            holdings = total[:, None] * weights[None, :]

        # 7) Market returns on the investable portfolio.
        shocks = draw_standardized_shocks(rng, n_paths, n_assets, market.student_t_df)
        correlated = shocks @ chol.T
        log_returns = mu[None, :] + sigma[None, :] * correlated + fee_log[None, :]
        log_returns = np.clip(log_returns, -50.0, 50.0)
        growth = np.exp(log_returns)
        value_before_return = holdings.sum(axis=1)
        holdings *= growth
        value_end = holdings.sum(axis=1)
        monthly_return = np.where(
            value_before_return > 0.0,
            value_end / np.maximum(value_before_return, 1e-12) - 1.0,
            0.0,
        )
        twr *= 1.0 + monthly_return

        # 8) Cash return on the emergency fund.
        if cash_index is not None:
            emergency *= growth[:, cash_index]

        # 9) Balance sheet at month end.
        investable_total = holdings.sum(axis=1)
        illiquid_total = sum(
            asset.values[month - 1] * asset.active for asset in projected_assets
        )
        if not isinstance(illiquid_total, np.ndarray):
            illiquid_total = np.full(n_paths, float(illiquid_total))
        debt_balance = sum(
            float(loan.schedule.balances_end[month - 1]) * loan.active
            for loan in init_liabilities
        )
        if not isinstance(debt_balance, np.ndarray):
            debt_balance = np.full(n_paths, float(debt_balance))
        liquid_total = investable_total + emergency
        total_assets[:, month - 1] = liquid_total
        investable_assets[:, month - 1] = investable_total
        emergency_fund[:, month - 1] = emergency
        illiquid_assets[:, month - 1] = illiquid_total
        liabilities[:, month - 1] = debt_balance
        net_worth[:, month - 1] = liquid_total + illiquid_total - debt_balance
        twr_index[:, month - 1] = twr
        debt_payments[month - 1] = float(np.mean(debt_payment_total))
        debt_balances[month - 1] = float(np.mean(debt_balance))
        total_debt_interest += float(np.mean(debt_interest))

    if household.monthly_income - household.monthly_expense - debt_payment_month_one < 0.0:
        warnings.append("首月现金流为负：收入不足以覆盖支出和月供，缺口由金融资产支付。")
    if bool(np.any(ruin)):
        warnings.append("部分路径在执行过程中耗尽了金融资产。")

    final_illiquid = sum(
        asset.values[-1] * asset.active for asset in projected_assets
    )
    if not isinstance(final_illiquid, np.ndarray):
        final_illiquid = np.full(n_paths, float(final_illiquid))
    final_debt = sum(
        float(loan.schedule.balances_end[-1]) * loan.active
        for loan in init_liabilities
    )
    if not isinstance(final_debt, np.ndarray):
        final_debt = np.full(n_paths, float(final_debt))

    return SimulationOutput(
        months=np.arange(1, horizon_months + 1),
        total_assets=total_assets,
        investable_assets=investable_assets,
        emergency_fund=emergency_fund,
        illiquid_assets=illiquid_assets,
        liabilities=liabilities,
        net_worth=net_worth,
        twr_index=twr_index,
        event_success=event_success,
        event_gaps=event_gaps,
        event_action_month=event_action_month,
        event_action_age=event_action_age,
        event_deadline=event_deadline,
        event_funding_investable=event_funding_investable,
        event_funding_emergency=event_funding_emergency,
        event_costs=event_costs,
        events=events,
        ruin=ruin,
        debt_payments=debt_payments,
        debt_balances=debt_balances,
        total_contributions=total_contributions,
        total_event_withdrawals=total_event_withdrawals,
        total_debt_interest=total_debt_interest,
        initial_liquid=initial_liquid,
        initial_emergency=initial_emergency,
        initial_illiquid=initial_illiquid,
        initial_liabilities=initial_liabilities,
        initial_net_worth=initial_net_worth,
        final_holdings=holdings,
        final_emergency=emergency,
        final_illiquid=final_illiquid,
        final_liabilities=final_debt,
        warnings=warnings,
    )
