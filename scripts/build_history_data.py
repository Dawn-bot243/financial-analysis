"""Build the daily real total-return history used by the historical DCA page.

The raw daily CSVs live in backend/data/market/ (gitignored). This script
normalizes each official total-return series to a real (today's purchasing
power) index starting at 1, keeps the daily dates, and writes a compact JSON
snapshot that the app reads at runtime.

Sources:
  - CSI H00300 / H00905 / H00922 total-return indices
  - Nasdaq XNDX USD total return converted to CNY (BOC USD/CNY)
  - COMEX continuous gold (USD/oz) converted to CNY/gram (BOC USD/CNY);
    this is a 20-year gold price proxy, not Shanghai Gold Exchange Au99.99
  - ChinaBond New Composite Wealth Index (total return)

The app reports the effective start date instead of pretending a longer
window exists when an asset's history is shorter.

Run:
    python scripts/build_history_data.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MARKET_DIR = ROOT / "backend" / "data" / "market"
CALIBRATION_PATH = ROOT / "backend" / "app" / "data" / "calibration.json"
OUT_PATH = ROOT / "backend" / "app" / "data" / "history.json"

END = pd.Timestamp("2026-10-20")
INFLATION = 0.02
ASSET_ORDER = ["csi300", "csi500", "dividend", "ndx100", "gold", "bond"]

FALLBACK_META = {
    "csi300": ("沪深300", "CSI H00300 沪深300全收益指数"),
    "csi500": ("中证500", "CSI H00905 中证500全收益指数"),
    "dividend": ("中证红利", "CSI H00922 中证红利全收益指数"),
    "ndx100": (
        "纳斯达克100（人民币，未对冲）",
        "Nasdaq XNDX 全收益（USD）× 中行 USD/CNY 中间价",
    ),
    "gold": ("黄金", "COMEX 黄金连续（USD/oz）× 中行 USD/CNY，折算人民币/克"),
    "bond": ("债券", "中债-新综合财富指数"),
}


def load_meta() -> dict[str, dict]:
    if CALIBRATION_PATH.exists():
        calibration = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        return calibration.get("assets", {})
    return {}


def build_asset(key: str, meta: dict) -> dict:
    path = MARKET_DIR / f"{key}.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing cached series: {path}")
    frame = pd.read_csv(path, parse_dates=["date"]).dropna()
    frame = frame.sort_values("date").drop_duplicates("date")
    frame = frame[frame["date"] <= END]
    if len(frame) < 30:
        raise ValueError(f"insufficient daily data for {key}: {len(frame)}")

    first = frame["date"].iloc[0]
    # Deflate by calendar time so the series is in today's purchasing power.
    years = (frame["date"] - first).dt.days / 365.25
    real = frame["value"].astype(float) / (1.0 + INFLATION) ** years
    real = real / real.iloc[0]

    label, source = FALLBACK_META[key]
    return {
        "name": key,
        "label": meta.get("label", label),
        "source": meta.get("source", source),
        "role": meta.get("role", "growth"),
        "start": frame["date"].iloc[0].date().isoformat(),
        "end": frame["date"].iloc[-1].date().isoformat(),
        "dates": [value.date().isoformat() for value in frame["date"]],
        "real_prices": [round(float(value), 8) for value in real],
    }


def main() -> None:
    meta = load_meta()
    assets = {key: build_asset(key, meta.get(key, {})) for key in ASSET_ORDER}

    digest = hashlib.sha256()
    for key in ASSET_ORDER:
        path = MARKET_DIR / f"{key}.csv"
        digest.update(key.encode("utf-8"))
        digest.update(path.read_bytes())
    digest.update(
        json.dumps(
            {"end": END.date().isoformat(), "inflation": INFLATION}, sort_keys=True
        ).encode("utf-8")
    )
    data_version = digest.hexdigest()[:16]

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_version": data_version,
        "inflation_assumption": INFLATION,
        "end": END.date().isoformat(),
        "asset_order": ASSET_ORDER,
        "source_note": (
            "全部权益与债券使用官方全收益/财富指数；纳指100 为人民币、含汇率、未对冲；"
            "黄金为 COMEX 黄金连续（USD/oz）× 中行 USD/CNY 折算人民币/克，含汇率、未对冲、无分红。"
            "价格已按 2% 通胀折算成今日购买力，并在各自首个交易日归一为 1。"
            "官方指数未扣产品费率。"
        ),
        "assets": assets,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print("wrote", OUT_PATH, "size", OUT_PATH.stat().st_size)
    print("data_version", data_version)
    for key, asset in assets.items():
        print(
            f"{key:10s} {asset['start']} -> {asset['end']} "
            f"rows {len(asset['dates'])}"
        )


if __name__ == "__main__":
    main()
