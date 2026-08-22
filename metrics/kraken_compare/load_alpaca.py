"""Load Alpaca paper fills into the common schema."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .schema import Fill, in_range, make_fill, parse_ts


def load_alpaca_jsonl(
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
            tid = str(raw.get("order_id") or "").strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            ts = parse_ts(raw.get("timestamp"))
            if not in_range(ts, start, end):
                continue
            side = str(raw.get("side") or "").lower()
            if side not in ("buy", "sell"):
                continue
            qty = float(raw.get("qty") or 0)
            price = float(raw.get("price") or 0)
            if qty <= 0 or price <= 0:
                continue
            pv = raw.get("portfolio_value")
            if pv is None:
                pv = raw.get("portfolio_value_usd")
            profit = raw.get("profit")
            if profit is None:
                profit = raw.get("profit_usd")
            entry = raw.get("entry_price")
            out.append(
                make_fill(
                    venue="alpaca",
                    timestamp=ts.isoformat() if ts else raw.get("timestamp"),
                    symbol=str(raw.get("symbol") or ""),
                    side=side,
                    qty=qty,
                    price=price,
                    trade_id=tid,
                    fee_usd=0.0,  # paper: no exchange fee charged
                    portfolio_usd=float(pv) if pv is not None else None,
                    entry_price=float(entry) if entry not in (None, "") else None,
                    profit_usd=float(profit) if profit not in (None, "") else None,
                )
            )
    out.sort(key=lambda r: r.get("timestamp") or "")
    return out
