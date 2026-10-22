"""Refresh the official total-return series used by scripts/calibrate.py.

Requires: pip install -r requirements-calibration.txt

Sources:
  - CSI total return indices (official):
      H00300 沪深300全收益, H00905 中证500全收益, H00922 中证红利全收益
  - S&P 500 Total Return (^SP500TR), converted to CNY with BOC USD/CNY.
  - Shanghai Composite Total Return 000888 (official from 2020-07-21), extended
    before that with the 510210 SSE Composite ETF cumulative NAV.
  - Nikkei 225 Total Return (official daily from 2023), extended before that
    with the 1320.T Nikkei 225 ETF adjusted close, converted with BOC JPY/CNY.
  - Hang Seng Gross Total Return 10068 (official from 2021-10), extended
    before that with the 2800.HK Tracker Fund adjusted close, converted with
    BOC HKD/CNY.
  - Nasdaq-100 Total Return Index (XNDX), converted to CNY with BOC USD/CNY.
  - Gold: COMEX continuous gold (USD/oz) from Eastmoney, converted to CNY/gram
    with the Bank of China USD/CNY central parity. This is a 20-year gold price
    proxy; it is not Shanghai Gold Exchange Au99.99.
  - Bonds: ChinaBond New Composite Wealth Index (total return).

The Shanghai/Nikkei/HSI series are intentionally labelled "official TR + ETF
proxy" when the official free history is shorter than the ETF history. The
ETF leg includes dividends and ETF fees; it is not a pure official index.

The app never calls these sources at runtime; it reads calibration.json.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

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


def fetch_boc_fx(symbol_cn: str) -> pd.DataFrame:
    """BOC central parity / conversion rate for 100 units of a currency.

    Columns: 日期, 中行汇买价, 中行钞买价, 中行钞卖价/汇卖价, 央行中间价,
    中行折算价. The resulting value is CNY per one unit.
    """
    frame = ak.currency_boc_sina(
        symbol=symbol_cn, start_date="20060101", end_date=END
    )
    central = pd.to_numeric(frame.iloc[:, 4], errors="coerce")
    converted = pd.to_numeric(frame.iloc[:, 5], errors="coerce")
    rate = central.fillna(converted) / 100.0
    return pd.DataFrame(
        {
            "date": pd.to_datetime(frame.iloc[:, 0], errors="coerce"),
            "value": rate,
        }
    ).dropna()


def fetch_usdcny() -> pd.DataFrame:
    return fetch_boc_fx("美元")


def fetch_yahoo_chart(symbol: str, field: str = "close") -> pd.DataFrame:
    """Daily Yahoo chart data; `field` is close or adjclose."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            )
        }
    )
    response = session.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + quote(symbol),
        params={
            "period1": 946684800,
            "period2": int(pd.Timestamp(END).timestamp()) + 2 * 86400,
            "interval": "1d",
            "events": "div,splits",
        },
        timeout=45,
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    indicators = result["indicators"]
    if field == "adjclose":
        values = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
    else:
        values = indicators["quote"][0].get("close") or []
    return pd.DataFrame(
        {
            "date": [
                datetime.fromtimestamp(value, timezone.utc).date()
                for value in timestamps
            ],
            "value": values,
        }
    ).dropna()


def fetch_nikkei_tr() -> pd.DataFrame:
    """Official Nikkei 225 Total Return daily CSV (daily data ~3 years)."""
    response = requests.get(
        "https://indexes.nikkei.co.jp/nkave/historical/"
        "nikkei_225_total_return_index_daily_en.csv",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=45,
    )
    response.raise_for_status()
    text = response.content.decode("utf-8-sig", errors="replace")
    rows = []
    for line in text.splitlines():
        parts = [part.strip().strip('"') for part in line.split(",")]
        if len(parts) >= 2 and parts[0][:4].isdigit() and "/" in parts[0]:
            rows.append((parts[0], parts[1]))
    if not rows:
        raise ValueError("empty Nikkei total-return CSV")
    return pd.DataFrame(rows, columns=["date", "value"])


def fetch_hsi_tr() -> pd.DataFrame:
    """Hang Seng Gross Total Return Index (10068.00), official daily."""
    response = requests.get(
        "https://www.hsi.com.hk/api/wsit-hsi-ddoc-ea-public-website-proxy/"
        "v1/product-data/pub/indexes/metadata/v2",
        params={
            "data": "valueHistoryPub",
            "language": "en-hk",
            "indexCodes": "10068.00",
        },
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            ),
            "Referer": "https://www.hsi.com.hk/eng/indexes/all-indexes/hsi",
            "Accept": "application/json",
        },
        timeout=45,
    )
    response.raise_for_status()
    rows = response.json()["data"][0].get("valueHistory") or []
    if not rows:
        raise ValueError("empty Hang Seng total-return data")
    return pd.DataFrame(
        {
            "date": [row["date"] for row in rows],
            "value": [row["close"] for row in rows],
        }
    )


