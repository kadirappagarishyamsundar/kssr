"""
Core analysis logic: pick the forecast a buyer could actually use, compare to
actuals, and summarise the error.

Conventions
-----------
* error_mw = forecast_mw - actual_mw
  Positive error = wind OVER-forecast = less wind than planned = the buyer is
  short and must cover the gap. So the upper error percentiles are the
  "buffer to hold" numbers.
* WINDFOR is hourly, FUELHH is half-hourly. Actuals are averaged to the hour
  (mean of the two half-hours starting at each hour) so both sides are in MW
  over the same hour.
* The cutoff is a wall-clock time in Europe/London on the day BEFORE delivery,
  converted to UTC (matters outside winter; handled correctly anyway).
"""
from __future__ import annotations

from datetime import date, time

import numpy as np
import pandas as pd

LONDON = "Europe/London"


def hourly_actuals(actuals: pd.DataFrame) -> pd.DataFrame:
    """Half-hourly FUELHH wind -> hourly mean MW. Drops hours missing a half-hour."""
    s = actuals.set_index("startTime")["generation"].sort_index()
    h = s.resample("1h").agg(["mean", "count"])
    h = h[h["count"] == 2]
    return h["mean"].rename("actual_mw").reset_index()


def latest_forecast_at_cutoff(fc: pd.DataFrame, cutoff_time: time = time(9, 0)) -> pd.DataFrame:
    """
    For each target hour, return the forecast row with the latest publishTime
    that is <= the day-ahead decision cutoff (D-1 at `cutoff_time`, London time).
    Forecasts published after the cutoff are ignored (they were not available).
    """
    df = fc.rename(columns={"generation": "forecast_mw"}).copy()
    delivery_date = df["startTime"].dt.tz_convert(LONDON).dt.normalize().dt.tz_localize(None)
    cutoff_local = delivery_date - pd.Timedelta(days=1) + pd.Timedelta(
        hours=cutoff_time.hour, minutes=cutoff_time.minute
    )
    df["delivery_date"] = delivery_date.dt.date
    df["decision_date"] = (delivery_date - pd.Timedelta(days=1)).dt.date
    df["cutoff"] = cutoff_local.dt.tz_localize(LONDON).dt.tz_convert("UTC")

    eligible = df[df["publishTime"] <= df["cutoff"]]
    idx = eligible.groupby("startTime")["publishTime"].idxmax()
    out = eligible.loc[idx].copy()
    out["horizon_h"] = (out["startTime"] - out["publishTime"]).dt.total_seconds() / 3600
    cols = ["startTime", "publishTime", "cutoff", "delivery_date", "decision_date",
            "forecast_mw", "horizon_h"]
    return out[cols].sort_values("startTime").reset_index(drop=True)


def build_evaluation(
    actuals_h: pd.DataFrame,
    fc: pd.DataFrame,
    cutoff_time: time = time(9, 0),
    decision_from: date = date(2026, 1, 1),
    decision_to: date = date(2026, 1, 31),
) -> pd.DataFrame:
    """Forecast-at-cutoff joined to actuals, limited to decisions made in the window."""
    sel = latest_forecast_at_cutoff(fc, cutoff_time)
    sel = sel[(sel["decision_date"] >= decision_from) & (sel["decision_date"] <= decision_to)]
    df = sel.merge(actuals_h, on="startTime", how="inner")
    df["error_mw"] = df["forecast_mw"] - df["actual_mw"]
    df["abs_error_mw"] = df["error_mw"].abs()
    df["hour"] = df["startTime"].dt.tz_convert(LONDON).dt.hour
    return df


def summarize(df: pd.DataFrame) -> dict:
    """Headline accuracy numbers for an evaluation frame."""
    e = df["error_mw"]
    mean_actual = df["actual_mw"].mean()
    mae = e.abs().mean()
    return {
        "n_hours": int(len(df)),
        "mean_actual_mw": float(mean_actual),
        "mae_mw": float(mae),
        "rmse_mw": float(np.sqrt((e ** 2).mean())),
        "bias_mw": float(e.mean()),
        "nmae_pct": float(mae / mean_actual * 100),  # MAE as % of mean generation
        "error_p10_mw": float(e.quantile(0.10)),
        "error_p50_mw": float(e.quantile(0.50)),
        "error_p90_mw": float(e.quantile(0.90)),  # shortfall to cover ~90% of the time
    }


def by_group(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """MAE / bias / RMSE grouped by e.g. 'hour' or 'delivery_date'."""
    g = df.groupby(key)["error_mw"]
    return pd.DataFrame({
        "mae_mw": g.apply(lambda x: x.abs().mean()),
        "bias_mw": g.mean(),
        "rmse_mw": g.apply(lambda x: np.sqrt((x ** 2).mean())),
        "n": g.size(),
    }).reset_index()


def by_horizon(
    actuals_h: pd.DataFrame,
    fc: pd.DataFrame,
    decision_from: date = date(2026, 1, 1),
    decision_to: date = date(2026, 1, 31),
    edges: tuple = (0, 3, 6, 12, 18, 24, 30, 36, 42, 48, 72),
) -> pd.DataFrame:
    """
    Accuracy vs forecast lead time, using EVERY forecast version (not just the
    one a buyer sees at the cutoff). Shows how accuracy degrades with horizon.
    Forecasts published after their target hour (negative horizon) are excluded.
    """
    df = fc.rename(columns={"generation": "forecast_mw"}).copy()
    df["horizon_h"] = (df["startTime"] - df["publishTime"]).dt.total_seconds() / 3600
    delivery = df["startTime"].dt.tz_convert(LONDON).dt.normalize().dt.tz_localize(None)
    decision = (delivery - pd.Timedelta(days=1)).dt.date
    df = df[(decision >= decision_from) & (decision <= decision_to) & (df["horizon_h"] >= 0)]
    df = df.merge(actuals_h, on="startTime", how="inner")
    df["error_mw"] = df["forecast_mw"] - df["actual_mw"]
    df["bucket"] = pd.cut(df["horizon_h"], bins=list(edges), right=False)
    g = df.groupby("bucket", observed=True)["error_mw"]
    out = pd.DataFrame({
        "mae_mw": g.apply(lambda x: x.abs().mean()),
        "bias_mw": g.mean(),
        "n": g.size(),
    }).reset_index()
    out["label"] = out["bucket"].map(lambda b: f"{int(b.left)}-{int(b.right)}h")
    out["horizon_start_h"] = out["bucket"].map(lambda b: int(b.left))
    return out.drop(columns="bucket")


def error_histogram(df: pd.DataFrame, bins: int = 24) -> pd.DataFrame:
    """Histogram of error_mw for the distribution chart."""
    counts, edges = np.histogram(df["error_mw"], bins=bins)
    return pd.DataFrame({"bin_start": edges[:-1], "bin_end": edges[1:], "count": counts})
