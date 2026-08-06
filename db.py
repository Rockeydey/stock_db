from __future__ import annotations

import re

import duckdb

from core_config import DATA_DIR, DB_PATH


def get_conn() -> duckdb.DuckDBPyConnection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB_PATH))


def _is_safe_identifier(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""))


def init_db() -> None:
    conn = get_conn()
    legacy_stock_tables: list[tuple[int, str]] = []

    stocks_exists = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = 'stocks'
        LIMIT 1
        """
    ).fetchone()

    if stocks_exists:
        stock_columns = [row[1] for row in conn.execute("PRAGMA table_info('stocks')").fetchall()]
        if "table_name" in stock_columns:
            legacy_stock_tables = conn.execute(
                "SELECT id, table_name FROM stocks WHERE table_name IS NOT NULL"
            ).fetchall()

            conn.execute("DROP TABLE IF EXISTS stocks_new")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stocks_new (
                    id INTEGER PRIMARY KEY,
                    symbol VARCHAR NOT NULL,
                    exchange VARCHAR NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, exchange)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO stocks_new (id, symbol, exchange, created_at)
                SELECT id, symbol, exchange, created_at FROM stocks
                """
            )
            conn.execute("DROP TABLE stocks")
            conn.execute("ALTER TABLE stocks_new RENAME TO stocks")
    else:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stocks (
                id INTEGER PRIMARY KEY,
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, exchange)
            )
            """
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_data (
            stock_id INTEGER NOT NULL,
            stock_name VARCHAR,
            exchange VARCHAR,
            symbol VARCHAR,
            trade_date DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            adj_close DOUBLE,
            volume BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_id, trade_date)
        )
        """
    )

    # Backfill schema changes for existing databases.
    conn.execute("ALTER TABLE stock_data ADD COLUMN IF NOT EXISTS stock_name VARCHAR")
    conn.execute("ALTER TABLE stock_data ADD COLUMN IF NOT EXISTS exchange VARCHAR")
    conn.execute("ALTER TABLE stock_data ADD COLUMN IF NOT EXISTS symbol VARCHAR")

    # Migrate legacy rows from old per-stock tables if present, then remove those tables.
    for stock_id, table_name in legacy_stock_tables:
        if not _is_safe_identifier(table_name):
            continue

        table_exists = conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = ?
            LIMIT 1
            """,
            [table_name],
        ).fetchone()
        if not table_exists:
            continue

        conn.execute(
            f"""
            INSERT INTO stock_data (stock_id, trade_date, open, high, low, close, adj_close, volume, created_at)
            SELECT ?, trade_date, open, high, low, close, adj_close, volume, created_at
            FROM {table_name}
            ON CONFLICT (stock_id, trade_date) DO NOTHING
            """,
            [stock_id],
        )
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

    next_stock_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM stocks").fetchone()[0]
    conn.execute("DROP SEQUENCE IF EXISTS stocks_id_seq")
    conn.execute(f"CREATE SEQUENCE stocks_id_seq START {next_stock_id};")

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

    next_refresh_log_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM refresh_log").fetchone()[0]
    conn.execute("DROP SEQUENCE IF EXISTS refresh_log_id_seq")
    conn.execute(f"CREATE SEQUENCE refresh_log_id_seq START {next_refresh_log_id};")
    conn.close()
