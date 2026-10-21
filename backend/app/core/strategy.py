from __future__ import annotations

from typing import Mapping, Protocol, Sequence

import numpy as np


class StrategyLike(Protocol):
    kind: str
    weights: Mapping[str, float] | None
    growth_assets: list[str]
    growth_weights: Mapping[str, float]
    defensive_assets: list[str]
    defensive_weights: Mapping[str, float]
    cash_asset: str
    cash_weight: float
    growth_start: float
    growth_end: float
    glide_start_age: float
    glide_end_age: float
    floor: float
    cap: float
    equity_asset: str
    bond_asset: str


def target_weights(
    strategy: StrategyLike, asset_names: Sequence[str], age: float
) -> np.ndarray:
    names = list(asset_names)
    index = {name: i for i, name in enumerate(names)}
    weights = np.zeros(len(names), dtype=float)

    if strategy.kind == "constant":
        if not strategy.weights:
            raise ValueError("constant strategy requires weights")
        for name, weight in strategy.weights.items():
            if name not in index:
                raise ValueError(f"unknown asset {name!r} in weights")
            weights[index[name]] = float(weight)
        total = float(weights.sum())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"target weights sum to {total:.6f}, expected 1")
        return weights

    if strategy.kind not in ("glide", "all_equity"):
        raise ValueError(f"unknown strategy kind {strategy.kind!r}")

    growth_assets = list(strategy.growth_assets) or [strategy.equity_asset]
    defensive_assets = list(strategy.defensive_assets)
    cash_weight = float(strategy.cash_weight)

    if strategy.kind == "all_equity":
        growth_weight = 1.0
        defensive_weight = 0.0
        cash_weight = 0.0
    else:
        span = strategy.glide_end_age - strategy.glide_start_age
        progress = (
            0.0
            if span <= 0.0
            else float(np.clip((age - strategy.glide_start_age) / span, 0.0, 1.0))
        )
        growth_weight = strategy.growth_start + (
            strategy.growth_end - strategy.growth_start
        ) * progress
        growth_weight = float(np.clip(growth_weight, strategy.floor, strategy.cap))
        growth_weight = min(growth_weight, max(0.0, 1.0 - cash_weight))
        defensive_weight = max(0.0, 1.0 - growth_weight - cash_weight)

    growth_weights = strategy.growth_weights or {
        asset: 1.0 / len(growth_assets) for asset in growth_assets
    }
    growth_total = sum(max(0.0, float(growth_weights.get(asset, 0.0))) for asset in growth_assets)
    if growth_total <= 0.0:
        raise ValueError("growth sleeve weights must sum to a positive value")
    for asset in growth_assets:
        if asset not in index:
            raise ValueError(f"unknown growth asset {asset!r}")
        weights[index[asset]] += (
            growth_weight * max(0.0, float(growth_weights.get(asset, 0.0))) / growth_total
        )

    if defensive_assets and defensive_weight > 1e-12:
        defensive_weights = strategy.defensive_weights or {
            asset: 1.0 / len(defensive_assets) for asset in defensive_assets
        }
        defensive_total = sum(
            max(0.0, float(defensive_weights.get(asset, 0.0)))
            for asset in defensive_assets
        )
        if defensive_total <= 0.0:
            raise ValueError("defensive sleeve weights must sum to a positive value")
        for asset in defensive_assets:
            if asset not in index:
                raise ValueError(f"unknown defensive asset {asset!r}")
            weights[index[asset]] += (
                defensive_weight
                * max(0.0, float(defensive_weights.get(asset, 0.0)))
                / defensive_total
            )
    elif defensive_weight > 1e-12:
        if strategy.cash_asset not in index:
            raise ValueError(
                "glide strategy has no defensive assets and no cash asset to absorb the remainder"
            )
        weights[index[strategy.cash_asset]] += defensive_weight

    if cash_weight > 1e-12:
        if strategy.cash_asset not in index:
            raise ValueError(f"missing cash asset {strategy.cash_asset!r}")
        weights[index[strategy.cash_asset]] += cash_weight

    total = float(weights.sum())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"target weights sum to {total:.6f}, expected 1")
    return weights
