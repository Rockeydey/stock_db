from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Flask, flash, redirect, render_template, request, url_for

from core_config import SECRET_KEY
from db import get_conn, init_db
from stock_data_service import fetch_and_store_stock_data, fetch_and_store_todays_data
from stock_store import (
    add_stock,
    delete_stock,
    execute_read_query,
    fetch_table_rows,
    get_stocks,
    list_main_tables,
    record_log,
)
from stock_utils import is_safe_identifier

app = Flask(__name__)
app.secret_key = SECRET_KEY


def parse_date_range(from_date: str, to_date: str) -> tuple[bool, str | None]:
    try:
        from_dt = datetime.strptime(from_date, "%Y-%m-%d")
        to_dt = datetime.strptime(to_date, "%Y-%m-%d")
    except ValueError:
        return False, "Invalid date format. Use YYYY-MM-DD."

    if from_dt > to_dt:
        return False, "From date must be less than or equal to To date."

    today = datetime.now().date()
    if from_dt.date() > today:
        return False, "From date cannot be in the future."

    return True, None


init_db()


@app.route("/")
def dashboard() -> str:
    stocks = get_stocks()
    from_date = request.args.get("from_date") or datetime.now().strftime("%Y-01-01")
    to_date = request.args.get("to_date") or datetime.now().strftime("%Y-%m-%d")
    overwrite_existing = request.args.get("overwrite_existing") == "1"
    return render_template(
        "dashboard.html",
        stocks=stocks,
        from_date=from_date,
        to_date=to_date,
        overwrite_existing=overwrite_existing,
    )


@app.route("/refresh-data", methods=["POST"])
def refresh_data() -> Any:
    from_date = request.form.get("from_date", "").strip()
    to_date = request.form.get("to_date", "").strip()
    overwrite_existing = request.form.get("overwrite_existing") == "1"

    ok, message = parse_date_range(from_date, to_date)
    if not ok:
        flash(message or "Invalid date range.", "error")
        return redirect(
            url_for(
                "dashboard",
                from_date=from_date,
                to_date=to_date,
                overwrite_existing="1" if overwrite_existing else "0",
            )
        )

    today = datetime.now().date()
    if datetime.strptime(to_date, "%Y-%m-%d").date() > today:
        to_date = today.strftime("%Y-%m-%d")
        flash(f"To date adjusted to {to_date}.", "warning")

    stocks = get_stocks()
    if not stocks:
        flash("No stocks configured. Add stocks in Settings.", "warning")
        return redirect(
            url_for(
                "dashboard",
                from_date=from_date,
                to_date=to_date,
                overwrite_existing="1" if overwrite_existing else "0",
            )
        )

    conn = get_conn()
    try:
        for stock in stocks:
            try:
                status, _inserted, msg = fetch_and_store_stock_data(
                    conn,
                    stock_id=stock["id"],
                    symbol=stock["symbol"],
                    exchange=stock["exchange"],
                    from_date=from_date,
                    to_date=to_date,
                    overwrite_existing=overwrite_existing,
                )
                flash(
                    f"{stock['symbol']} ({stock['exchange']}): {status} - {msg}",
                    "success" if status == "SUCCESS" else "warning",
                )
            except Exception as ex:
                record_log(conn, stock["id"], from_date, to_date, "ERROR", 0, str(ex))
                flash(f"{stock['symbol']} ({stock['exchange']}): ERROR - {ex}", "error")
    finally:
        conn.close()

    return redirect(
        url_for(
            "dashboard",
            from_date=from_date,
            to_date=to_date,
            overwrite_existing="1" if overwrite_existing else "0",
        )
    )


@app.route("/settings", methods=["GET", "POST"])
def settings() -> str:
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add":
            symbol = request.form.get("symbol", "")
            exchange = request.form.get("exchange", "")
            is_ok, msg = add_stock(symbol, exchange)
            flash(msg, "success" if is_ok else "error")

        elif action == "delete":
            raw_stock_id = request.form.get("stock_id", "0")
            try:
                stock_id = int(raw_stock_id)
            except ValueError:
                stock_id = 0
            is_ok, msg = delete_stock(stock_id)
            flash(msg, "success" if is_ok else "error")

        return redirect(url_for("settings"))

    return render_template("settings.html", stocks=get_stocks())


@app.route("/today-refresh", methods=["GET", "POST"])
def today_refresh() -> str:
    stocks = get_stocks()
    results: list[dict[str, Any]] = []
    run_started_at: str | None = None
    total_rows = 0

    if request.method == "POST":
        if not stocks:
            flash("No stocks configured. Add stocks in Settings.", "warning")
        else:
            run_started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn = get_conn()
            try:
                for stock in stocks:
                    status = "ERROR"
                    message = "Unknown error"
                    try:
                        status, message = fetch_and_store_todays_data(
                            conn,
                            stock_id=stock["id"],
                            symbol=stock["symbol"],
                            exchange=stock["exchange"],
                        )
                    except Exception as ex:
                        status = "ERROR"
                        message = str(ex)

                    results.append(
                        {
                            "id": stock["id"],
                            "symbol": stock["symbol"],
                            "exchange": stock["exchange"],
                            "status": status,
                            "message": message,
                        }
                    )

                total_rows = conn.execute("SELECT COUNT(*) FROM todays_data").fetchone()[0]
                success_count = sum(1 for row in results if row["status"] == "SUCCESS")
                warning_count = sum(1 for row in results if row["status"] == "WARNING")
                error_count = sum(1 for row in results if row["status"] == "ERROR")
                flash(
                    (
                        f"Today's refresh completed. Success: {success_count}, "
                        f"Warning: {warning_count}, Error: {error_count}."
                    ),
                    "success" if error_count == 0 else "warning",
                )
            finally:
                conn.close()

    return render_template(
        "today_refresh.html",
        stocks=stocks,
        results=results,
        run_started_at=run_started_at,
        total_rows=total_rows,
    )


@app.route("/tables")
def list_tables() -> Any:
    return redirect(url_for("query_tables"))


@app.route("/tables/query", methods=["GET", "POST"])
def query_tables() -> str:
    default_query = "SELECT * FROM stocks ORDER BY id DESC LIMIT 100"
    query_text = (request.args.get("query") or "").strip() or default_query
    selected_table = (request.args.get("selected_table") or "").strip()
    tables = list_main_tables()
    if selected_table and selected_table not in tables:
        selected_table = ""
    headers: list[str] = []
    records: list[list[Any]] = []

    if request.method == "POST":
        query_text = request.form.get("query", "").strip() or default_query

    headers, records, query_error = execute_read_query(query_text)
    if query_error:
        flash(query_error, "error")

    return render_template(
        "table_view.html",
        table_name=None,
        headers=headers,
        records=records,
        query_text=query_text,
        tables=tables,
        selected_table=selected_table,
    )


@app.route("/tables/<table_name>")
def view_table(table_name: str) -> Any:
    if not is_safe_identifier(table_name):
        flash("Invalid table name.", "error")
        return redirect(url_for("list_tables"))

    headers, records = fetch_table_rows(table_name)
    if not headers and not records:
        flash("Table not found.", "error")
        return redirect(url_for("list_tables"))

    default_query = f"SELECT * FROM {table_name} ORDER BY 1 DESC LIMIT 500"
    return redirect(url_for("query_tables", query=default_query, selected_table=table_name))


if __name__ == "__main__":
    app.run(debug=True)
