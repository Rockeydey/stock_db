"""
Purpose: This module provides functions to initialize and 
manage the DuckDB database for storing stock data. 
It includes functionality to create necessary tables, 
migrate legacy data, and ensure proper column order in the stock_data table.

"""


from __future__ import annotations

import re
import time

import duckdb

from src.core_config import DATA_DIR, DB_PATH


def get_conn(
    *,
    read_only: bool = False,
    retries: int = 8,
    retry_delay_seconds: float = 0.35,
) -> duckdb.DuckDBPyConnection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return duckdb.connect(str(DB_PATH), read_only=read_only)
        except duckdb.IOException as ex:
            last_error = ex
            error_text = str(ex).lower()
            if "file is already open" not in error_text:
                raise
            if attempt >= retries:
                break
            time.sleep(retry_delay_seconds)

    raise duckdb.IOException(
        "DuckDB file is locked by another Python process. "
        "Close the other process (or wait for it to finish) and retry. "
        f"Path: {DB_PATH}. Last error: {last_error}"
    )


def _is_safe_identifier(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""))


def _ensure_stock_data_column_order(conn: duckdb.DuckDBPyConnection) -> None:
    column_rows = conn.execute("PRAGMA table_info('stock_data')").fetchall()
    column_names = [row[1] for row in column_rows]
    if not column_names or "stock_name" not in column_names:
        return
    if column_names[0] == "stock_name":
        return

    conn.execute("DROP TABLE IF EXISTS stock_data_reordered")
    conn.execute(
        """
        CREATE TABLE stock_data_reordered (
            stock_name VARCHAR,
            stock_id INTEGER NOT NULL,
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
    conn.execute(
        """
        INSERT INTO stock_data_reordered (
            stock_name,
            stock_id,
            exchange,
            symbol,
            trade_date,
            open,
            high,
            low,
            close,
            adj_close,
            volume,
            created_at
        )
        SELECT
            stock_name,
            stock_id,
            exchange,
            symbol,
            trade_date,
            open,
            high,
            low,
            close,
            adj_close,
            volume,
            created_at
        FROM stock_data
        """
    )
    conn.execute("DROP TABLE stock_data")
    conn.execute("ALTER TABLE stock_data_reordered RENAME TO stock_data")


def _ensure_todays_data_one_row_per_stock(conn: duckdb.DuckDBPyConnection) -> None:
    column_rows = conn.execute("PRAGMA table_info('todays_data')").fetchall()
    if not column_rows:
        return

    pk_columns = [row[1] for row in column_rows if row[5] > 0]
    if pk_columns == ["stock_id"]:
        return

    conn.execute("DROP TABLE IF EXISTS todays_data_rekeyed")
    conn.execute(
        """
        CREATE TABLE todays_data_rekeyed (
            stock_id INTEGER NOT NULL,
            stock_name VARCHAR,
            exchange VARCHAR,
            symbol VARCHAR,
            quote_date DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            adj_close DOUBLE,
            volume BIGINT,
            current_price DOUBLE,
            pe_ratio_trailing DOUBLE,
            pe_ratio_forward DOUBLE,
            beta_5y_monthly DOUBLE,
            market_cap BIGINT,
            fifty_two_week_high DOUBLE,
            fifty_two_week_low DOUBLE,
            company_name VARCHAR,
            sector VARCHAR,
            industry VARCHAR,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_id)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO todays_data_rekeyed (
            stock_id,
            stock_name,
            exchange,
            symbol,
            quote_date,
            open,
            high,
            low,
            close,
            adj_close,
            volume,
            current_price,
            pe_ratio_trailing,
            pe_ratio_forward,
            beta_5y_monthly,
            market_cap,
            fifty_two_week_high,
            fifty_two_week_low,
            company_name,
            sector,
            industry,
            fetched_at
        )
        SELECT
            stock_id,
            stock_name,
            exchange,
            symbol,
            quote_date,
            open,
            high,
            low,
            close,
            adj_close,
            volume,
            current_price,
            pe_ratio_trailing,
            pe_ratio_forward,
            beta_5y_monthly,
            market_cap,
            fifty_two_week_high,
            fifty_two_week_low,
            company_name,
            sector,
            industry,
            fetched_at
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY stock_id
                    ORDER BY quote_date DESC, fetched_at DESC
                ) AS rn
            FROM todays_data
        ) ranked
        WHERE rn = 1
        """
    )
    conn.execute("DROP TABLE todays_data")
    conn.execute("ALTER TABLE todays_data_rekeyed RENAME TO todays_data")


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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS todays_data (
            stock_id INTEGER NOT NULL,
            stock_name VARCHAR,
            exchange VARCHAR,
            symbol VARCHAR,
            quote_date DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            adj_close DOUBLE,
            volume BIGINT,
            current_price DOUBLE,
            pe_ratio_trailing DOUBLE,
            pe_ratio_forward DOUBLE,
            beta_5y_monthly DOUBLE,
            market_cap BIGINT,
            fifty_two_week_high DOUBLE,
            fifty_two_week_low DOUBLE,
            company_name VARCHAR,
            sector VARCHAR,
            industry VARCHAR,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_id, quote_date)
        )
        """
    )

    # Backfill schema changes for existing databases.
    conn.execute("ALTER TABLE stock_data ADD COLUMN IF NOT EXISTS stock_name VARCHAR")
    conn.execute("ALTER TABLE stock_data ADD COLUMN IF NOT EXISTS exchange VARCHAR")
    conn.execute("ALTER TABLE stock_data ADD COLUMN IF NOT EXISTS symbol VARCHAR")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS current_price DOUBLE")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS pe_ratio_trailing DOUBLE")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS pe_ratio_forward DOUBLE")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS beta_5y_monthly DOUBLE")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS market_cap BIGINT")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS fifty_two_week_high DOUBLE")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS fifty_two_week_low DOUBLE")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS company_name VARCHAR")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS sector VARCHAR")
    conn.execute("ALTER TABLE todays_data ADD COLUMN IF NOT EXISTS industry VARCHAR")
    _ensure_stock_data_column_order(conn)
    _ensure_todays_data_one_row_per_stock(conn)

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
