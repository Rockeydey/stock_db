from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import duckdb
import pandas as pd
import yfinance as yf

from stock_store import log_exists, record_log
from stock_utils import exchange_symbol


def _normalize_download_frame(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def _fetch_from_yahoo(ticker: str, api_start: str, api_end: str) -> tuple[pd.DataFrame, str]:
    errors: list[str] = []

    try:
        df = yf.download(
            ticker,
            start=api_start,
            end=api_end,
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        df = _normalize_download_frame(df)
        if not df.empty:
            return df, "download(start,end)"
    except Exception as ex:
        errors.append(f"download(start,end): {ex}")

    try:
        df = yf.Ticker(ticker).history(
            start=api_start,
            end=api_end,
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
        df = _normalize_download_frame(df)
        if not df.empty:
            return df, "history(start,end)"
    except Exception as ex:
        errors.append(f"history(start,end): {ex}")

    try:
        # Last fallback: query long period and filter locally.
        df = yf.Ticker(ticker).history(
            period="max",
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
        df = _normalize_download_frame(df)
        if not df.empty:
            return df, "history(period=max)"
    except Exception as ex:
        errors.append(f"history(period=max): {ex}")

    msg = "; ".join(errors) if errors else "all Yahoo fetch attempts returned empty"
    return pd.DataFrame(), msg


def _resolve_stock_name(ticker: str, symbol: str) -> str:
    try:
        info = yf.Ticker(ticker).info
        if isinstance(info, dict):
            name = info.get("longName") or info.get("shortName")
            if isinstance(name, str) and name.strip():
                return name.strip()
    except Exception:
        pass

    # Fallback keeps a useful value even when metadata lookup fails.
    return symbol


def fetch_and_store_stock_data(
    conn: duckdb.DuckDBPyConnection,
    stock_id: int,
    symbol: str,
    exchange: str,
    from_date: str,
    to_date: str,
    overwrite_existing: bool = False,
) -> tuple[str, int, str]:
    if not overwrite_existing and log_exists(conn, stock_id, from_date, to_date):
        return "SKIPPED", 0, "Already refreshed for this date range."

    ticker = exchange_symbol(exchange, symbol)
    stock_name = _resolve_stock_name(ticker, symbol)
    from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").date()

    # Fetch a slightly wider window, then filter locally.
    # This helps around timezone/session boundary issues on provider side.
    api_start = (from_dt - timedelta(days=2)).strftime("%Y-%m-%d")
    api_end = (to_dt + timedelta(days=2)).strftime("%Y-%m-%d")

    df, source_or_error = _fetch_from_yahoo(ticker, api_start, api_end)

    if df.empty:
        msg = (
            f"No data returned for {ticker} in {from_date} to {to_date}. "
            f"Yahoo attempts: {source_or_error}"
        )
        record_log(conn, stock_id, from_date, to_date, "NO_DATA", 0, msg)
        return "WARNING", 0, msg

    df = df.reset_index()
    if "Date" not in df.columns and "Datetime" in df.columns:
        df = df.rename(columns={"Datetime": "Date"})

    if "Date" not in df.columns:
        msg = f"Unexpected response format for {ticker}. Missing Date column."
        record_log(conn, stock_id, from_date, to_date, "ERROR", 0, msg)
        return "WARNING", 0, msg

    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    df = df[(df["Date"] >= from_dt) & (df["Date"] <= to_dt)]

    if df.empty:
        msg = f"No rows after range filter for {ticker}. Source={source_or_error}."
        record_log(conn, stock_id, from_date, to_date, "NO_DATA", 0, msg)
        return "WARNING", 0, msg

    if "Adj Close" not in df.columns:
        df["Adj Close"] = df.get("Close")

    insert_rows: list[tuple[Any, ...]] = []
    for _, row in df.iterrows():
        trade_date = row["Date"]
        insert_rows.append(
            (
                stock_id,
                stock_name,
                exchange,
                symbol,
                trade_date,
                None if pd.isna(row.get("Open")) else float(row.get("Open")),
                None if pd.isna(row.get("High")) else float(row.get("High")),
                None if pd.isna(row.get("Low")) else float(row.get("Low")),
                None if pd.isna(row.get("Close")) else float(row.get("Close")),
                None if pd.isna(row.get("Adj Close")) else float(row.get("Adj Close")),
                None if pd.isna(row.get("Volume")) else int(row.get("Volume")),
            )
        )

    before_count = conn.execute("SELECT COUNT(*) FROM stock_data WHERE stock_id = ?", [stock_id]).fetchone()[0]
    if overwrite_existing:
        conn.executemany(
            """
            INSERT INTO stock_data (
                stock_id,
                stock_name,
                exchange,
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                adj_close,
                volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_id, trade_date) DO UPDATE SET
                stock_name = EXCLUDED.stock_name,
                exchange = EXCLUDED.exchange,
                symbol = EXCLUDED.symbol,
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                adj_close = EXCLUDED.adj_close,
                volume = EXCLUDED.volume,
                created_at = now()
            """,
            insert_rows,
        )
    else:
        conn.executemany(
            """
            INSERT INTO stock_data (
                stock_id,
                stock_name,
                exchange,
                symbol,
                trade_date,
                open,
                high,
                low,
                close,
                adj_close,
                volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_id, trade_date) DO NOTHING
            """,
            insert_rows,
        )
    after_count = conn.execute("SELECT COUNT(*) FROM stock_data WHERE stock_id = ?", [stock_id]).fetchone()[0]

    inserted_rows = after_count - before_count
    if overwrite_existing:
        message = (
            f"Downloaded {len(insert_rows)} rows and overwrote existing rows on date conflicts. "
            f"Net new rows added: {inserted_rows}. Source={source_or_error}."
        )
    else:
        message = (
            f"Downloaded {len(insert_rows)} rows, inserted {inserted_rows} new rows. "
            f"Source={source_or_error}."
        )
    record_log(conn, stock_id, from_date, to_date, "SUCCESS", inserted_rows, message)
    return "SUCCESS", inserted_rows, message
