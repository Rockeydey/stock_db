# Flask + DuckDB Stock Dashboard (NSE/BSE)

This project provides:

- Flask web app framework
- DuckDB as database
- NSE/BSE day-level stock fetch process
- Settings page to add/delete stocks (creates/drops tables)
- DuckDB table browser page
- Refresh Data flow with log check to skip duplicate downloads for same date range

## Setup

1. Create and activate a Python virtual environment.
2. Install packages:
   - `pip install -r requirements.txt`
3. Run app:
   - `python app.py`
4. Open browser:
   - `http://127.0.0.1:5000`

## Pages

- Dashboard: `/`
  - Select date range
  - Click **Refresh Data**
- Settings: `/settings`
  - Add/remove stocks
- DuckDB Tables: `/tables`
  - View tables and rows

## Notes

- Database file: `data/stocks.duckdb`
- Stock table naming: `stock_<exchange>_<symbol>`
- Data source: Yahoo Finance (`yfinance`) using ticker mapping:
  - NSE → `.NS`
  - BSE → `.BO`
