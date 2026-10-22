from __future__ import annotations

from datetime import date
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator

AssetRole = Literal["growth", "defensive", "cash", "illiquid"]
Liquidity = Literal["liquid", "illiquid"]
WithdrawalOrder = Literal["investments_first", "emergency_first"]


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AssetAssumption(BaseModel):
    name: str = Field(min_length=1)
    label: str = ""
    role: AssetRole = "growth"
    # Annualized geometric return, already net of inflation (today's purchasing power).
    expected_real_return: float = Field(ge=-0.99, le=1.0)
    volatility: float = Field(ge=0.0, le=2.0)
    expense_ratio: float = Field(default=0.0, ge=0.0, le=0.2)
    liquid: bool = True


class MarketAssumptions(BaseModel):
    assets: list[AssetAssumption] = Field(min_length=1)
    correlation: list[list[float]]
    student_t_df: float = Field(default=5.0, gt=2.0, le=100.0)

    @model_validator(mode="after")
    def _validate_correlation(self) -> "MarketAssumptions":
        n = len(self.assets)
        if len(self.correlation) != n or any(len(row) != n for row in self.correlation):
            raise ValueError("correlation matrix must be n x n")
        for i in range(n):
            if abs(self.correlation[i][i] - 1.0) > 1e-9:
                raise ValueError("correlation diagonal must be 1")
            for j in range(n):
                value = self.correlation[i][j]
                if abs(value - self.correlation[j][i]) > 1e-9:
                    raise ValueError("correlation matrix must be symmetric")
                if not (-1.0 <= value <= 1.0):
                    raise ValueError("correlation entries must be in [-1, 1]")
        eigenvalues = np.linalg.eigvalsh(np.asarray(self.correlation, dtype=float))
        if float(eigenvalues.min()) < -1e-8:
            raise ValueError("correlation matrix must be positive semidefinite")
        return self


class Liability(BaseModel):
    name: str = "房贷"
    balance: float = Field(ge=0.0)
    annual_rate: float = Field(ge=0.0, le=1.0)
    remaining_months: int = Field(ge=1, le=600)
    # Optional link to an initial holding that this loan finances. On sale,
    # the remaining balance is repaid from the proceeds.
    linked_holding: str | None = None


class InitialHolding(BaseModel):
    asset: str = Field(min_length=1)
    label: str = ""
    value: float = Field(ge=0.0)
    liquidity: Liquidity = "liquid"
    # Used by illiquid holdings.
    growth_rate: float = Field(default=0.0, ge=-0.5, le=0.2)
    monthly_income: float = Field(default=0.0, ge=0.0)
    selling_cost_rate: float = Field(default=0.0, ge=0.0, le=0.2)
    sell_age: float | None = Field(default=None, ge=0.0, le=120.0)
    liability_name: str | None = None


class AssetPurchase(BaseModel):
    asset: str = "real_estate"
    label: str = ""
    price: float = Field(gt=0.0)
    down_payment: float = Field(ge=0.0)
    loan_annual_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    loan_months: int = Field(default=0, ge=0, le=600)
    appreciation_rate: float = Field(default=0.0, ge=-0.5, le=0.2)
    monthly_rent: float = Field(default=0.0, ge=0.0)
    selling_cost_rate: float = Field(default=0.0, ge=0.0, le=0.2)
    sell_age: float | None = Field(default=None, ge=0.0, le=120.0)

    @model_validator(mode="after")
    def _validate_purchase(self) -> "AssetPurchase":
        if self.down_payment > self.price + 1e-6:
            raise ValueError("down_payment cannot exceed price")
        if self.loan_months == 0 and self.price - self.down_payment > 1e-6:
            # A zero-term loan is interpreted as no loan; require full payment.
            if self.down_payment + 1e-6 < self.price:
                raise ValueError("loan_months must be > 0 when the purchase is financed")
        return self


