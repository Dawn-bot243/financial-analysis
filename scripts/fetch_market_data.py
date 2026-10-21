"""Refresh the official total-return series used by scripts/calibrate.py.

Requires: pip install -r requirements-calibration.txt

Sources:
  - CSI total return indices (official):
      H00300 沪深300全收益, H00905 中证500全收益, H00922 中证红利全收益
  - Nasdaq-100 Total Return Index (XNDX), official Nasdaq Global Indexes;
    converted to CNY with the Bank of China USD/CNY central parity.
  - Gold: COMEX continuous gold (USD/oz) from Eastmoney, converted to CNY/gram
    with the Bank of China USD/CNY central parity. This is a 20-year gold price
    proxy; it is not Shanghai Gold Exchange Au99.99.
  - Bonds: ChinaBond New Composite Wealth Index (total return).

The app never calls these sources at runtime; it reads calibration.json.
"""

from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "data" / "market"
END = "20261020"

CSI_SERIES = {
    "csi300": "H00300",
    "csi500": "H00905",
    "dividend": "H00922",
}


def retry(label: str, fn, attempts: int = 3):
    for attempt in range(1, attempts + 1):
        try:
            value = fn()
            print(label, "ok")
            return value
        except Exception as exc:  # noqa: BLE001 - report and retry
            print(label, f"attempt {attempt} failed:", type(exc).__name__, str(exc)[:180])
            time.sleep(4)
    return None


def save(frame: pd.DataFrame, key: str) -> None:
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame["date"], errors="coerce"),
            "value": pd.to_numeric(frame["value"], errors="coerce"),
        }
    ).dropna()
    out = out.sort_values("date").drop_duplicates("date")
    out.to_csv(OUT / f"{key}.csv", index=False)
    print(key, "saved", len(out), out["date"].min().date(), "->", out["date"].max().date())


def fetch_csi(index_code: str) -> pd.DataFrame:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Referer": "https://www.csindex.com.cn/",
            "Accept": "application/json, text/plain, */*",
        }
    )
    response = session.get(
        "https://www.csindex.com.cn/csindex-home/perf/index-perf",
        params={
            "indexCode": index_code,
            "startDate": "20050101",
            "endDate": END,
        },
        timeout=45,
    )
    response.raise_for_status()
    rows = response.json().get("data") or []
    if not rows:
        raise ValueError(f"empty CSI data for {index_code}")
    return pd.DataFrame(
        {
            "date": [row["tradeDate"] for row in rows],
            "value": [row["close"] for row in rows],
        }
    )


def fetch_xndx() -> pd.DataFrame:
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125 Safari/537.36"}
    )
    session.get("https://indexes.nasdaqomx.com/Index/History/XNDX", timeout=30)
    response = session.post(
        "https://indexes.nasdaqomx.com/Index/HistoryChartData",
        data={
            "id": "XNDX",
            "startDate": "1999-01-01T00:00:00.000",
            "endDate": "2026-10-20T00:00:00.000",
            "timeOfDay": "EOD",
        },
        headers={
            "Referer": "https://indexes.nasdaqomx.com/Index/History/XNDX",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=60,
    )
    response.raise_for_status()
    rows = response.json()
    if not rows:
        raise ValueError("empty XNDX data")
    return pd.DataFrame(
        {
            "date": [pd.to_datetime(row["x"], unit="ms", utc=True).tz_localize(None).normalize() for row in rows],
            "value": [row["y"] for row in rows],
        }
    )


def fetch_usdcny() -> pd.DataFrame:
    # Bank of China central parity / conversion rate; the columns are
    # 日期, 中行汇买价, 中行钞买价, 中行钞卖价/汇卖价, 央行中间价, 中行折算价.
    frame = ak.currency_boc_sina(symbol="美元", start_date="20060101", end_date=END)
    central = pd.to_numeric(frame.iloc[:, 4], errors="coerce")
    converted = pd.to_numeric(frame.iloc[:, 5], errors="coerce")
    rate = central.fillna(converted) / 100.0
    return pd.DataFrame(
        {
            "date": pd.to_datetime(frame.iloc[:, 0], errors="coerce"),
            "value": rate,
        }
    ).dropna()


def fetch_comex_gold() -> pd.DataFrame:
    """COMEX continuous gold (USD/oz), daily, from Eastmoney's public K-line API."""
    response = requests.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": "101.GC00Y",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "klt": "101",
            "fqt": "0",
            "beg": "20060101",
            "end": END,
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
        },
        timeout=45,
    )
    response.raise_for_status()
    rows = (response.json().get("data") or {}).get("klines") or []
    if not rows:
        raise ValueError("empty COMEX gold data")
    frame = pd.DataFrame(
        [
            {
                "date": row.split(",")[0],
                # K-line fields: date, open, close, high, low, volume, ...
                "value": float(row.split(",")[2]),
            }
            for row in rows
        ]
    )
    return frame


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for key, code in CSI_SERIES.items():
        frame = retry(f"CSI {code}", lambda code=code: fetch_csi(code))
        if frame is not None:
            save(frame, key)

    fx = retry("USD/CNY BOC", fetch_usdcny)
    if fx is not None:
        save(fx, "usdcny")

    xndx = retry("XNDX", fetch_xndx)
    if xndx is not None:
        save(xndx, "ndx100_usd")
        if fx is not None:
            usd = xndx.rename(columns={"value": "usd_close"}).sort_values("date")
            fx_sorted = fx.sort_values("date")
            merged = pd.merge_asof(
                usd,
                fx_sorted.rename(columns={"value": "usdcny"}),
                on="date",
                direction="backward",
            ).dropna()
            merged["value"] = merged["usd_close"] * merged["usdcny"]
            save(merged[["date", "value"]], "ndx100")

    gold_usd = retry("COMEX gold", fetch_comex_gold)
    if gold_usd is not None:
        save(gold_usd, "gold_comex_usd")
        if fx is not None:
            merged = pd.merge_asof(
                gold_usd.sort_values("date"),
                fx.sort_values("date").rename(columns={"value": "usdcny"}),
                on="date",
                direction="backward",
            ).dropna()
            # USD/oz -> CNY/gram.
            merged["value"] = merged["value"] * merged["usdcny"] / 31.1034768
            save(merged[["date", "value"]], "gold")
        else:
            print("USD/CNY unavailable; gold CNY series not rebuilt")

    bond = retry(
        "bond",
        lambda: ak.bond_new_composite_index_cbond(indicator="财富", period="总值"),
    )
    if bond is not None:
        save(
            pd.DataFrame({"date": bond.iloc[:, 0], "value": bond.iloc[:, 1]}),
            "bond",
        )

    print("done. now run: python scripts/calibrate.py")


if __name__ == "__main__":
    main()
