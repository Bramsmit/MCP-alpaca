"""
Gedeelde Alpaca crypto-runtime: clients, quotes, posities, open orders,
limit-sell submit, trade-state, fill-notificaties (Telegram + journal).

Gebruikt door:
  - bot_range_1000.live_trader (daily range-bot)
  - bot_hybrid.hybrid_trader (regime / hourly)

Let op: wijzigingen hier raken beide bots. Range-specifieke logica hoort in
live_trader.py (o.a. select_top_symbols, run_once).
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce, QueryOrderStatus, OrderStatus
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest

from bot_live.config import (
    BITVAVO_FEE_BUY_RATE,
    BITVAVO_FEE_SELL_LIMIT_RATE,
)
from bot_live.telegram import notify_trade_filled
from bot_live.journal import log_trade

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def get_trading_clients():
    """Maak Alpaca clients. Paper mode via ALPACA_PAPER_TRADE env var (default True)."""
    api_key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret:
        raise ValueError("ALPACA_API_KEY en ALPACA_SECRET_KEY vereist in .env")
    paper = os.environ.get("ALPACA_PAPER_TRADE", "True").strip().lower() not in ("false", "0", "no")
    if not paper:
        log.warning("⚠️  LIVE TRADING — ALPACA_PAPER_TRADE=False")
    return (
        TradingClient(api_key, secret, paper=paper),
        CryptoHistoricalDataClient(api_key, secret),
    )


def get_current_prices(data_client, symbols: list[str]) -> dict[str, float]:
    """Huidige prijs per symbol (mid van latest quote)."""
    try:
        request = CryptoLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = data_client.get_crypto_latest_quote(request)
        result = {}
        for symbol in symbols:
            q = quotes.get(symbol)
            if q:
                ap = float(q.ask_price or 0)
                bp = float(q.bid_price or 0)
                if ap and bp:
                    result[symbol] = (ap + bp) / 2
                elif ap:
                    result[symbol] = ap
                elif bp:
                    result[symbol] = bp
        return result
    except Exception as e:
        log.warning("get_current_prices fout: %s", e)
        return {}


def _round_price(price: float) -> float:
    """Round price to pass Alpaca validation. Explicit float() voor numpy types."""
    p = float(price)
    if p < 0.0001:
        return round(p, 8)
    if p < 1:
        return round(p, 6)
    return round(p, 4)


def _norm_symbol(s: str) -> str:
    """Normaliseer symbol naar DOT/USD formaat."""
    if "/" in s:
        return s
    if s.endswith("USD"):
        return f"{s[:-3]}/USD"
    return f"{s}/USD"


def _position_qty_float(p) -> float:
    """Qty als float; Alpaca geeft soms string (exacte precisie)."""
    q = p.qty
    if isinstance(q, str):
        return float(Decimal(q))
    return float(q or 0)


def get_positions(trading_client, symbols: list[str] | None = None) -> dict[str, tuple[float, float]]:
    """Posities per symbol: {symbol: (qty, avg_entry_price)}. Filter op symbols indien gegeven."""
    positions = trading_client.get_all_positions()
    out = {}
    for p in positions:
        sym = _norm_symbol(p.symbol)
        if symbols is None or sym in symbols:
            out[sym] = (_position_qty_float(p), float(p.avg_entry_price or 0))
    return out


# Onder deze hoeveelheid crypto: geen sell (dust / afronding-ruis)
MIN_SELLABLE_CRYPTO_QTY = Decimal("0.0001")


def _find_position(trading_client, symbol: str):
    """Alpaca Position voor dit symbol, of None."""
    for p in trading_client.get_all_positions():
        if _norm_symbol(p.symbol) == symbol:
            return p
    return None


def _decimal_from_json_qty(raw) -> Decimal | None:
    """Parse qty uit Alpaca JSON (meestal string, exact). Geen round() op floats."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            return Decimal(raw)
        except Exception:
            return None
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        return Decimal(repr(raw))
    try:
        return Decimal(str(raw))
    except Exception:
        return None


def _sell_qty_decimal_from_position(p) -> Decimal:
    """
    Hoeveelheid die we mogen verkopen volgens Alpaca.

    Primair: qty_available (niet gelocked in open orders).
    Fallback: qty als qty_available ontbreekt.
    """
    if p is None:
        return Decimal(0)
    data = p.model_dump(mode="json")

    raw_avail = data.get("qty_available")
    if raw_avail is not None and raw_avail != "":
        d_avail = _decimal_from_json_qty(raw_avail)
        if d_avail is not None:
            if d_avail > 0:
                return d_avail
            return Decimal(0)

    raw_qty = data.get("qty")
    d_qty = _decimal_from_json_qty(raw_qty)
    return d_qty if d_qty is not None and d_qty > 0 else Decimal(0)