def fetch_etf_cumulative_nav(code: str) -> pd.DataFrame:
    """Eastmoney fund cumulative NAV (dividends reinvested), daily."""
    response = requests.get(
        f"https://fund.eastmoney.com/pingzhongdata/{code}.js",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            )
        },
        timeout=45,
    )
    response.raise_for_status()
    match = re.search(
        r"Data_ACWorthTrend\s*=\s*(\[.*?\]);",
        response.content.decode("utf-8-sig", errors="ignore"),
        re.S,
    )
    if not match:
        raise ValueError(f"cumulative NAV not found for {code}")
    rows = json.loads(match.group(1))
    if not rows:
        raise ValueError(f"empty cumulative NAV for {code}")
    frame = pd.DataFrame(rows, columns=["timestamp", "value"])
    frame["date"] = pd.to_datetime(frame["timestamp"], unit="ms").dt.normalize()
    return frame[["date", "value"]]


def weekdays_only(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove weekend rows from fund NAV data (no trading on weekends)."""
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"])
    return result[result["date"].dt.dayofweek < 5]


def to_cny(frame: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """Convert a local-currency series to CNY with the latest BOC rate."""
    local = frame.copy()
    local["date"] = pd.to_datetime(local["date"])
    local["value"] = pd.to_numeric(local["value"], errors="coerce")
    local = local.dropna().sort_values("date")
    rates = fx.sort_values("date")
    merged = pd.merge_asof(
        local,
        rates.rename(columns={"value": "fx"}),
        on="date",
        direction="backward",
    ).dropna()
    merged["value"] = merged["value"] * merged["fx"]
    return merged[["date", "value"]]


def splice_series(
    official: pd.DataFrame, proxy: pd.DataFrame
) -> pd.DataFrame:
    """Use official TR from its first date; scale the ETF proxy before it.

    The two legs are joined at the first official date, so the level is
    continuous. Before that date the ETF total-return path is used (including
    its fees); after it the official index is used.
    """
    official = official.copy()
    proxy = proxy.copy()
    official["date"] = pd.to_datetime(official["date"])
    proxy["date"] = pd.to_datetime(proxy["date"])
    official["value"] = pd.to_numeric(official["value"], errors="coerce")
    proxy["value"] = pd.to_numeric(proxy["value"], errors="coerce")
    official = official.dropna().sort_values("date").reset_index(drop=True)
    proxy = proxy.dropna().sort_values("date").reset_index(drop=True)
    if official.empty:
        return proxy
    if proxy.empty:
        return official
    start = official["date"].iloc[0]
    before = proxy[proxy["date"] <= start]
    if before.empty:
        return official
    factor = float(official["value"].iloc[0]) / float(before["value"].iloc[-1])
    prefix = proxy[proxy["date"] < start].copy()
    prefix["value"] = prefix["value"] * factor
    return (
        pd.concat([prefix, official], ignore_index=True)
        .sort_values("date")
        .drop_duplicates("date", keep="last")
    )


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
    hkd = retry("HKD/CNY BOC", lambda: fetch_boc_fx("港币"))
    if hkd is not None:
        save(hkd, "hkdcny")
    jpy = retry("JPY/CNY BOC", lambda: fetch_boc_fx("日元"))
    if jpy is not None:
        save(jpy, "jpydncy")

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

    sp500 = retry("S&P 500 TR", lambda: fetch_yahoo_chart("^SP500TR"))
    if sp500 is not None:
        save(sp500, "sp500_tr_usd")
        if fx is not None:
            save(to_cny(sp500, fx), "sp500")

    sse_official = retry("CSI 000888", lambda: fetch_csi("000888"))
    if sse_official is not None:
        sse_official = sse_official[
            pd.to_datetime(sse_official["date"])
            >= pd.Timestamp("2020-07-21")
        ]
        save(sse_official, "sse_tr_cny")
    sse_proxy = retry("510210 NAV", lambda: fetch_etf_cumulative_nav("510210"))
    if sse_proxy is not None:
        sse_proxy = weekdays_only(sse_proxy)
        save(sse_proxy, "sse_etf_cny")
    if sse_official is not None and sse_proxy is not None:
        save(splice_series(sse_official, sse_proxy), "sse")

    nikkei_official = retry("Nikkei TR", fetch_nikkei_tr)
    if nikkei_official is not None:
        save(nikkei_official, "nikkei_tr_jpy")
    nikkei_proxy = retry(
        "1320.T ETF", lambda: fetch_yahoo_chart("1320.T", "adjclose")
    )
    if nikkei_proxy is not None:
        save(nikkei_proxy, "nikkei_etf_jpy")
    if nikkei_official is not None and nikkei_proxy is not None and jpy is not None:
        save(
            splice_series(
                to_cny(nikkei_official, jpy), to_cny(nikkei_proxy, jpy)
            ),
            "nikkei",
        )

    hsi_official = retry("HSI 10068", fetch_hsi_tr)
    if hsi_official is not None:
        save(hsi_official, "hsi_tr_hkd")
    hsi_proxy = retry(
        "2800.HK ETF", lambda: fetch_yahoo_chart("2800.HK", "adjclose")
    )
    if hsi_proxy is not None:
        save(hsi_proxy, "hsi_etf_hkd")
    if hsi_official is not None and hsi_proxy is not None and hkd is not None:
        save(
            splice_series(to_cny(hsi_official, hkd), to_cny(hsi_proxy, hkd)),
            "hsi",
        )

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

    print(
        "done. now run: python scripts/calibrate.py && "
        "python scripts/build_history_data.py"
    )


if __name__ == "__main__":
    main()
