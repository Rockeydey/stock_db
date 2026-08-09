from __future__ import annotations

from db import get_conn, init_db
from stock_data_service import fetch_and_store_todays_data
from stock_store import get_stocks


def main() -> None:
    init_db()
    conn = get_conn()

    try:
        stocks = get_stocks()
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
