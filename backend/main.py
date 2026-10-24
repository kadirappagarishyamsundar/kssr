"""
FastAPI backend. Run locally:

    pip install fastapi uvicorn pandas
    uvicorn main:app --reload

Docs UI: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import json
from datetime import date, time
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import core

DATA = Path(__file__).parent / "data" / "processed"
DECISION_FROM = date(2026, 1, 1)
DECISION_TO = date(2026, 1, 31)
DEFAULT_CUTOFF = "09:00"

app = FastAPI(title="Wind forecast accuracy API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

_actuals = pd.read_csv(DATA / "actuals_hourly.csv.gz")
_actuals["startTime"] = pd.to_datetime(_actuals["startTime"], utc=True)
_fc = pd.read_csv(DATA / "windfor.csv.gz")
_fc["startTime"] = pd.to_datetime(_fc["startTime"], utc=True)
_fc["publishTime"] = pd.to_datetime(_fc["publishTime"], utc=True)


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe list (NaN -> null, timestamps -> ISO strings)."""
    df = df.copy()
    num = df.select_dtypes("number").columns
    df[num] = df[num].round(1)
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _parse_cutoff(cutoff: str) -> time:
    try:
        hh, mm = cutoff.split(":")
        return time(int(hh), int(mm))
    except Exception:
        raise HTTPException(status_code=422, detail="cutoff must be HH:MM, e.g. 09:00")


@lru_cache(maxsize=64)
def _evaluation(cutoff: str) -> pd.DataFrame:
    return core.build_evaluation(_actuals, _fc, _parse_cutoff(cutoff), DECISION_FROM, DECISION_TO)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    ev = _evaluation(DEFAULT_CUTOFF)
    return {
        "default_cutoff": DEFAULT_CUTOFF,
        "cutoff_timezone": core.LONDON,
        "decision_from": DECISION_FROM.isoformat(),
        "decision_to": DECISION_TO.isoformat(),
        "first_delivery_date": str(ev["delivery_date"].min()),
        "last_delivery_date": str(ev["delivery_date"].max()),
        "error_definition": "forecast_mw - actual_mw (positive = wind over-forecast)",
    }


@app.get("/api/forecast")
def forecast(delivery_date: date, cutoff: str = DEFAULT_CUTOFF):
    """The forecast a buyer would have at the cutoff on D-1, next to what actually happened."""
    ev = _evaluation(cutoff)
    day = ev[ev["delivery_date"] == delivery_date]
    if day.empty:
        raise HTTPException(status_code=404, detail="No data for that delivery date")
    return {
        "delivery_date": delivery_date.isoformat(),
        "cutoff_utc": day["cutoff"].iloc[0].isoformat(),
        "latest_publish_used": day["publishTime"].max().isoformat(),
        "summary": {k: round(v, 1) for k, v in core.summarize(day).items()},
        "hours": _records(day[["startTime", "publishTime", "forecast_mw", "actual_mw",
                               "error_mw", "horizon_h"]]),
    }


@app.get("/api/accuracy/summary")
def accuracy_summary(cutoff: str = DEFAULT_CUTOFF):
    return {k: round(v, 1) for k, v in core.summarize(_evaluation(cutoff)).items()}


@app.get("/api/accuracy/by-hour")
def accuracy_by_hour(cutoff: str = DEFAULT_CUTOFF):
    return _records(core.by_group(_evaluation(cutoff), "hour"))


@app.get("/api/accuracy/by-day")
def accuracy_by_day(cutoff: str = DEFAULT_CUTOFF):
    out = core.by_group(_evaluation(cutoff), "delivery_date")
    out["delivery_date"] = out["delivery_date"].astype(str)
    return _records(out)


@app.get("/api/accuracy/by-horizon")
def accuracy_by_horizon():
    return _records(core.by_horizon(_actuals, _fc, DECISION_FROM, DECISION_TO))


@app.get("/api/accuracy/error-distribution")
def error_distribution(cutoff: str = DEFAULT_CUTOFF, bins: int = Query(24, ge=5, le=100)):
    return _records(core.error_histogram(_evaluation(cutoff), bins))
