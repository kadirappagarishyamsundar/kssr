"""
Step 2: turn the raw downloads into the small dataset the app ships with.

    python scripts/prep_data.py   (run from the repo root)

Reads  data/raw/*.parquet   (made by explore_elexon.py)
Writes backend/data/processed/actuals_hourly.csv.gz and windfor.csv.gz
Then prints the headline accuracy numbers as a sanity check.

Scope: decisions made in January 2026 => delivery days 2 Jan - 1 Feb 2026.
"""
from datetime import date, time
from pathlib import Path

import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from core import build_evaluation, hourly_actuals, summarize

RAW = Path("data/raw")
OUT = Path("backend/data/processed")
OUT.mkdir(parents=True, exist_ok=True)

actuals = pd.read_parquet(RAW / "actuals_wind_2026-01.parquet")
fc = pd.read_parquet(RAW / "windfor_2025-12_2026-01.parquet")

lo = pd.Timestamp("2026-01-02", tz="UTC")  # first delivery day in scope
hi = pd.Timestamp("2026-02-02", tz="UTC")  # exclusive: last delivery day is 1 Feb

ah = hourly_actuals(actuals)
ah = ah[(ah["startTime"] >= lo) & (ah["startTime"] < hi)]
fc = fc[(fc["startTime"] >= lo) & (fc["startTime"] < hi)][["startTime", "publishTime", "generation"]]

print(f"hourly actuals: {len(ah)} rows, {ah['startTime'].min()} -> {ah['startTime'].max()}")
if len(ah) != 744:
    print("  WARNING: expected 744 hours (2 Jan - 1 Feb). Did you re-run explore_elexon.py "
          "after setting JAN_END to 2026-02-02?")
print(f"forecast rows kept: {len(fc)}")

ah.to_csv(OUT / "actuals_hourly.csv.gz", index=False)
fc.to_csv(OUT / "windfor.csv.gz", index=False)

ev = build_evaluation(ah, fc, time(9, 0), date(2026, 1, 1), date(2026, 1, 31))
print("\nHeadline accuracy at 09:00 cutoff:")
for k, v in summarize(ev).items():
    print(f"  {k}: {round(v, 1)}")
print("\nSaved to", OUT.resolve())
