from __future__ import annotations

from .assets import (
    ASSET_LABELS,
    ASSET_ORDER,
    DEFAULT_HOLDINGS,
    calibrated_assets,
    calibrated_correlation,
    load_calibration,
)
from .models import (
    AssetAssumption,
    AssetPurchase,
    DefaultsResponse,
    Household,
    InitialHolding,
    Liability,
    LifeEvent,
    MarketAssumptions,
    ScenarioPreset,
    ScenarioRequest,
    StrategySpec,
)

SCENARIO_PRESETS: dict[str, ScenarioPreset] = {
    "conservative": ScenarioPreset(name="保守", equity=0.02, bond=0.0, cash=0.0),
    "base": ScenarioPreset(name="基准", equity=0.04, bond=0.01, cash=0.0),
    "optimistic": ScenarioPreset(name="乐观", equity=0.06, bond=0.02, cash=0.0),
}

FALLBACK_ASSETS = [
    AssetAssumption(name="csi300", label="沪深300", role="growth", expected_real_return=0.0227, volatility=0.1528),
    AssetAssumption(name="csi500", label="中证500", role="growth", expected_real_return=0.0108, volatility=0.2085),
    AssetAssumption(name="dividend", label="中证红利", role="growth", expected_real_return=0.0336, volatility=0.1152),
    AssetAssumption(name="sse", label="上证指数", role="growth", expected_real_return=0.0300, volatility=0.2000),
    AssetAssumption(name="sp500", label="标普500", role="growth", expected_real_return=0.0600, volatility=0.1700),
    AssetAssumption(name="ndx100", label="纳斯达克100", role="growth", expected_real_return=0.1713, volatility=0.1800),
    AssetAssumption(name="nikkei", label="日经225", role="growth", expected_real_return=0.0500, volatility=0.1900),
    AssetAssumption(name="hsi", label="恒生指数", role="growth", expected_real_return=0.0400, volatility=0.2000),
    AssetAssumption(name="gold", label="黄金", role="defensive", expected_real_return=0.1128, volatility=0.1399),
    AssetAssumption(name="bond", label="债券", role="defensive", expected_real_return=0.0183, volatility=0.0177),
    AssetAssumption(name="cash", label="现金", role="cash", expected_real_return=0.0, volatility=0.0),
]

