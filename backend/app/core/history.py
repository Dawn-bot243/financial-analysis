"""Historical DCA backtest on official daily total-return series.

The data snapshot (backend/app/data/history.json) stores daily real
total-return indices normalized to 1 at each asset's first trading day. The
core never downloads data; it aligns the selected assets on a common date
grid, runs a monthly DCA, and returns actual (not simulated) results.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np

from ..models import (
    HistoryAssetMeta,
    HistoryAssetValue,
    HistoryMetaResponse,
    HistoryPoint,
    HistoryRequest,
)

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "history.json"
TRADING_YEARS = 365.25


@dataclass(frozen=True)
class AssetHistory:
    name: str
    label: str
    source: str
    role: str
    dates: list[date]
    prices: np.ndarray


@dataclass(frozen=True)
class HistoryData:
    data_version: str
    inflation_assumption: float
    latest_date: date
    source_note: str
    assets: dict[str, AssetHistory]


@dataclass
class HistoryResult:
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
    warnings: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def load_history_data() -> HistoryData:
    import json

    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assets: dict[str, AssetHistory] = {}
    latest: date | None = None
    for name in raw["asset_order"]:
        item = raw["assets"][name]
        dates = [date.fromisoformat(value) for value in item["dates"]]
        prices = np.asarray(item["real_prices"], dtype=float)
        assets[name] = AssetHistory(
            name=name,
            label=item.get("label", name),
            source=item.get("source", ""),
            role=item.get("role", "growth"),
            dates=dates,
            prices=prices,
        )
        if latest is None or dates[-1] > latest:
            latest = dates[-1]
    return HistoryData(
        data_version=str(raw["data_version"]),
        inflation_assumption=float(raw.get("inflation_assumption", 0.02)),
        latest_date=latest or date.today(),
        source_note=str(raw.get("source_note", "")),
        assets=assets,
    )


def history_meta(data: HistoryData | None = None) -> HistoryMetaResponse:
    data = data or load_history_data()
    return HistoryMetaResponse(
        data_version=data.data_version,
        inflation_assumption=data.inflation_assumption,
        latest_date=data.latest_date,
        assets=[
            HistoryAssetMeta(
                name=asset.name,
                label=asset.label,
                source=asset.source,
                start=asset.dates[0],
                end=asset.dates[-1],
            )
            for asset in data.assets.values()
        ],
        disclaimer=(
            "历史回测使用官方全收益/财富指数的日频真实数据，按 2% 通胀折算成今日购买力；"
            "纳指100 为人民币、含汇率、未对冲；黄金无分红。结果为历史实现值，不是未来预测。"
        ),
    )


def _parse_weights(request: HistoryRequest) -> dict[str, float]:
    if request.mode == "single":
        return {request.asset: 1.0}
    weights = {
        name: float(weight)
        for name, weight in request.weights.items()
        if float(weight) > 0.0
    }
    if not weights:
        raise ValueError("at least one portfolio weight must be positive")
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1, got {total:.6f}")
    return weights


def _shift_years(value: date, years: float) -> date:
    return value - timedelta(days=round(TRADING_YEARS * years))


def _requested_dates(
    request: HistoryRequest,
    selected: dict[str, float],
    data: HistoryData,
) -> tuple[date, date]:
    common_first = max(data.assets[name].dates[0] for name in selected)
    common_last = min(data.assets[name].dates[-1] for name in selected)
    requested_end = request.end_date or data.latest_date
    anchor_end = min(requested_end, common_last)
    if anchor_end < common_first:
        raise ValueError("requested end date is before the available history")
    if request.start_date is not None:
        requested_start = request.start_date
    else:
        years = request.lookback_years or 10.0
        requested_start = _shift_years(anchor_end, years)
    if requested_start >= requested_end:
        raise ValueError("start date must be before end date")
    return requested_start, requested_end


def _single_grid(
    asset: AssetHistory, requested_start: date, requested_end: date
) -> tuple[list[date], np.ndarray]:
    first = bisect_left(asset.dates, requested_start)
    last = bisect_right(asset.dates, requested_end) - 1
    if first > last:
        raise ValueError("requested period has no trading data")
    dates = asset.dates[first : last + 1]
    prices = asset.prices[first : last + 1][:, None]
    return dates, prices


def _portfolio_grid(
    selected: dict[str, float],
    data: HistoryData,
    requested_start: date,
    requested_end: date,
) -> tuple[list[date], np.ndarray]:
    names = list(selected)
    common_first = max(data.assets[name].dates[0] for name in names)
    common_last = min(data.assets[name].dates[-1] for name in names)
    range_start = max(requested_start, common_first)
    range_end = min(requested_end, common_last)
    if range_start >= range_end:
        raise ValueError("selected assets have no common trading period")

    date_set: set[date] = set()
    for name in names:
        asset = data.assets[name]
        start = bisect_left(asset.dates, range_start)
        end = bisect_right(asset.dates, range_end)
        date_set.update(asset.dates[start:end])
    dates = sorted(date_set)
    if len(dates) < 2:
        raise ValueError("common trading period is too short")

    prices = np.empty((len(dates), len(names)), dtype=float)
    for column, name in enumerate(names):
        asset = data.assets[name]
        for row, day in enumerate(dates):
            index = bisect_right(asset.dates, day) - 1
            if index < 0:
                raise ValueError(f"no price for {name} on {day}")
            prices[row, column] = asset.prices[index]
    return dates, prices


def _month_end_indices(dates: list[date]) -> list[int]:
    result: list[int] = []
    for index, day in enumerate(dates):
        if index == len(dates) - 1 or (
            dates[index + 1].year,
            dates[index + 1].month,
        ) != (day.year, day.month):
            result.append(index)
    return result


def _contribution_indices(dates: list[date]) -> list[int]:
    result = [0]
    key = (dates[0].year, dates[0].month)
    for index in range(1, len(dates)):
        next_key = (dates[index].year, dates[index].month)
        if next_key != key:
            result.append(index)
            key = next_key
    return result


def _npv(rate: float, cashflows: list[tuple[date, float]], start: date) -> float:
    total = 0.0
    for day, amount in cashflows:
        years = (day - start).days / TRADING_YEARS
        total += amount / (1.0 + rate) ** years
    return total


def _irr(cashflows: list[tuple[date, float]], start: date) -> float | None:
    if not cashflows:
        return None
    low, high = -0.9999, 10.0
    low_value = _npv(low, cashflows, start)
    high_value = _npv(high, cashflows, start)
    if low_value * high_value > 0.0:
        return None
    for _ in range(120):
        middle = (low + high) / 2.0
        value = _npv(middle, cashflows, start)
        if abs(value) < 1e-9:
            break
        if low_value * value <= 0.0:
            high = middle
            high_value = value
        else:
            low = middle
            low_value = value
    return (low + high) / 2.0


def _drawdown(unit_values: np.ndarray, dates: list[date]) -> tuple[float, date | None, date | None]:
    if len(unit_values) == 0:
        return 0.0, None, None
    running_max = np.maximum.accumulate(unit_values)
    drawdowns = 1.0 - unit_values / np.maximum(running_max, 1e-12)
    trough = int(np.argmax(drawdowns))
    if drawdowns[trough] <= 1e-12:
        return 0.0, dates[0], dates[0]
    peak = int(np.argmax(unit_values[: trough + 1]))
    return float(drawdowns[trough]), dates[peak], dates[trough]


def run_history_backtest(
    request: HistoryRequest, data: HistoryData | None = None
) -> HistoryResult:
    data = data or load_history_data()
    selected = _parse_weights(request)
    unknown = set(selected) - set(data.assets)
    if unknown:
        raise ValueError(f"unknown assets: {sorted(unknown)}")

    requested_start, requested_end = _requested_dates(request, selected, data)
    if len(selected) == 1:
        name = next(iter(selected))
        dates, prices = _single_grid(
            data.assets[name], requested_start, requested_end
        )
    else:
        dates, prices = _portfolio_grid(
            selected, data, requested_start, requested_end
        )

    effective_start, effective_end = dates[0], dates[-1]
    warnings: list[str] = []
    if (effective_start - requested_start).days > 31:
        warnings.append(
            f"所选资产在请求起点尚无数据，实际从 {effective_start.isoformat()} 开始。"
        )
    if (requested_end - effective_end).days > 7:
        warnings.append(
            f"请求结束日期晚于数据最新可用日期，实际截至 {effective_end.isoformat()}。"
        )
    months = (
        (effective_end.year - effective_start.year) * 12
        + (effective_end.month - effective_start.month)
        + 1
    )
    if months < 12:
        warnings.append("区间不足 12 个月，年化 IRR 仅供参考。")

    names = list(selected)
    weights = np.asarray([selected[name] for name in names], dtype=float)
    weights = weights / weights.sum()
    contribution_indices = set(_contribution_indices(dates))
    initial = float(request.initial_capital)
    monthly = float(request.monthly_contribution)

    first_cash = initial + monthly
    total_units = first_cash  # unit value starts at 1
    units = (first_cash * weights) / prices[0]
    invested = first_cash
    cashflows: list[tuple[date, float]] = [(dates[0], -first_cash)]

    unit_values = np.empty(len(dates), dtype=float)
    month_ends = set(_month_end_indices(dates))
    path_indices = sorted({0, len(dates) - 1, *month_ends})
    path: list[HistoryPoint] = []
    values = np.empty(len(dates), dtype=float)

    for index, day in enumerate(dates):
        if index > 0 and index in contribution_indices:
            portfolio_before = float(np.sum(units * prices[index]))
            unit_value_before = portfolio_before / total_units if total_units > 0 else 1.0
            total_units += monthly / unit_value_before
            units += (monthly * weights) / prices[index]
            invested += monthly
            cashflows.append((day, -monthly))

        if (
            index > 0
            and request.rebalance == "annual"
            and dates[index].year != dates[index - 1].year
        ):
            portfolio_value = float(np.sum(units * prices[index]))
            units = (portfolio_value * weights) / prices[index]

        value = float(np.sum(units * prices[index]))
        unit_value = value / total_units if total_units > 0 else 0.0
        values[index] = value
        unit_values[index] = unit_value

        if index in path_indices:
            path.append(
                HistoryPoint(date=day, value=value, invested=invested)
            )

    terminal = float(values[-1])
    total_invested = float(invested)
    profit = terminal - total_invested
    return_on_invested = profit / total_invested if total_invested > 0 else 0.0
    cashflows.append((effective_end, terminal))
    irr = _irr(cashflows, effective_start)
    max_drawdown, peak_date, trough_date = _drawdown(unit_values, dates)

    yearly: dict[int, HistoryPoint] = {}
    for point in path:
        yearly[point.date.year] = point
    yearly_points = [yearly[year] for year in sorted(yearly)]

    final_values = units * prices[-1]
    final_total = float(final_values.sum())
    composition = [
        HistoryAssetValue(
            asset=name,
            label=data.assets[name].label,
            value=float(final_values[index]),
            weight=float(final_values[index] / final_total) if final_total > 0 else 0.0,
        )
        for index, name in enumerate(names)
    ]

    return HistoryResult(
        requested_start_date=requested_start,
        requested_end_date=requested_end,
        effective_start_date=effective_start,
        effective_end_date=effective_end,
        months=months,
        contribution_count=len(contribution_indices) if monthly > 0 else 0,
        initial_capital=initial,
        monthly_contribution=monthly,
        total_invested=total_invested,
        terminal_value=terminal,
        profit=profit,
        return_on_invested=return_on_invested,
        irr_annual=irr,
        max_drawdown=max_drawdown,
        drawdown_peak_date=peak_date,
        drawdown_trough_date=trough_date,
        path=path,
        yearly=yearly_points,
        final_composition=composition,
        warnings=warnings,
    )
