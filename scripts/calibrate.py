"""Build a reproducible calibration snapshot from official total-return series.

The raw series live in backend/data/market/*.csv (gitignored). This script
computes annualized geometric returns, volatilities and correlations for
5y/10y/15y/full windows and writes backend/app/data/calibration.json.

All return series are official total-return indices:
  - CSI H00300 / H00905 / H00922
  - Nasdaq-100 XNDX, converted to CNY with BOC USD/CNY
  - ChinaBond New Composite Wealth Index
Gold is a price series (no dividends); cash is a fixed real-return assumption.

Run:
    python scripts/calibrate.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MARKET_DIR = ROOT / "backend" / "data" / "market"
OUT_PATH = ROOT / "backend" / "app" / "data" / "calibration.json"

ASSET_ORDER = ["csi300", "csi500", "dividend", "ndx100", "gold", "bond", "cash"]
CALIBRATED = ["csi300", "csi500", "dividend", "ndx100", "gold", "bond"]
SOURCE_FILES = CALIBRATED + ["ndx100_usd", "usdcny"]
INFLATION = 0.02
END = pd.Timestamp("2026-09-30")
WINDOWS: dict[str, int | None] = {"5y": 5, "10y": 10, "15y": 15, "full": None}

META = {
    "csi300": {
        "label": "沪深300",
        "role": "growth",
        "series_type": "total_return_index",
        "source": "CSI H00300 沪深300全收益指数",
        "fee_included": False,
        "expense_ratio": 0.0,
        "note": "官方全收益指数，分红再投资；未扣产品费率",
    },
    "csi500": {
        "label": "中证500",
        "role": "growth",
        "series_type": "total_return_index",
        "source": "CSI H00905 中证500全收益指数",
        "fee_included": False,
        "expense_ratio": 0.0,
        "note": "官方全收益指数，分红再投资；未扣产品费率",
    },
    "dividend": {
        "label": "中证红利",
        "role": "growth",
        "series_type": "total_return_index",
        "source": "CSI H00922 中证红利全收益指数",
        "fee_included": False,
        "expense_ratio": 0.0,
        "note": "官方全收益指数，分红再投资；未扣产品费率",
    },
    "ndx100": {
        "label": "纳斯达克100（人民币，未对冲）",
        "role": "growth",
        "series_type": "total_return_index",
        "source": "Nasdaq XNDX 全收益（USD）× 中行 USD/CNY 中间价",
        "fee_included": False,
        "expense_ratio": 0.0,
        "note": "官方美元全收益指数换算为人民币，含汇率、未对冲；未扣产品费率",
    },
    "gold": {
        "label": "黄金",
        "role": "defensive",
        "series_type": "price",
        "source": "COMEX 黄金连续（USD/oz）× 中行 USD/CNY，折算人民币/克",
        "fee_included": False,
        "expense_ratio": 0.0,
        "note": "人民币金价，含汇率、未对冲；黄金无分红，价格即总收益近似；不是上金所 Au99.99",
    },
    "bond": {
        "label": "债券",
        "role": "defensive",
        "series_type": "total_return_index",
        "source": "中债-新综合财富指数（财富，总值）",
        "fee_included": False,
        "expense_ratio": 0.0,
        "note": "官方财富指数，含票息；未扣产品费率",
    },
    "cash": {
        "label": "现金",
        "role": "cash",
        "series_type": "fixed",
        "source": "固定实际收益 0%",
        "fee_included": True,
        "expense_ratio": 0.0,
        "note": "应急金与现金仓位的假定实际收益，不是指数",
    },
}


def load_series() -> dict[str, pd.Series]:
    series: dict[str, pd.Series] = {}
    for key in CALIBRATED:
        path = MARKET_DIR / f"{key}.csv"
        if not path.exists():
            raise FileNotFoundError(f"missing cached series: {path}")
        df = pd.read_csv(path, parse_dates=["date"]).dropna()
        df = df.sort_values("date").drop_duplicates("date")
        monthly = df.set_index("date")["value"].resample("ME").last().dropna()
        series[key] = monthly[monthly.index <= END]
    return series


def stats_for(series: pd.Series, years: int | None) -> dict:
    if years is None:
        start = None
    else:
        start = END - pd.DateOffset(years=years)
    values = series if start is None else series[series.index >= start]
    returns = np.log(values).diff().dropna()
    if len(returns) < 12:
        raise ValueError(f"insufficient monthly returns: {len(returns)}")
    nominal = float(np.exp(returns.mean() * 12.0) - 1.0)
    real = float((1.0 + nominal) / (1.0 + INFLATION) - 1.0)
    vol = float(returns.std(ddof=1) * np.sqrt(12.0))
    requested = None if years is None else int(years * 12)
    return {
        "start": values.index.min().date().isoformat(),
        "end": values.index.max().date().isoformat(),
        "months": int(len(returns)),
        "requested_months": requested,
        "is_short": bool(requested is not None and len(returns) < requested - 1),
        "nominal_geo": nominal,
        "real_geo": real,
        "volatility": vol,
    }


def correlation_for(
    series: dict[str, pd.Series], years: int | None
) -> dict:
    if years is None:
        start = None
    else:
        start = END - pd.DateOffset(years=years)
    frames = []
    for key in CALIBRATED:
        values = series[key]
        if start is not None:
            values = values[values.index >= start]
        frames.append(np.log(values).diff().rename(key))
    common = pd.concat(frames, axis=1).dropna()
    if len(common) < 12:
        raise ValueError(f"insufficient common months: {len(common)}")
    corr = common.corr()
    matrix = corr.reindex(index=CALIBRATED, columns=CALIBRATED).to_numpy().tolist()
    cash_index = ASSET_ORDER.index("cash")
    full = []
    for row in matrix:
        new_row = list(row)
        new_row.insert(cash_index, 0.0)
        full.append(new_row)
    full.insert(cash_index, [0.0] * len(ASSET_ORDER))
    full[cash_index][cash_index] = 1.0
    requested = None if years is None else int(years * 12)
    return {
        "start": common.index.min().date().isoformat(),
        "end": common.index.max().date().isoformat(),
        "months": int(len(common)),
        "requested_months": requested,
        "is_short": bool(requested is not None and len(common) < requested - 1),
        "asset_order": ASSET_ORDER,
        "matrix": full,
    }


def main() -> None:
    series = load_series()
    assets: dict[str, dict] = {}
    for key in ASSET_ORDER:
        meta = dict(META[key])
        if key == "cash":
            meta["windows"] = {
                window: {
                    "start": END.date().isoformat(),
                    "end": END.date().isoformat(),
                    "months": 0,
                    "requested_months": None,
                    "is_short": False,
                    "nominal_geo": INFLATION,
                    "real_geo": 0.0,
                    "volatility": 0.0,
                }
                for window in WINDOWS
            }
        else:
            meta["windows"] = {
                window: stats_for(series[key], years)
                for window, years in WINDOWS.items()
            }
        assets[key] = meta

    correlations = {
        window: correlation_for(series, years)
        for window, years in WINDOWS.items()
    }

    digest = hashlib.sha256()
    for key in SOURCE_FILES:
        path = MARKET_DIR / f"{key}.csv"
        if not path.exists():
            raise FileNotFoundError(f"missing cached series: {path}")
        digest.update(key.encode("utf-8"))
        digest.update(path.read_bytes())
    digest.update(
        json.dumps({"inflation": INFLATION, "windows": WINDOWS}, sort_keys=True).encode(
            "utf-8"
        )
    )
    data_version = digest.hexdigest()[:16]

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inflation_assumption": INFLATION,
        "asset_order": ASSET_ORDER,
        "assets": assets,
        "correlations": correlations,
        "data_version": data_version,
        "disclaimer": (
            "全部权益与债券收益使用官方全收益/财富指数：CSI H00300/H00905/H00922、"
            "Nasdaq XNDX（按中行 USD/CNY 换算人民币）、中债新综合财富指数。"
            "黄金使用 COMEX 黄金连续（USD/oz）× 中行 USD/CNY，折算人民币/克；"
            "无分红、含汇率、未对冲；现金为 0% 实际收益假设。"
            "官方指数未扣产品费率，可在资产假设里另行添加。"
            "历史窗口不足的资产/相关矩阵会带 is_short 标记。"
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT_PATH)
    print("data_version", data_version)
    for window in WINDOWS:
        corr = correlations[window]
        print(
            window,
            "corr months",
            corr["months"],
            "requested",
            corr["requested_months"],
            "short",
            corr["is_short"],
        )
    for key in CALIBRATED:
        w = assets[key]["windows"]["10y"]
        print(
            f"{key:10s} 10y real {w['real_geo']:7.3%} vol {w['volatility']:7.3%} "
            f"months {w['months']:3d} short {w['is_short']} start {w['start']}"
        )


if __name__ == "__main__":
    main()