# Fallback only (used when calibration.json is missing). The original seven
# assets keep their matrix; the four new assets start uncorrelated until the
# calibration snapshot supplies their real pairwise correlations.
_OLD_FALLBACK_ORDER = [
    "csi300",
    "csi500",
    "dividend",
    "ndx100",
    "gold",
    "bond",
    "cash",
]
_OLD_FALLBACK_CORRELATION = [
    [1.0, 0.81, 0.55, 0.30, 0.11, -0.30, 0.0],
    [0.81, 1.0, 0.38, 0.32, 0.18, -0.19, 0.0],
    [0.55, 0.38, 1.0, 0.21, 0.0, -0.14, 0.0],
    [0.30, 0.32, 0.21, 1.0, -0.01, -0.05, 0.0],
    [0.11, 0.18, 0.0, -0.01, 1.0, 0.0, 0.0],
    [-0.30, -0.19, -0.14, -0.05, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
]


def _fallback_correlation() -> list[list[float]]:
    size = len(ASSET_ORDER)
    matrix = [[0.0] * size for _ in range(size)]
    for index in range(size):
        matrix[index][index] = 1.0
    for old_i, old_name in enumerate(_OLD_FALLBACK_ORDER):
        for old_j, old_name_j in enumerate(_OLD_FALLBACK_ORDER):
            matrix[ASSET_ORDER.index(old_name)][ASSET_ORDER.index(old_name_j)] = (
                _OLD_FALLBACK_CORRELATION[old_i][old_j]
            )
    return matrix


FALLBACK_CORRELATION = _fallback_correlation()


def _holdings() -> list[InitialHolding]:
    holdings = [
        InitialHolding(
            asset=item["asset"],
            label=item["label"],
            value=float(item["value"]),
            liquidity="liquid",
        )
        for item in DEFAULT_HOLDINGS
    ]
    holdings.append(
        InitialHolding(
            asset="real_estate",
            label="自住房",
            value=1_500_000.0,
            liquidity="illiquid",
            growth_rate=0.02,
            monthly_income=3_000.0,
            selling_cost_rate=0.02,
            sell_age=None,
            liability_name="房贷",
        )
    )
    return holdings


def _events() -> list[LifeEvent]:
    return [
        LifeEvent(
            name="购车",
            start_age=33.0,
            # A three-year window: check every month from age 33 to 36, buy at
            # the first month the household can cover the down payment from all
            # liquid assets, and retry at the deadline if needed.
            window_years=3.0,
            monthly_expense=1_500.0,
            purchase=AssetPurchase(
                asset="car",
                label="家用车",
                price=250_000.0,
                down_payment=100_000.0,
                loan_annual_rate=0.04,
                loan_months=60,
                appreciation_rate=-0.10,
                monthly_rent=0.0,
                selling_cost_rate=0.05,
                sell_age=38.0,
            ),
        ),
        LifeEvent(
            name="子女教育",
            start_age=39.5,
            one_off_expense=300_000.0,
        ),
    ]


def default_request(
    calibration: dict | None = None, window: str = "10y"
) -> ScenarioRequest:
    calibration = calibration if calibration is not None else load_calibration()
    if calibration:
        assets = calibrated_assets(calibration, window)
        correlation = calibrated_correlation(calibration, window)
        data_version = str(calibration.get("data_version", "none"))
    else:
        assets = FALLBACK_ASSETS
        correlation = FALLBACK_CORRELATION
        data_version = "none"

    return ScenarioRequest(
        name="基准",
        market=MarketAssumptions(
            assets=assets,
            correlation=correlation,
            student_t_df=5.0,
        ),
        household=Household(
            current_age=30.0,
            initial_capital=0.0,
            holdings=_holdings(),
            monthly_income=30_000.0,
            monthly_expense=15_000.0,
            income_growth_real=0.0,
            expense_growth_real=0.0,
            liabilities=[
                Liability(
                    name="房贷",
                    balance=900_000.0,
                    annual_rate=0.035,
                    remaining_months=300,
                    linked_holding="自住房",
                )
            ],
            events=_events(),
            emergency_fund_months=10.0,
            emergency_fund_includes_debt=True,
            event_withdrawal_order="investments_first",
        ),
        strategy=StrategySpec(
            kind="glide",
            growth_assets=[
                "csi300",
                "csi500",
                "dividend",
                "sse",
                "sp500",
                "ndx100",
                "nikkei",
                "hsi",
            ],
            growth_weights={
                "csi300": 0.4,
                "csi500": 0.2,
                "dividend": 0.2,
                "sse": 0.0,
                "sp500": 0.0,
                "ndx100": 0.2,
                "nikkei": 0.0,
                "hsi": 0.0,
            },
            defensive_assets=["bond", "gold"],
            defensive_weights={"bond": 0.8, "gold": 0.2},
            cash_asset="cash",
            cash_weight=0.0,
            growth_start=0.8,
            growth_end=0.4,
            glide_start_age=30.0,
            glide_end_age=60.0,
            floor=0.2,
            cap=1.0,
            rebalance="annual",
        ),
        horizon_years=10,
        n_paths=10_000,
        seed=42,
        include_explanation=True,
        data_version=data_version,
        calibration_window=window,
    )


def defaults_payload(window: str = "10y") -> DefaultsResponse:
    calibration = load_calibration()
    return DefaultsResponse(
        request=default_request(calibration=calibration, window=window),
        presets=SCENARIO_PRESETS,
        calibration=calibration or None,
    )
