from __future__ import annotations

import re


def normalize_symbol(symbol: str) -> str:
    return re.sub(r"\.(NS|BO)$", "", symbol.strip().upper())


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
