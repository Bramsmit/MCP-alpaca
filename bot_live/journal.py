"""
Trade journal: schrijft elke gevulde trade naar een JSONL-bestand in de repo-root.

Standaard: trades.jsonl (Alpaca-bot). Bitvavo-bot gebruikt journal_filename='bitvavo_trades.jsonl'
(zelfde formaat), zodat GitHub Actions dat bestand kan cachen.

Gebruik load_trades() om de geschiedenis te lezen.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from bot_live.config import BITVAVO_FEE_BUY_RATE, JOURNAL_FIXED_FEE_PER_FILL_USD

log = logging.getLogger(__name__)


def _journal_path(filename: str = "trades.jsonl") -> Path:
    return Path(__file__).resolve().parent.parent / filename


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
    fee_eur: float | None = None,
    journal_filename: str = "trades.jsonl",
    journal_fixed_fee_per_fill: float | None = None,
) -> None:
    """Schrijf één gevulde trade append naar journal_filename (onder repo-root).

    journal_fixed_fee_per_fill: None = JOURNAL_FIXED_FEE_PER_FILL_USD (Alpaca);
    Bitvavo zet typisch FEE_FIXED_PER_SIDE_EUR.
    """
    profit_pct = None
    if profit is not None and entry_price and entry_price > 0 and qty > 0:
        fixed = (
            JOURNAL_FIXED_FEE_PER_FILL_USD
            if journal_fixed_fee_per_fill is None
            else journal_fixed_fee_per_fill
        )
        cost = entry_price * qty * (1 + BITVAVO_FEE_BUY_RATE) + fixed
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
        "fee_eur": round(fee_eur, 4) if fee_eur is not None else None,
    }

    try:
        path = _journal_path(journal_filename)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
            f.flush()
        log.info(
            "Journal %s: trade gelogd order_id=%s %s %s",
            journal_filename,
            order_id,
            side,
            symbol,
        )
    except Exception as e:
        log.warning("Kon trade niet loggen naar journal: %s", e)


def load_trades(journal_filename: str = "trades.jsonl") -> list[dict]:
    """Laad alle trades uit het gegeven journal-bestand (repo-root).

    Retourneert lege lijst als bestand ontbreekt.
    """
    path = _journal_path(journal_filename)
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
