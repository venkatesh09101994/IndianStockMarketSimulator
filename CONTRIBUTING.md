# Contributing

Thanks for your interest in the Indian Stock Market Simulator!

## Development setup
1. Python 3.11+ and Node 18+.
2. `python -m venv venv && .\venv\Scripts\Activate.ps1`
3. `pip install -r requirements.txt`
4. `cd frontend && npm install`
5. Copy `.env.example` to `.env` and adjust.
6. Seed stocks: `python update_indian_stocks.py`
7. Backend: `python -m uvicorn app.main:app --app-dir backend --port 8000 --reload`
8. Frontend: `npm --prefix frontend run dev`

## Tests
```
python -m pytest backend/tests/
```

## How to add a stock
The app supports dynamic onboarding. Search for a ticker in the Stocks page; if not present, Yahoo Finance results appear with an "Add" button. Or call:
```
POST /api/stocks/add  {"symbol": "YESBANK"}
```
The backend fetches company info, quote, and ~2 years of daily history.

## Pull requests
- Keep changes focused and add tests for new logic.
- Follow existing code style (FastAPI + React/TS + Tailwind).
- Update `architecture.md` if you change core principles.