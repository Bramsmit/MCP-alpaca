"""Common fill schema for Alpaca ↔ Kraken comparison."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


Fill = dict[str, Any]


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def in_range(
    ts: datetime | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    if ts is None:
        return False
    if start is not None and ts < start:
        return False
    if end is not None and ts > end:
        return False
    return True


def norm_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace("-", "/")
    if "/" in s:
        base, quote = s.split("/", 1)
        return f"{base}/{quote}"
    if s.endswith("USD"):
        return f"{s[:-3]}/USD"
    return s


def make_fill(
    *,
    venue: str,
    timestamp: str | None,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    trade_id: str,
    fee_usd: float | None = None,
    portfolio_usd: float | None = None,
    entry_price: float | None = None,
    profit_usd: float | None = None,
) -> Fill:
    side_l = side.lower().strip()
    return {
        "venue": venue,
        "timestamp": timestamp,
        "symbol": norm_symbol(symbol),
        "side": side_l,
        "qty": float(qty),
        "price": float(price),
        "fee_usd": None if fee_usd is None else float(fee_usd),
        "portfolio_usd": None if portfolio_usd is None else float(portfolio_usd),
        "trade_id": str(trade_id),
        "entry_price": None if entry_price is None else float(entry_price),
        "profit_usd": None if profit_usd is None else float(profit_usd),
        "notional_usd": round(float(qty) * float(price), 8),
    }
