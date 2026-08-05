from __future__ import annotations

from typing import Any

import duckdb

from db import get_conn
from stock_utils import normalize_symbol, sanitize_table_name


def create_stock_table(conn: duckdb.DuckDBPyConnection, table_name: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            trade_date DATE PRIMARY KEY,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            adj_close DOUBLE,
            volume BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def drop_stock_table(conn: duckdb.DuckDBPyConnection, table_name: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")


def get_stocks() -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, symbol, exchange, table_name, created_at FROM stocks ORDER BY exchange, symbol"
    ).fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "symbol": row[1],
            "exchange": row[2],
            "table_name": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def add_stock(symbol: str, exchange: str) -> tuple[bool, str]:
    symbol = normalize_symbol(symbol)
    exchange = exchange.strip().upper()

    if not symbol:
        return False, "Symbol is required."
    if exchange not in {"NSE", "BSE"}:
        return False, "Exchange must be NSE or BSE."

    table_name = sanitize_table_name(exchange, symbol)
    conn = get_conn()
    try:
        create_stock_table(conn, table_name)
        conn.execute(
            """
            INSERT INTO stocks (id, symbol, exchange, table_name)
            VALUES (nextval('stocks_id_seq'), ?, ?, ?)
            """,
            [symbol, exchange, table_name],
        )
        return True, f"Added {symbol} ({exchange}) and created table {table_name}."
    except Exception as ex:
        drop_stock_table(conn, table_name)
        return False, f"Could not add stock: {ex}"
    finally:
        conn.close()


def delete_stock(stock_id: int) -> tuple[bool, str]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT table_name, symbol, exchange FROM stocks WHERE id = ?", [stock_id]
        ).fetchone()
        if not row:
            return False, "Stock not found."

        table_name, symbol, exchange = row
        drop_stock_table(conn, table_name)
        conn.execute("DELETE FROM refresh_log WHERE stock_id = ?", [stock_id])
        conn.execute("DELETE FROM stocks WHERE id = ?", [stock_id])
        return True, f"Deleted {symbol} ({exchange}) and dropped table {table_name}."
    except Exception as ex:
        return False, f"Could not delete stock: {ex}"
    finally:
        conn.close()


def log_exists(conn: duckdb.DuckDBPyConnection, stock_id: int, from_date: str, to_date: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM refresh_log
        WHERE stock_id = ?
          AND from_date = ?
          AND to_date = ?
          AND status = 'SUCCESS'
        LIMIT 1
        """,
        [stock_id, from_date, to_date],
    ).fetchone()
    return row is not None


def record_log(
    conn: duckdb.DuckDBPyConnection,
    stock_id: int,
    from_date: str,
    to_date: str,
    status: str,
    rows_inserted: int,
    message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO refresh_log (id, stock_id, from_date, to_date, status, rows_inserted, message)
        VALUES (nextval('refresh_log_id_seq'), ?, ?, ?, ?, ?, ?)
        ON CONFLICT (stock_id, from_date, to_date, status)
        DO UPDATE SET
            rows_inserted = EXCLUDED.rows_inserted,
            message = EXCLUDED.message,
            refreshed_at = now()
        """,
        [stock_id, from_date, to_date, status, rows_inserted, message],
    )


def list_main_tables() -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
    ).fetchall()
    conn.close()
    return [row[0] for row in rows]


def fetch_table_rows(table_name: str, limit: int = 500) -> tuple[list[str], list[list[Any]]]:
    conn = get_conn()
    exists = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        LIMIT 1
        """,
        [table_name],
    ).fetchone()
    if not exists:
        conn.close()
        return [], []

    df = conn.execute(f"SELECT * FROM {table_name} ORDER BY 1 DESC LIMIT {limit}").df()
    conn.close()
    return list(df.columns), df.fillna("").values.tolist()
