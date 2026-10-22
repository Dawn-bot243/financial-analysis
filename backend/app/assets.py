from __future__ import annotations

import json
from pathlib import Path

from .models import AssetAssumption

CALIBRATION_PATH = Path(__file__).resolve().parent / "data" / "calibration.json"
DEFAULT_WINDOW = "10y"

ASSET_ORDER = [
    "csi300",
    "csi500",
    "dividend",
    "sse",
    "sp500",
    "ndx100",
    "nikkei",
    "hsi",
    "gold",
    "bond",
    "cash",
]

ASSET_LABELS = {
    "csi300": "沪深300",
    "csi500": "中证500",
    "dividend": "中证红利",
    "sse": "上证指数",
    "sp500": "标普500",
    "ndx100": "纳斯达克100",
    "nikkei": "日经225",
    "hsi": "恒生指数",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
    "real_estate": "房产",
    "car": "车",
    "other_illiquid": "其他不动产",
}

DEFAULT_HOLDINGS = [
    {"asset": "cash", "label": "现金", "value": 300_000.0},
    {"asset": "csi300", "label": "沪深300", "value": 200_000.0},
    {"asset": "csi500", "label": "中证500", "value": 100_000.0},
    {"asset": "dividend", "label": "中证红利", "value": 100_000.0},
    {"asset": "ndx100", "label": "纳斯达克100", "value": 100_000.0},
    {"asset": "gold", "label": "黄金", "value": 50_000.0},
    {"asset": "bond", "label": "债券", "value": 100_000.0},
]


def load_calibration() -> dict:
    if not CALIBRATION_PATH.exists():
        return {}
    return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))


def calibrated_assets(calibration: dict, window: str) -> list[AssetAssumption]:
    if not calibration:
        raise ValueError("calibration snapshot not found")
    order = calibration.get("asset_order", ASSET_ORDER)
    assets: list[AssetAssumption] = []
    for key in order:
        meta = calibration["assets"][key]
        stats = meta["windows"][window]
        assets.append(
            AssetAssumption(
                name=key,
                label=meta.get("label", ASSET_LABELS.get(key, key)),
                role=meta.get("role", "growth"),
                expected_real_return=float(stats["real_geo"]),
                volatility=float(stats["volatility"]),
                expense_ratio=float(meta.get("expense_ratio", 0.0)),
                liquid=True,
            )
        )
    return assets


def calibrated_correlation(calibration: dict, window: str) -> list[list[float]]:
    return calibration["correlations"][window]["matrix"]


def calibration_window_labels(calibration: dict) -> dict[str, str]:
    return {
        window: {
            "5y": "近 5 年",
            "10y": "近 10 年",
            "15y": "近 15 年",
            "full": "全历史",
        }.get(window, window)
        for window in calibration.get("correlations", {})
    }