def _decimal_to_submit_sell_qty(d: Decimal) -> float:
    """Decimal -> float voor LimitOrderRequest."""
    if d <= 0:
        return 0.0
    return float(d)


def _submit_crypto_sell(trading_client, symbol: str, position, limit_sell: float) -> None:
    """Plaats één limit sell; qty = Alpaca qty_available (of qty fallback)."""
    d = _sell_qty_decimal_from_position(position)
    qty_sell = _decimal_to_submit_sell_qty(d)
    if qty_sell <= 0:
        raise ValueError(f"qty must be > 0 (decimal={d!r})")
    trading_client.submit_order(
        LimitOrderRequest(
            symbol=symbol,
            qty=qty_sell,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.GTC,
            limit_price=_round_price(limit_sell),
        )
    )


def get_open_orders(trading_client, symbol: str = None) -> list:
    """Open orders, optioneel gefilterd op symbol."""
    result = trading_client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    orders = result if isinstance(result, list) else result.get("orders", [])
    if symbol:
        return [o for o in orders if _norm_symbol(o.symbol) == symbol]
    return list(orders)


def get_buying_power(trading_client) -> float:
    """Beschikbaar cash."""
    acc = trading_client.get_account()
    return float(acc.cash)


def get_portfolio_value(trading_client) -> float:
    """Totaal portfolio waarde (equity)."""
    acc = trading_client.get_account()
    return float(getattr(acc, "equity", 0) or getattr(acc, "portfolio_value", 0) or 0)


def _state_path() -> Path:
    return _REPO_ROOT / ".alpaca_trade_state.json"


def _load_state() -> dict:
    """Laad state uit file."""
    path = _state_path()
    if not path.exists():
        return {"entries": {}, "notified_order_ids": []}
    try:
        data = json.loads(path.read_text())
        return {
            "entries": data.get("entries", {}),
            "notified_order_ids": data.get("notified_order_ids", []),
        }
    except Exception:
        return {"entries": {}, "notified_order_ids": []}


def _save_state(entries: dict | None = None, notified_ids: list[str] | None = None) -> None:
    """Bewaar state. entries/notified_ids = None betekent: niet overschrijven."""
    path = _state_path()
    state = _load_state()
    if entries is not None:
        state["entries"] = entries
    if notified_ids is not None:
        state["notified_order_ids"] = notified_ids[-200:]
    try:
        path.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.warning("Kon state niet opslaan: %s", e)


def _check_and_notify_filled_orders(trading_client, symbols: list[str]) -> int:
    """Gevulde orders → Telegram + journal. Retourneert aantal nieuwe trades."""
    try:
        after = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after)
        orders = trading_client.get_orders(req)
        portfolio_value = get_portfolio_value(trading_client)
        state = _load_state()
        entries = dict(state["entries"])
        notified_ids = list(state.get("notified_order_ids", []))
        new_notified = []

        for o in orders or []:
            if getattr(o, "status", None) != OrderStatus.FILLED:
                continue
            oid = str(getattr(o, "id", ""))
            if oid in notified_ids:
                continue
            sym = _norm_symbol(o.symbol)
            if sym not in symbols:
                continue
            qty = float(o.filled_qty or 0)
            price = float(o.filled_avg_price or 0)
            if not qty or not price:
                continue
            side = "buy" if o.side == OrderSide.BUY else "sell"
            profit = None
            entry_price_for_log = None
            if side == "sell" and sym in entries:
                entry = entries[sym].get("entry", 0)
                entry_price_for_log = entry if entry else None
                if entry:
                    cost_incl = entry * qty * (1 + BITVAVO_FEE_BUY_RATE)
                    proceeds = price * qty * (1 - BITVAVO_FEE_SELL_LIMIT_RATE)
                    profit = proceeds - cost_incl
                del entries[sym]
            notify_trade_filled(
                side, sym, qty, price, profit, portfolio_value, entry_price=entry_price_for_log
            )
            log_trade(
                order_id=oid,
                symbol=sym,
                side=side,
                qty=qty,
                price=price,
                entry_price=entry_price_for_log,
                profit=profit,
                portfolio_value=portfolio_value,
            )
            new_notified.append(oid)

        if new_notified:
            _save_state(notified_ids=notified_ids + new_notified)
        return len(new_notified)
    except Exception as e:
        log.warning("check filled orders: %s", e)
        return 0
