"""
This script updates today's stock data for all configured stocks in the database. It initializes the database connection, retrieves the list of stocks, and fetches and stores today's data for each stock. Finally, it prints the total number of rows in the `todays_data` table after the update.

Updated: 2026-08-09

"""


from __future__ import annotations

from db import get_conn, init_db
from stock_data_service import fetch_and_store_todays_data
def main() -> None:
    init_db()
    conn = get_conn()

    try:
        rows = conn.execute(
            "SELECT id, symbol, exchange, created_at FROM stocks ORDER BY exchange, symbol"
        ).fetchall()
        stocks = [
            {
                "id": row[0],
                "symbol": row[1],
                "exchange": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]
        print(f"Stocks configured: {len(stocks)}")

        for stock in stocks:
            status, message = fetch_and_store_todays_data(
                conn,
                stock_id=stock["id"],
                symbol=stock["symbol"],
                exchange=stock["exchange"],
            )
            print(f"{stock['symbol']} ({stock['exchange']}): {status} - {message}")

        total = conn.execute("SELECT COUNT(*) FROM todays_data").fetchone()[0]
        print(f"todays_data rows: {total}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
