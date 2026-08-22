"""Load Kraken fills (API export or bot JSONL) into the common schema."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .schema import Fill, in_range, make_fill, parse_ts


def _from_api_row(raw: dict) -> Fill | None:
    tid = str(raw.get("trade_id") or "").strip()
    side = str(raw.get("side") or "").lower()
    qty = float(raw.get("qty") or raw.get("filled_qty") or 0)
    price = float(raw.get("price") or raw.get("filled_avg_price_usd") or 0)
    if not tid or side not in ("buy", "sell") or qty <= 0 or price <= 0:
        return None
    ts_raw = raw.get("timestamp") or raw.get("exchange_trade_timestamp")
    fee = raw.get("fee_usd")
    if fee is None:
        fee = raw.get("exchange_fee_usd")
    pv = raw.get("portfolio_usd")
    if pv is None:
        pv = raw.get("portfolio_value_usd")
    entry = raw.get("entry_price")
    if entry is None:
        entry = raw.get("entry_price_usd_for_pnl")
    profit = raw.get("profit_usd")
    if profit is None:
        profit = raw.get("estimated_roundtrip_profit_usd")
    return make_fill(
        venue="kraken",
        timestamp=str(ts_raw) if ts_raw else None,
        symbol=str(raw.get("symbol") or ""),
        side=side,
        qty=qty,
        price=price,
        trade_id=tid,
        fee_usd=float(fee) if fee is not None else None,
        portfolio_usd=float(pv) if pv is not None else None,
        entry_price=float(entry) if entry not in (None, "") else None,
        profit_usd=float(profit) if profit not in (None, "") else None,
    )


def _from_journal_row(raw: dict) -> Fill | None:
    """bot_live / rangebot log_trade shape (kraken_trades.jsonl)."""
    tid = str(raw.get("order_id") or raw.get("trade_id") or "").strip()
    side = str(raw.get("side") or "").lower()
    qty = float(raw.get("qty") or 0)
    price = float(raw.get("price") or 0)
    if not tid or side not in ("buy", "sell") or qty <= 0 or price <= 0:
        return None
    ts_raw = raw.get("timestamp")
    fee = raw.get("fee_eur")  # misnamed; may hold USD fee in kraken journal
    if fee is None:
        fee = raw.get("fee_usd")
    pv = raw.get("portfolio_value") or raw.get("portfolio_value_usd")
    return make_fill(
        venue="kraken",
        timestamp=str(ts_raw) if ts_raw else None,
        symbol=str(raw.get("symbol") or ""),
        side=side,
        qty=qty,
        price=price,
        trade_id=tid,
        fee_usd=float(fee) if fee is not None else None,
        portfolio_usd=float(pv) if pv is not None else None,
        entry_price=float(raw["entry_price"])
        if raw.get("entry_price") not in (None, "")
        else None,
        profit_usd=float(raw["profit"])
        if raw.get("profit") not in (None, "")
        else (
            float(raw["profit_usd"])
            if raw.get("profit_usd") not in (None, "")
            else None
        ),
    )


def load_kraken_jsonl(
    path: Path,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Fill]:
    if not path.exists():
        return []
    seen: set[str] = set()
    out: list[Fill] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            fill = _from_api_row(raw) or _from_journal_row(raw)
            if fill is None:
                continue
            if fill["trade_id"] in seen:
                continue
            seen.add(fill["trade_id"])
            ts = parse_ts(fill.get("timestamp"))
            if not in_range(ts, start, end):
                continue
            out.append(fill)
    out.sort(key=lambda r: r.get("timestamp") or "")
    return out
