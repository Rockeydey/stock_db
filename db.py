from __future__ import annotations

import duckdb

from core_config import DATA_DIR, DB_PATH


def get_conn() -> duckdb.DuckDBPyConnection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB_PATH))


def init_db() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY,
            symbol VARCHAR NOT NULL,
            exchange VARCHAR NOT NULL,
            table_name VARCHAR NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, exchange)
        )
        """
    )

    conn.execute("CREATE SEQUENCE IF NOT EXISTS stocks_id_seq START 1;")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_log (
            id BIGINT PRIMARY KEY,
            stock_id INTEGER NOT NULL,
            from_date DATE NOT NULL,
            to_date DATE NOT NULL,
            status VARCHAR NOT NULL,
            rows_inserted INTEGER DEFAULT 0,
            message VARCHAR,
            refreshed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_id, from_date, to_date, status)
        )
        """
    )

    conn.execute("CREATE SEQUENCE IF NOT EXISTS refresh_log_id_seq START 1;")
    conn.close()