class LifeEvent(BaseModel):
    name: str = Field(min_length=1)
    start_age: float | None = Field(default=None, ge=0.0, le=120.0)
    end_age: float | None = Field(default=None, ge=0.0, le=120.0)
    # Approximate timing window. The event is checked every month from
    # start_age through start_age + window_years. 0 means the exact start month.
    window_years: float = Field(default=0.0, ge=0.0, le=30.0)
    one_off_expense: float = Field(default=0.0, ge=0.0)
    monthly_income: float = Field(default=0.0, ge=0.0)
    monthly_expense: float = Field(default=0.0, ge=0.0)
    purchase: AssetPurchase | None = None

    # Legacy fields from the first MVP; mapped below.
    age: float | None = Field(default=None, ge=0.0, le=120.0)
    amount: float | None = Field(default=None, ge=0.0)
    mandatory: bool = True

    @model_validator(mode="before")
    @classmethod
    def _map_legacy(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if data.get("start_age") is None and data.get("age") is not None:
                data["start_age"] = data["age"]
            if not data.get("one_off_expense") and data.get("amount") is not None:
                data["one_off_expense"] = data["amount"]
        return data

    @model_validator(mode="after")
    def _validate_event(self) -> "LifeEvent":
        if self.start_age is None:
            raise ValueError("event requires start_age (or legacy age)")
        if self.end_age is not None and self.end_age < self.start_age:
            raise ValueError("end_age must be greater than or equal to start_age")
        if self.window_years > 0.0:
            if self.purchase is None and self.one_off_expense <= 0.0:
                raise ValueError(
                    "window_years requires a purchase or a one_off_expense"
                )
            if (
                self.purchase is not None
                and self.purchase.sell_age is not None
                and self.purchase.sell_age <= self.start_age + self.window_years
            ):
                raise ValueError(
                    "purchase.sell_age must be greater than "
                    "start_age + window_years"
                )
        elif self.purchase is not None:
            if (
                self.purchase.sell_age is not None
                and self.purchase.sell_age <= self.start_age
            ):
                raise ValueError("purchase.sell_age must be greater than start_age")
        return self


class Household(BaseModel):
    current_age: float = Field(ge=0.0, le=120.0)
    # Legacy single initial capital. Ignored when holdings are provided.
    initial_capital: float = Field(default=0.0, ge=0.0)
    holdings: list[InitialHolding] = Field(default_factory=list)
    monthly_income: float = Field(ge=0.0)
    monthly_expense: float = Field(ge=0.0)
    income_growth_real: float = Field(default=0.0, ge=-0.2, le=0.2)
    expense_growth_real: float = Field(default=0.0, ge=-0.2, le=0.2)
    liabilities: list[Liability] = Field(default_factory=list)
    events: list[LifeEvent] = Field(default_factory=list)
    emergency_fund_months: float = Field(default=10.0, ge=0.0, le=60.0)
    emergency_fund_includes_debt: bool = True
    event_withdrawal_order: WithdrawalOrder = "investments_first"

    @model_validator(mode="after")
    def _validate_links(self) -> "Household":
        liability_names = [item.name for item in self.liabilities]
        if len(set(liability_names)) != len(liability_names):
            raise ValueError("liability names must be unique")
        linked = set(liability_names)
        for holding in self.holdings:
            if holding.liability_name and holding.liability_name not in linked:
                raise ValueError(
                    f"holding {holding.label or holding.asset!r} links to unknown liability "
                    f"{holding.liability_name!r}"
                )
        return self


class StrategySpec(BaseModel):
    kind: Literal["constant", "glide", "all_equity"] = "glide"
    # Constant mode: target weights across all market assets.
    weights: dict[str, float] | None = None

    # Glide mode: a growth sleeve and a defensive sleeve. The glide controls
    # the total growth weight; the sleeve compositions stay fixed.
    growth_assets: list[str] = Field(default_factory=list)
    growth_weights: dict[str, float] = Field(default_factory=dict)
    defensive_assets: list[str] = Field(default_factory=list)
    defensive_weights: dict[str, float] = Field(default_factory=dict)
    cash_asset: str = "cash"
    cash_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    growth_start: float = Field(default=0.8, ge=0.0, le=1.0)
    growth_end: float = Field(default=0.4, ge=0.0, le=1.0)
    glide_start_age: float = Field(default=30.0, ge=0.0, le=120.0)
    glide_end_age: float = Field(default=60.0, ge=0.0, le=120.0)
    floor: float = Field(default=0.0, ge=0.0, le=1.0)
    cap: float = Field(default=1.0, ge=0.0, le=1.0)
    rebalance: Literal["monthly", "annual", "none"] = "annual"

    # Legacy fields from the first MVP; used to synthesize the sleeves.
    equity_start: float | None = Field(default=None, ge=0.0, le=1.0)
    equity_end: float | None = Field(default=None, ge=0.0, le=1.0)
    equity_asset: str = "equity"
    bond_asset: str = "bond"

    @model_validator(mode="after")
    def _normalize_sleeves(self) -> "StrategySpec":
        if self.kind == "all_equity":
            self.growth_assets = [self.equity_asset]
            self.growth_weights = {self.equity_asset: 1.0}
            self.growth_start = 1.0
            self.growth_end = 1.0
            self.defensive_assets = []
            self.defensive_weights = {}
            self.cash_weight = 0.0
        elif self.kind == "glide" and not self.growth_assets:
            # Legacy glide: one equity asset and one bond asset.
            self.growth_assets = [self.equity_asset]
            self.growth_weights = {self.equity_asset: 1.0}
            if self.equity_start is not None:
                self.growth_start = self.equity_start
            if self.equity_end is not None:
                self.growth_end = self.equity_end
            if self.bond_asset:
                self.defensive_assets = [self.bond_asset]
                self.defensive_weights = {self.bond_asset: 1.0}
            self.cash_weight = 0.0

        if self.kind == "glide":
            if not self.growth_assets:
                raise ValueError("glide strategy requires at least one growth asset")
            if self.glide_end_age <= self.glide_start_age:
                raise ValueError("glide_end_age must be greater than glide_start_age")
            if self.floor > self.cap:
                raise ValueError("floor must be less than or equal to cap")
            if self.cash_weight > 1.0:
                raise ValueError("cash_weight must be at most 1")
            if self.cash_asset in self.growth_assets or self.cash_asset in self.defensive_assets:
                raise ValueError("cash_asset must not be in growth/defensive sleeves")
            if set(self.growth_assets) & set(self.defensive_assets):
                raise ValueError("growth and defensive assets must be disjoint")
            if not self.growth_weights:
                equal = 1.0 / len(self.growth_assets)
                self.growth_weights = {asset: equal for asset in self.growth_assets}
            if self.defensive_assets and not self.defensive_weights:
                equal = 1.0 / len(self.defensive_assets)
                self.defensive_weights = {
                    asset: equal for asset in self.defensive_assets
                }
            for asset, weight in self.growth_weights.items():
                if asset not in self.growth_assets:
                    raise ValueError(f"growth weight for unknown asset {asset!r}")
                if weight < 0:
                    raise ValueError("growth weights must be non-negative")
            for asset, weight in self.defensive_weights.items():
                if asset not in self.defensive_assets:
                    raise ValueError(f"defensive weight for unknown asset {asset!r}")
                if weight < 0:
                    raise ValueError("defensive weights must be non-negative")
            if sum(self.growth_weights.values()) <= 0:
                raise ValueError("growth weights must sum to a positive value")
            if self.defensive_weights and sum(self.defensive_weights.values()) <= 0:
                raise ValueError("defensive weights must sum to a positive value")
        return self


class ScenarioRequest(BaseModel):
    name: str = "基准"
    market: MarketAssumptions
    household: Household
    strategy: StrategySpec
    horizon_years: int = Field(default=10, ge=1, le=50)
    n_paths: int = Field(default=10000, ge=100, le=100000)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    include_explanation: bool = True
    data_version: str = "none"
    calibration_window: str | None = None
    # Optional single terminal-wealth goal. 0 means no goal. The simple
    # DCA page uses this; the full scenario page leaves it at 0.
    goal_amount: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _validate_consistency(self) -> "ScenarioRequest":
        names = [asset.name for asset in self.market.assets]
        if len(set(names)) != len(names):
            raise ValueError("asset names must be unique")
        name_set = set(names)

        if self.strategy.kind == "constant":
            if not self.strategy.weights:
                raise ValueError("constant strategy requires weights")
            missing = name_set - set(self.strategy.weights)
            extra = set(self.strategy.weights) - name_set
            if missing or extra:
                raise ValueError(
                    f"weights must cover exactly the asset names (missing={sorted(missing)}, extra={sorted(extra)})"
                )
            if any(weight < 0 for weight in self.strategy.weights.values()):
                raise ValueError("weights must be non-negative")
            total = sum(self.strategy.weights.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError("weights must sum to 1")
        else:
            for asset in self.strategy.growth_assets:
                if asset not in name_set:
                    raise ValueError(f"unknown growth asset {asset!r}")
            for asset in self.strategy.defensive_assets:
                if asset not in name_set:
                    raise ValueError(f"unknown defensive asset {asset!r}")
            if self.strategy.cash_weight > 0 and self.strategy.cash_asset not in name_set:
                raise ValueError(f"missing cash asset {self.strategy.cash_asset!r}")

        for holding in self.household.holdings:
            if holding.liquidity == "liquid" and holding.asset not in name_set:
                raise ValueError(
                    f"liquid holding {holding.label or holding.asset!r} is not a market asset"
                )
        return self


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class PercentilePoint(BaseModel):
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


class PercentileBand(BaseModel):
    p5: list[float]
    p25: list[float]
    p50: list[float]
    p75: list[float]
    p95: list[float]


class DrawdownSummary(BaseModel):
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    hist_edges: list[float]
    hist_counts: list[int]


class TimingPoint(BaseModel):
    age: float
    # Cumulative share of all simulated paths that completed the event by this age.
    probability: float


class EventResult(BaseModel):
    name: str
    age: float
    amount: float
    month: int
    success_probability: float
    success_ci95_low: float
    success_ci95_high: float
    mean_gap: float
    p50_gap: float
    event_type: Literal["cashflow", "purchase"] = "cashflow"
    has_goal: bool = True

    # Timing-window fields. They remain at their defaults for events without a
    # window and for old snapshots.
    window_years: float = 0.0
    window_start_age: float | None = None
    window_end_age: float | None = None
    natural_success_probability: float | None = None
    deadline_success_probability: float | None = None
    failure_probability: float | None = None
    median_action_age: float | None = None
    action_age_p25: float | None = None
    action_age_p75: float | None = None
    median_cost: float | None = None
    funding_investable_mean: float | None = None
    funding_emergency_mean: float | None = None
    funding_emergency_share_mean: float | None = None
    timing: list[TimingPoint] = Field(default_factory=list)


class CompositionItem(BaseModel):
    label: str
    value: float
    kind: Literal["investable", "emergency", "illiquid", "liability"]


class RunMetrics(BaseModel):
    months: list[int]
    years: list[float]
    assets: PercentileBand
    net_worth: PercentileBand
    terminal_assets: PercentilePoint
    terminal_net_worth: PercentilePoint
    max_drawdown: DrawdownSummary
    annualized_twr: PercentilePoint
    events: list[EventResult]
    joint_shortfall_probability: float
    joint_shortfall_ci95_low: float
    joint_shortfall_ci95_high: float
    ruin_probability: float
    ruin_ci95_low: float
    ruin_ci95_high: float
    total_contributions: float
    total_event_withdrawals: float
    total_debt_interest: float
    initial_capital: float
    monthly_surplus: float
    monthly_debt_payment: float
    goal_amount: float = 0.0
    goal_probability: float = 0.0
    goal_ci95_low: float = 0.0
    goal_ci95_high: float = 0.0

    # New in the household-balance-sheet version. Optional so old snapshots
    # remain readable.
    emergency_fund: PercentileBand | None = None
    illiquid_assets: PercentileBand | None = None
    liabilities: PercentileBand | None = None
    terminal_emergency_fund: PercentilePoint | None = None
    terminal_illiquid_assets: PercentilePoint | None = None
    terminal_liabilities: PercentilePoint | None = None
    terminal_composition: list[CompositionItem] = Field(default_factory=list)
    emergency_fund_target_months: float = 0.0
    initial_net_worth: float | None = None
    initial_emergency_fund: float | None = None
    initial_illiquid_assets: float | None = None
    initial_liabilities: float | None = None


class Explanation(BaseModel):
    summary: str
    bullets: list[str]
    caveats: list[str]
    metric_refs: list[str]
    source: Literal["template", "llm"]
    model: str | None = None
    warnings: list[str] = Field(default_factory=list)
    templates: dict | None = None


class AnalysisRequest(BaseModel):
    """On-demand LLM analysis for an existing run."""

    mode: Literal["simple", "full", "history"]
    run_id: str = Field(min_length=4, max_length=64)
    force: bool = False


class AnalysisMetric(BaseModel):
    key: str
    label: str
    value: float
    formatted: str
    delta: float | None = None
    delta_formatted: str | None = None
    better: Literal["better", "worse", "neutral"] = "neutral"


class WhatIfVariant(BaseModel):
    key: str
    label: str
    description: str
    changes: dict[str, Any] = Field(default_factory=dict)
    metrics: list[AnalysisMetric] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    analysis_id: str
    created_at: str
    mode: Literal["simple", "full", "history"]
    run_id: str
    source: Literal["template", "llm"]
    model: str | None = None
    summary: str
    findings: list[str]
    suggestions: list[str]
    caveats: list[str]
    metric_refs: list[str]
    metric_order: list[str] = Field(default_factory=list)
    metric_labels: dict[str, str] = Field(default_factory=dict)
    variants: list[WhatIfVariant] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    templates: dict | None = None
    warnings: list[str] = Field(default_factory=list)
    code_version: str
    code_fingerprint: str
    data_version: str = "none"
    disclaimer: str = "以上为情景推演与局部 what-if 分析，不构成投资建议。"


class RunResponse(BaseModel):
    run_id: str
    created_at: str
    request: ScenarioRequest
    metrics: RunMetrics
    explanation: Explanation
    warnings: list[str] = Field(default_factory=list)
    code_version: str
    code_fingerprint: str
    data_version: str = "none"


class HistoryRequest(BaseModel):
    """Historical DCA backtest request.

    A single asset or a multi-asset portfolio; the period is either a lookback
    from the end date or explicit start/end dates.
    """

    mode: Literal["single", "portfolio"] = "single"
    asset: str = "gold"
    weights: dict[str, float] = Field(default_factory=dict)
    initial_capital: float = Field(default=0.0, ge=0.0)
    monthly_contribution: float = Field(default=0.0, ge=0.0)
    start_date: date | None = None
    end_date: date | None = None
    lookback_years: float | None = Field(default=10.0, gt=0.0, le=50.0)
    rebalance: Literal["annual", "none"] = "annual"

    @model_validator(mode="after")
    def _validate_history(self) -> "HistoryRequest":
        if self.initial_capital <= 0.0 and self.monthly_contribution <= 0.0:
            raise ValueError("initial capital or monthly contribution must be positive")
        if self.mode == "portfolio":
            if not self.weights:
                raise ValueError("portfolio mode requires weights")
            if any(weight < 0.0 for weight in self.weights.values()):
                raise ValueError("weights must be non-negative")
            total = sum(self.weights.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError("weights must sum to 1")
        if self.start_date is None and self.lookback_years is None:
            raise ValueError("provide start_date or lookback_years")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date >= self.end_date
        ):
            raise ValueError("start_date must be before end_date")
        return self


class HistoryPoint(BaseModel):
    date: date
    value: float
    invested: float


class HistoryAssetValue(BaseModel):
    asset: str
    label: str
    value: float
    weight: float


class HistoryResponse(BaseModel):
    run_id: str
    created_at: str
    request: HistoryRequest
    data_version: str
    code_version: str
    code_fingerprint: str
    requested_start_date: date
    requested_end_date: date
    effective_start_date: date
    effective_end_date: date
    months: int
    contribution_count: int
    initial_capital: float
    monthly_contribution: float
    total_invested: float
    terminal_value: float
    profit: float
    return_on_invested: float
    irr_annual: float | None
    max_drawdown: float
    drawdown_peak_date: date | None
    drawdown_trough_date: date | None
    path: list[HistoryPoint]
    yearly: list[HistoryPoint]
    final_composition: list[HistoryAssetValue]
    warnings: list[str] = Field(default_factory=list)


class HistoryAssetMeta(BaseModel):
    name: str
    label: str
    source: str
    start: date
    end: date


class HistoryMetaResponse(BaseModel):
    data_version: str
    inflation_assumption: float
    latest_date: date
    assets: list[HistoryAssetMeta]
    disclaimer: str


CashflowDirection = Literal[
    "income", "expense", "transfer", "investment", "ignore"
]
InvestmentBucket = Literal["cash", "a_share", "overseas", "gold", "bond", "other"]
InvestmentAction = Literal["buy", "sell"]
CashflowRuleField = Literal["counterparty", "description", "category", "any"]


class CashflowMapping(BaseModel):
    date: str = ""
    amount: str = ""
    income_amount: str | None = None
    expense_amount: str | None = None
    direction: str | None = None
    counterparty: str | None = None
    description: str | None = None
    category: str | None = None
    account: str | None = None
    status: str | None = None
    header_row: int = 0
    amount_mode: Literal[
        "signed", "positive_expense", "absolute", "two_columns"
    ] = "signed"
    direction_values: dict[str, CashflowDirection] = Field(
        default_factory=lambda: {
            "收入": "income",
            "支出": "expense",
            "不计收支": "ignore",
            "中性交易": "ignore",
            "/": "ignore",
            "—": "ignore",
            "转账": "transfer",
            "income": "income",
            "expense": "expense",
            "credit": "income",
            "debit": "expense",
            "贷": "income",
            "借": "expense",
        }
    )


class CashflowPreview(BaseModel):
    headers: list[str]
    rows: list[dict[str, str]]
    suggested_mapping: CashflowMapping
    header_row: int
    encoding: str
    total_rows: int


class CashflowTransaction(BaseModel):
    id: int
    import_id: str
    source: str
    account: str
    date: date
    amount: float
    direction: CashflowDirection
    category: str
    bucket: InvestmentBucket | None = None
    investment_action: InvestmentAction | None = None
    counterparty: str = ""
    description: str = ""
    raw_category: str = ""
    is_one_off: bool = False
    note: str = ""
    category_source: Literal["rule", "manual", "import"] = "rule"
    fingerprint: str = ""
    raw_json: str = ""
    created_at: str = ""


class CashflowTransactionList(BaseModel):
    items: list[CashflowTransaction]
    total: int


class CashflowTransactionPatch(BaseModel):
    direction: CashflowDirection | None = None
    category: str | None = None
    bucket: InvestmentBucket | None = None
    investment_action: InvestmentAction | None = None
    is_one_off: bool | None = None
    note: str | None = None


class CashflowRule(BaseModel):
    id: int
    priority: int = 0
    pattern: str
    match_field: CashflowRuleField = "any"
    direction: CashflowDirection | None = None
    category: str
    bucket: InvestmentBucket | None = None
    investment_action: InvestmentAction | None = None
    enabled: bool = True
    note: str = ""


class CashflowRuleInput(BaseModel):
    priority: int = 0
    pattern: str = Field(min_length=1)
    match_field: CashflowRuleField = "any"
    direction: CashflowDirection | None = None
    category: str = Field(min_length=1)
    bucket: InvestmentBucket | None = None
    investment_action: InvestmentAction | None = None
    enabled: bool = True
    note: str = ""


class CashflowBalanceInput(BaseModel):
    date: date
    bucket: InvestmentBucket
    balance: float = Field(ge=0.0)
    note: str = ""


class CashflowBalance(BaseModel):
    id: int
    date: date
    bucket: InvestmentBucket
    balance: float
    note: str = ""
    source: str = "manual"
    updated_at: str = ""


class CashflowMonth(BaseModel):
    month: str
    income: float
    expense: float
    net_savings: float
    savings_rate: float | None = None
    income_recurring: float
    expense_recurring: float
    net_savings_recurring: float
    savings_rate_recurring: float | None = None
    investment_buy: float
    investment_sell: float
    investment_net: float
    bucket_buy: dict[str, float] = Field(default_factory=dict)
    one_off_income: float
    one_off_expense: float
    transaction_count: int
    uncategorized_count: int


class CashflowCategoryTotal(BaseModel):
    category: str
    amount: float
    one_off_amount: float
    share: float
    count: int


class CashflowBucketFlow(BaseModel):
    bucket: InvestmentBucket
    buy: float
    sell: float
    net: float
    buy_share: float


class CashflowBalancePoint(BaseModel):
    month: str
    balances: dict[str, float]
    total: float


class CashflowSummary(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    latest_month: str | None = None
    inflation_assumption: float = 0.02
    months: list[CashflowMonth] = Field(default_factory=list)
    income_categories: list[CashflowCategoryTotal] = Field(default_factory=list)
    expense_categories: list[CashflowCategoryTotal] = Field(default_factory=list)
    investment_buckets: list[CashflowBucketFlow] = Field(default_factory=list)
    balances: list[CashflowBalancePoint] = Field(default_factory=list)
    latest_balances: dict[str, float] = Field(default_factory=dict)
    total_income: float = 0.0
    total_expense: float = 0.0
    total_net_savings: float = 0.0
    savings_rate: float | None = None
    transaction_count: int = 0
    uncategorized_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class CashflowAssumptionPreview(BaseModel):
    monthly_income: float
    monthly_expense: float
    savings_rate: float | None = None
    months_used: int
    window_start: str
    window_end: str
    excluded_one_off_count: int = 0
    inflation_assumption: float = 0.02
    warnings: list[str] = Field(default_factory=list)


class CashflowImportBatch(BaseModel):
    import_id: str
    created_at: str
    source: str
    account: str
    filename: str
    row_count: int
    imported: int
    duplicates: int
    skipped: int
    warnings: list[str] = Field(default_factory=list)


class CashflowImportResult(BaseModel):
    import_id: str
    source: str
    account: str
    filename: str
    row_count: int
    imported: int
    duplicates: int
    skipped: int
    warnings: list[str] = Field(default_factory=list)


class CompareItem(BaseModel):
    run_id: str
    name: str
    terminal_assets_p50: float
    terminal_net_worth_p50: float
    max_drawdown_p50: float
    joint_shortfall_probability: float
    ruin_probability: float
    # Distribution and composition fields for life-path comparisons.
    terminal_assets_p5: float | None = None
    terminal_assets_p25: float | None = None
    terminal_assets_p75: float | None = None
    terminal_assets_p95: float | None = None
    terminal_emergency_p50: float | None = None
    terminal_illiquid_p50: float | None = None
    terminal_liabilities_p50: float | None = None
    total_contributions: float = 0.0
    total_event_withdrawals: float = 0.0


class CompareResponse(BaseModel):
    items: list[CompareItem]


class RunListItem(BaseModel):
    run_id: str
    created_at: str
    name: str
    terminal_assets_p50: float
    joint_shortfall_probability: float


class ScenarioPreset(BaseModel):
    name: str
    equity: float
    bond: float
    cash: float


class DefaultsResponse(BaseModel):
    request: ScenarioRequest
    presets: dict[str, ScenarioPreset]
    calibration: dict | None = None
