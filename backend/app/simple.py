from __future__ import annotations

from pydantic import BaseModel, Field

from .assets import calibrated_assets, calibrated_correlation, load_calibration
from .models import (
    Household,
    InitialHolding,
    MarketAssumptions,
    ScenarioRequest,
    StrategySpec,
)


class SimpleRequest(BaseModel):
    """Minimal DCA input: initial capital, monthly contribution, allocation."""

    name: str = "简版定投"
    initial_capital: float = Field(default=0.0, ge=0.0)
    monthly_contribution: float = Field(default=0.0, ge=0.0)
    horizon_years: int = Field(default=10, ge=1, le=50)
    # Fractions of the portfolio, keyed by the calibrated asset names.
    weights: dict[str, float] = Field(default_factory=dict)
    goal_amount: float = Field(default=0.0, ge=0.0)
    calibration_window: str = "10y"
    n_paths: int = Field(default=5000, ge=100, le=100000)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


def build_simple_request(payload: SimpleRequest) -> ScenarioRequest:
    calibration = load_calibration()
    if not calibration:
        raise ValueError("calibration snapshot not found")
    window = payload.calibration_window or "10y"
    if window not in calibration.get("correlations", {}):
        raise ValueError(f"unknown calibration window {window!r}")

    assets = calibrated_assets(calibration, window)
    correlation = calibrated_correlation(calibration, window)
    names = [asset.name for asset in assets]
    unknown = set(payload.weights) - set(names)
    if unknown:
        raise ValueError(f"unknown assets: {sorted(unknown)}")

    weights = {name: float(payload.weights.get(name, 0.0)) for name in names}
    if any(weight < 0.0 for weight in weights.values()):
        raise ValueError("weights must be non-negative")
    total = sum(weights.values())
    if total <= 0.0:
        raise ValueError("at least one asset weight must be positive")
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1, got {total:.6f}")
    if payload.initial_capital <= 0.0 and payload.monthly_contribution <= 0.0:
        raise ValueError("initial capital or monthly contribution must be positive")

    holdings = [
        InitialHolding(
            asset=asset.name,
            label=asset.label or asset.name,
            value=payload.initial_capital * weights[asset.name],
            liquidity="liquid",
        )
        for asset in assets
    ]
    household = Household(
        current_age=30.0,
        holdings=holdings,
        monthly_income=payload.monthly_contribution,
        monthly_expense=0.0,
        income_growth_real=0.0,
        expense_growth_real=0.0,
        liabilities=[],
        events=[],
        emergency_fund_months=0.0,
        emergency_fund_includes_debt=False,
        event_withdrawal_order="investments_first",
    )
    strategy = StrategySpec(
        kind="constant",
        weights=weights,
        rebalance="annual",
    )
    return ScenarioRequest(
        name=payload.name or "简版定投",
        market=MarketAssumptions(
            assets=assets,
            correlation=correlation,
            student_t_df=5.0,
        ),
        household=household,
        strategy=strategy,
        horizon_years=payload.horizon_years,
        n_paths=payload.n_paths,
        seed=payload.seed,
        include_explanation=False,
        data_version=str(calibration.get("data_version", "none")),
        calibration_window=window,
        goal_amount=payload.goal_amount,
    )
