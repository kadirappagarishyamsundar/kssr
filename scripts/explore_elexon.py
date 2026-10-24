"""
Step 1: download January 2026 wind data from Elexon and inspect it.

Usage:
    pip install requests pandas pyarrow
    python explore_elexon.py

Saves raw data to data/raw/ so later steps never need to call the API again.

NOTE: parameter names below follow the Elexon Insights stream endpoints as I
know them. If a request returns 400, open the endpoint's docs page (linked in
the challenge PDF) and compare parameter names / allowed date ranges.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.elexon.co.uk/bmrs/api/v1/datasets"
OUT = Path("data/raw")
OUT.mkdir(parents=True, exist_ok=True)

# Target window: the challenge only cares about decisions made in January 2026.
JAN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
JAN_END = datetime(2026, 2, 1, tzinfo=timezone.utc)

# Forecasts for early-January targets were published earlier, so fetch a wider
# publish window. Widen LOOKBACK_DAYS if the horizon check below shows forecasts
# published before this window.
LOOKBACK_DAYS = 14
# Stream endpoints can cap the range per request, so chunk to be safe.
CHUNK_DAYS = 7


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def get_json(url: str, params: dict) -> list[dict]:
    r = requests.get(url, params=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} for {r.url}\n{r.text[:500]}")
    body = r.json()
    # Stream endpoints return a bare list; non-stream ones wrap it in {"data": [...]}.
    return body["data"] if isinstance(body, dict) else body


def chunks(start: datetime, end: datetime, days: int):
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        yield cur, nxt
        cur = nxt


def fetch_actuals() -> pd.DataFrame:
    """FUELHH, WIND only. Filtered by settlement date."""
    rows: list[dict] = []
    for a, b in chunks(JAN_START, JAN_END, CHUNK_DAYS):
        params = {
            "settlementDateFrom": a.strftime("%Y-%m-%d"),
            # 'To' is inclusive on settlement date, so step back one day.
            "settlementDateTo": (b - timedelta(days=1)).strftime("%Y-%m-%d"),
            "fuelType": "WIND",
        }
        rows += get_json(f"{BASE}/FUELHH/stream", params)
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No FUELHH rows returned")
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df = df[df["fuelType"] == "WIND"].drop_duplicates(subset=["startTime"])
    return df.sort_values("startTime").reset_index(drop=True)


def fetch_forecasts() -> pd.DataFrame:
    """WINDFOR, filtered by publish time (one row per target time per vintage)."""
    rows: list[dict] = []
    start = JAN_START - timedelta(days=LOOKBACK_DAYS)
    for a, b in chunks(start, JAN_END, CHUNK_DAYS):
        params = {"publishDateTimeFrom": iso(a), "publishDateTimeTo": iso(b)}
        rows += get_json(f"{BASE}/WINDFOR/stream", params)
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No WINDFOR rows returned")
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df["publishTime"] = pd.to_datetime(df["publishTime"], utc=True)
    df = df.drop_duplicates(subset=["startTime", "publishTime"])
    df["horizon_h"] = (df["startTime"] - df["publishTime"]).dt.total_seconds() / 3600
    return df.sort_values(["startTime", "publishTime"]).reset_index(drop=True)


def report(actuals: pd.DataFrame, fc: pd.DataFrame) -> None:
    print("\n=== ACTUALS (FUELHH, WIND) ===")
    print(f"rows: {len(actuals)}  (January has 31*48 = 1488 half-hours)")
    print(f"range: {actuals['startTime'].min()} -> {actuals['startTime'].max()}")
    print(actuals["generation"].describe().round(1))
    full = pd.date_range(JAN_START, JAN_END - timedelta(minutes=30), freq="30min")
    missing = full.difference(pd.DatetimeIndex(actuals["startTime"]))
    print(f"missing half-hours in January: {len(missing)}")

    print("\n=== FORECASTS (WINDFOR) ===")
    print(f"rows: {len(fc)}")
    print(f"publishTime range: {fc['publishTime'].min()} -> {fc['publishTime'].max()}")
    print(f"startTime range:   {fc['startTime'].min()} -> {fc['startTime'].max()}")
    print(f"distinct publish times: {fc['publishTime'].nunique()}")
    pt = fc["publishTime"].drop_duplicates().sort_values()
    print("typical gap between publishes:", pt.diff().median())
    print("publish hours (UTC) seen:", sorted(pt.dt.hour.unique().tolist()))

    print("\nforecast horizon (hours between publishTime and startTime):")
    print(fc["horizon_h"].describe().round(1))
    print("horizon min/max:", round(fc["horizon_h"].min(), 1), round(fc["horizon_h"].max(), 1))

    per_target = fc.groupby("startTime").size()
    print("\nforecast vintages per target time:")
    print(per_target.describe().round(1))

    # Sanity check for the core design: is there a usable forecast before a
    # 09:00 UTC day-before cutoff for each January target?
    cutoff = (fc["startTime"].dt.normalize() - timedelta(days=1)) + timedelta(hours=9)
    usable = fc[fc["publishTime"] <= cutoff]
    targets_jan = fc[(fc["startTime"] >= JAN_START) & (fc["startTime"] < JAN_END)]["startTime"].unique()
    covered = usable["startTime"].isin(targets_jan)
    n_cov = usable.loc[covered, "startTime"].nunique()
    print(f"\ntargets with a forecast published before D-1 09:00 UTC: {n_cov} / {len(targets_jan)}")
    print("(if low, increase LOOKBACK_DAYS or reconsider the cutoff)")


def main() -> None:
    print("Fetching actuals...")
    actuals = fetch_actuals()
    actuals.to_parquet(OUT / "actuals_wind_2026-01.parquet")

    print("Fetching forecasts...")
    fc = fetch_forecasts()
    fc.to_parquet(OUT / "windfor_2025-12_2026-01.parquet")

    report(actuals, fc)
    print("\nSaved parquet files to", OUT.resolve())


if __name__ == "__main__":
    main()
