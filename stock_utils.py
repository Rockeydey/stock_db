from __future__ import annotations

import re


def normalize_symbol(symbol: str) -> str:
    return re.sub(r"\.(NS|BO)$", "", symbol.strip().upper())


def sanitize_table_name(exchange: str, symbol: str) -> str:
    raw_name = f"{exchange}_{symbol}".lower()
    cleaned = re.sub(r"[^a-z0-9_]", "_", raw_name)
    return f"stock_{cleaned}"


def exchange_symbol(exchange: str, symbol: str) -> str:
    exch = exchange.strip().upper()
    base_symbol = normalize_symbol(symbol)
    if exch == "NSE":
        return f"{base_symbol}.NS"
    if exch == "BSE":
        return f"{base_symbol}.BO"
    return base_symbol


def is_safe_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""))
