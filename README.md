# Wind forecast accuracy for day-ahead buying (GB)

A small web app that shows, for each delivery day in the pilot period, the national wind forecast a buyer
actually had when making the day-ahead decision, and how accurate those forecasts were against actual generation.

**Live app:** https://kssr-i11s.vercel.app 
**API:** https://kssr-nine.vercel.app/docs   
**Demo video:** <YOUTUBE_URL>

## Scope and key assumptions
- Data: Elexon only. Actuals = FUELHH (`fuelType=WIND`, half-hourly). Forecasts = WINDFOR (hourly, many versions per target hour).
- "Decisions made in January 2026" = decisions on 1-31 Jan, i.e. delivery days **2 Jan - 1 Feb 2026** (744 hours).
- **Decision cutoff:** the forecast used for a delivery hour is the latest version with `publishTime` <= the cutoff on the previous day
  (default 09:00 London time; selectable in the UI). Later versions are ignored because the buyer did not have them.
- WINDFOR is hourly and FUELHH is half-hourly, so actuals are averaged to the hour (FUELHH values are 30-minute averages in MW).
- Error = forecast - actual. Positive means wind was over-forecast, so the buyer is short.
- Metrics: MAE, RMSE, bias, MAE as % of mean generation, and error P10/P50/P90 (the P90 is the "shortfall buffer").
- Forecasts published after the hour they describe (negative lead time) are excluded.

## Finding to be aware of
Over the period WINDFOR averaged roughly 1.7 GW above FUELHH outturn at every lead time. The Elexon documentation for these datasets
does not state their coverage, so we cannot tell whether this is forecast error or a definitional difference. The app reports the raw
error and the buffer needed to cover it; confirming coverage with Elexon is the recommended next step.

## Repository layout
```
backend/            FastAPI app
  core.py           cutoff selection + accuracy metrics (pure pandas, unit tested)
  main.py           API endpoints
  test_core.py      unit tests
  data/processed/   small CSVs the app serves (built by scripts/prep_data.py)
frontend/           React (Vite) app: Forecast and Accuracy pages
scripts/
  explore_elexon.py downloads Jan 2026 data from Elexon into data/raw/ and prints a data-quality report
  prep_data.py      builds backend/data/processed/ and prints headline numbers
docker-compose.yml  runs backend + frontend together
```

## Run with Docker
```
docker compose up --build
```
Open http://localhost:8080 (API docs at http://localhost:8000/docs).

## Run locally without Docker
```
pip install -r backend/requirements.txt
cd backend && uvicorn main:app --reload        # terminal 1
cd frontend && npm install && npm run dev      # terminal 2 -> http://localhost:5173
```

## Rebuild the data (optional; processed files are committed)
```
pip install requests pandas pyarrow
python scripts/explore_elexon.py
python scripts/prep_data.py
```

## Tests
```
cd backend && pip install pytest && python -m pytest -q
```

## Deployment (Vercel)
Two Vercel projects from this repo: `backend/` (FastAPI) and `frontend/` (Vite, with env var `VITE_API_URL` set to the backend URL).

## AI tools
This project was built with assistance from Claude (Anthropic) for design discussion and code generation. I reviewed, ran and tested the code.
