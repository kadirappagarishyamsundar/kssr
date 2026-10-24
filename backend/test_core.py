from datetime import date, time

import pandas as pd

from core import build_evaluation, hourly_actuals, latest_forecast_at_cutoff


def ts(s):
    return pd.Timestamp(s, tz="UTC")


def make_fc(rows):
    return pd.DataFrame(rows, columns=["startTime", "publishTime", "generation"]).assign(
        startTime=lambda d: d["startTime"].map(ts),
        publishTime=lambda d: d["publishTime"].map(ts),
    )


def test_picks_latest_forecast_before_cutoff_and_ignores_later_ones():
    # Target: 2026-01-10 12:00. Cutoff (09:00 on Jan 9) -> only first two are usable.
    fc = make_fc([
        ("2026-01-10 12:00", "2026-01-08 22:30", 100.0),
        ("2026-01-10 12:00", "2026-01-09 07:30", 200.0),  # latest usable
        ("2026-01-10 12:00", "2026-01-09 09:30", 300.0),  # after cutoff -> ignored
        ("2026-01-10 12:00", "2026-01-10 11:30", 999.0),  # near real time -> ignored
    ])
    out = latest_forecast_at_cutoff(fc, time(9, 0))
    assert len(out) == 1
    assert out.loc[0, "forecast_mw"] == 200.0
    assert out.loc[0, "horizon_h"] == 28.5


def test_cutoff_is_inclusive():
    fc = make_fc([("2026-01-10 12:00", "2026-01-09 09:00", 50.0)])
    out = latest_forecast_at_cutoff(fc, time(9, 0))
    assert len(out) == 1


def test_target_with_no_usable_forecast_is_dropped():
    fc = make_fc([("2026-01-10 12:00", "2026-01-09 10:00", 50.0)])
    assert latest_forecast_at_cutoff(fc, time(9, 0)).empty


def test_negative_horizon_forecasts_never_selected():
    fc = make_fc([("2026-01-10 12:00", "2026-01-10 14:30", 50.0)])
    assert latest_forecast_at_cutoff(fc, time(9, 0)).empty


def test_hourly_actuals_averages_half_hours_and_drops_incomplete_hours():
    act = pd.DataFrame({
        "startTime": [ts("2026-01-10 12:00"), ts("2026-01-10 12:30"), ts("2026-01-10 13:00")],
        "generation": [100.0, 200.0, 300.0],  # 13:30 missing -> 13:00 hour dropped
    })
    h = hourly_actuals(act)
    assert len(h) == 1
    assert h.loc[0, "actual_mw"] == 150.0


def test_build_evaluation_error_sign_and_decision_window():
    fc = make_fc([
        ("2026-01-10 12:00", "2026-01-09 07:30", 200.0),
        ("2026-02-05 12:00", "2026-02-04 07:30", 200.0),  # decision Feb 4 -> outside window
    ])
    act = pd.DataFrame({
        "startTime": [ts("2026-01-10 12:00"), ts("2026-01-10 12:30"),
                      ts("2026-02-05 12:00"), ts("2026-02-05 12:30")],
        "generation": [100.0, 100.0, 100.0, 100.0],
    })
    ev = build_evaluation(hourly_actuals(act), fc, time(9, 0), date(2026, 1, 1), date(2026, 1, 31))
    assert len(ev) == 1
    assert ev.loc[0, "error_mw"] == 100.0  # forecast 200 vs actual 100 -> over-forecast
