"""
Trade journal: schrijft elke gevulde trade naar trades.jsonl.
Gebruik load_trades() om de geschiedenis te lezen.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from bot.config import BITVAVO_FEE_BUY_RATE

log = logging.getLogger(__name__)


def _journal_path() -> Path:
    return Path(__file__).resolve().parent.parent / "trades.jsonl"


def log_trade(
    *,
    order_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    entry_price: float | None,
    profit: float | None,
    portfolio_value: float,
) -> None:
    """Schrijf één gevulde trade naar trades.jsonl (append)."""
    profit_pct = None
    if profit is not None and entry_price and entry_price > 0 and qty > 0:
        cost = entry_price * qty * (1 + BITVAVO_FEE_BUY_RATE)
        profit_pct = round(profit / cost * 100, 2)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "order_id": order_id,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "entry_price": entry_price,
        "profit": round(profit, 4) if profit is not None else None,
        "profit_pct": profit_pct,
        "portfolio_value": round(portfolio_value, 2),
    }

    try:
        path = _journal_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        log.warning("Kon trade niet loggen naar journal: %s", e)


def load_trades() -> list[dict]:
    """Laad alle trades uit trades.jsonl.

    Retourneert lege lijst als bestand ontbreekt.
    """
    path = _journal_path()
    if not path.exists():
        return []
    trades = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return trades
