"""
Gedeelde Alpaca crypto-runtime: clients, quotes, posities, open orders,
limit-sell submit, trade-state, fill-notificaties (Telegram + journal).

Gebruikt door:
  - alpaca_bot.live_trader (daily range-bot; shim: bot_range_1000.live_trader)
  - bot_hybrid.hybrid_trader (regime / hourly)

Let op: wijzigingen hier raken hybrid en Alpaca range. Range-specifieke loop hoort in
alpaca_bot/live_trader.py (o.a. select_top_symbols, run_once).
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
    ALPACA_FILLED_ORDERS_LOOKBACK_HOURS,
    BITVAVO_FEE_BUY_RATE,
    BITVAVO_FEE_SELL_LIMIT_RATE,
    JOURNAL_FIXED_FEE_PER_FILL_USD,
    SYMBOL_POOL,
    TELEGRAM_NOTIFY_BUY_FILLS,
)
from bot_live.telegram import notify_trade_filled
from bot_live.journal import known_order_ids, log_trade

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _alpaca_bot_trade_log_path() -> Path | None:
    """
    Append-only JSON-lines audit van gevulde Alpaca-orders (USD-quote).

    ALPACA_BOT_TRADE_LOG:
      - niet gezet → repo-root alpaca_bot_trades.jsonl
      - leeg / false / 0 / off → uit
      - anders → pad (relatief t.o.v. repo-root als niet absoluut)
    """
    raw = os.environ.get("ALPACA_BOT_TRADE_LOG")
    if raw is None:
        return _REPO_ROOT / "alpaca_bot_trades.jsonl"
    s = raw.strip()
    if s.lower() in ("", "0", "false", "no", "off"):
        return None
    p = Path(s).expanduser()
    return p if p.is_absolute() else _REPO_ROOT / p


def _order_audit_snapshot(o) -> dict:
    """Compacte Alpaca-order velden voor lokaal nakijken (geen secrets)."""
    keys = (
        "id",
        "client_order_id",
        "symbol",
        "side",
        "type",
        "status",
        "qty",
        "filled_qty",
        "filled_avg_price",
        "limit_price",
        "created_at",
        "updated_at",
        "filled_at",
        "submitted_at",
        "time_in_force",
    )
    try:
        data = o.model_dump(mode="json")
        return {k: data.get(k) for k in keys if k in data or hasattr(o, k)}
    except Exception:
        out = {}
        for k in keys:
            if hasattr(o, k):
                v = getattr(o, k)
                out[k] = v.isoformat() if hasattr(v, "isoformat") else v
        return out


def append_alpaca_bot_fill_audit(record: dict) -> None:
    """Schrijf één JSON-object als regel naar het Alpaca-bot auditbestand."""
    path = _alpaca_bot_trade_log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
            f.flush()
    except Exception as e:
        log.warning("alpaca_bot_trade_log: %s", e)


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


def get_position_market_value_usd(
    trading_client, symbols: list[str] | None = None
) -> float:
    """
    Marktwaarde van open crypto-posities (USD).

    Gebruik dit voor deploy-cap sizing — niet ``equity - cash``: op Alpaca telt
    gereserveerde cash in open buy-limits mee in equity−cash, terwijl er geen
    positie is.
    """
    total = 0.0
    for p in trading_client.get_all_positions():
        sym = _norm_symbol(p.symbol)
        if symbols is not None and sym not in symbols:
            continue
        mv = getattr(p, "market_value", None)
        if mv is not None and mv != "":
            total += abs(float(mv))
            continue
        qty = _position_qty_float(p)
        if qty <= 0:
            continue
        px = float(getattr(p, "current_price", None) or p.avg_entry_price or 0)
        total += qty * px
    return total


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


def get_cumulative_fictive_fees_usd() -> float:
    """Som geschatte fictieve fees (Alpaca journal-model), uit .alpaca_trade_state.json."""
    return float(_load_state().get("cumulative_fictive_fees_usd", 0) or 0)


def _parse_order_ts(val) -> datetime:
    if val is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(val, datetime):
        dt = val
    else:
        try:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _order_fill_sort_ts(o) -> datetime:
    for attr in ("filled_at", "updated_at", "submitted_at", "created_at"):
        ts = getattr(o, attr, None)
        if ts:
            return _parse_order_ts(ts)
    return datetime.min.replace(tzinfo=timezone.utc)


def _load_state() -> dict:
    """Laad state uit file."""
    path = _state_path()
    base = {
        "entries": {},
        "notified_order_ids": [],
        "cumulative_fictive_fees_usd": 0.0,
    }
    if not path.exists():
        return base.copy()
    try:
        data = json.loads(path.read_text())
        out = base.copy()
        out["entries"] = data.get("entries", {})
        out["notified_order_ids"] = data.get("notified_order_ids", [])
        out["cumulative_fictive_fees_usd"] = float(
            data.get("cumulative_fictive_fees_usd", 0) or 0
        )
        return out
    except Exception:
        return base.copy()


def _save_state(
    entries: dict | None = None,
    notified_ids: list[str] | None = None,
    cumulative_fictive_fees_usd: float | None = None,
) -> None:
    """Bewaar state. None = veld niet wijzigen."""
    path = _state_path()
    state = _load_state()
    if entries is not None:
        state["entries"] = entries
    if notified_ids is not None:
        state["notified_order_ids"] = notified_ids[-1000:]
    if cumulative_fictive_fees_usd is not None:
        state["cumulative_fictive_fees_usd"] = float(cumulative_fictive_fees_usd)
    try:
        path.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.warning("Kon state niet opslaan: %s", e)


def _known_notified_order_ids() -> set[str]:
    """State + trades.jsonl + data/alpaca_trades.jsonl (persistente repo-log).

    Drie lagen zodat dedup ook werkt na cache-miss of bij eerste run na herinstallatie.
    """
    state = _load_state()
    ids = {str(x) for x in state.get("notified_order_ids", []) if x}
    ids.update(known_order_ids("trades.jsonl"))
    # Persistente log in repo (bijgewerkt door export_trade_log stap in CI)
    persistent = _REPO_ROOT / "data" / "alpaca_trades.jsonl"
    if persistent.exists():
        try:
            with persistent.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = __import__("json").loads(line)
                        oid = str(rec.get("order_id") or "")
                        if oid:
                            ids.add(oid)
        except Exception:
            pass
    return ids


def _apply_buy_to_entries(entries: dict, sym: str, qty: float, price: float) -> None:
    prev = entries.get(sym)
    if prev and float(prev.get("qty") or 0) > 0:
        pq = float(prev["qty"])
        pe = float(prev.get("entry") or 0)
        new_qty = pq + qty
        new_entry = (pe * pq + price * qty) / new_qty if new_qty > 0 else price
        entries[sym] = {"qty": new_qty, "entry": new_entry}
    else:
        entries[sym] = {"qty": qty, "entry": price}


def _check_and_notify_filled_orders(trading_client, symbols: list[str]) -> int:
    """Gevulde orders (laatste ALPACA_FILLED_ORDERS_LOOKBACK_HOURS u) → Telegram + journal."""
    try:
        after = (
            datetime.now(timezone.utc)
            - timedelta(hours=ALPACA_FILLED_ORDERS_LOOKBACK_HOURS)
        ).isoformat()
        req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after)
        orders = trading_client.get_orders(req)
        orders = sorted(orders or [], key=_order_fill_sort_ts)
        portfolio_value = get_portfolio_value(trading_client)
        state = _load_state()
        entries = dict(state["entries"])
        # Open posities in pool: verse avg entry (ook als sym even uit top-N is)
        for sym, (qty, ep) in get_positions(trading_client, SYMBOL_POOL).items():
            if qty > 0 and ep > 0:
                entries[sym] = {"qty": float(qty), "entry": float(ep)}
        known_notified = _known_notified_order_ids()
        cum_fees = float(state.get("cumulative_fictive_fees_usd", 0) or 0)
        new_notified: list[str] = []
        entries_dirty = False

        for o in orders:
            if getattr(o, "status", None) != OrderStatus.FILLED:
                continue
            oid = str(getattr(o, "id", ""))
            if not oid or oid in known_notified:
                continue
            sym = _norm_symbol(o.symbol)
            if sym not in symbols:
                continue
            qty = float(o.filled_qty or 0)
            price = float(o.filled_avg_price or 0)
            if not qty or not price:
                continue
            side = "buy" if o.side == OrderSide.BUY else "sell"
            if side == "buy":
                cum_fees += qty * price * BITVAVO_FEE_BUY_RATE + JOURNAL_FIXED_FEE_PER_FILL_USD
            else:
                cum_fees += qty * price * BITVAVO_FEE_SELL_LIMIT_RATE + JOURNAL_FIXED_FEE_PER_FILL_USD

            profit = None
            entry_price_for_log = None
            if side == "buy":
                _apply_buy_to_entries(entries, sym, qty, price)
                entries_dirty = True
            elif sym in entries:
                entry = entries[sym].get("entry", 0)
                entry_price_for_log = entry if entry else None
                if entry:
                    cost_incl = (
                        entry * qty * (1 + BITVAVO_FEE_BUY_RATE)
                        + JOURNAL_FIXED_FEE_PER_FILL_USD
                    )
                    proceeds = (
                        price * qty * (1 - BITVAVO_FEE_SELL_LIMIT_RATE)
                        - JOURNAL_FIXED_FEE_PER_FILL_USD
                    )
                    profit = proceeds - cost_incl
                prev_qty = float(entries[sym].get("qty") or 0)
                remain_q = prev_qty - qty
                if remain_q <= 1e-12:
                    del entries[sym]
                else:
                    entries[sym] = {
                        "qty": remain_q,
                        "entry": entries[sym].get("entry"),
                    }
                entries_dirty = True

            send_tg = (side == "buy" and TELEGRAM_NOTIFY_BUY_FILLS) or (
                side == "sell" and entry_price_for_log and entry_price_for_log > 0
            )
            known_notified.add(oid)
            new_notified.append(oid)
            filled_ts_iso = None
            for attr in ("filled_at", "updated_at", "submitted_at"):
                ts = getattr(o, attr, None)
                if ts:
                    filled_ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                    break
            base_asset = sym.split("/")[0] if "/" in sym else sym
            append_alpaca_bot_fill_audit(
                {
                    "logged_at": datetime.now(timezone.utc).isoformat(),
                    "alpaca_fill_timestamp": filled_ts_iso,
                    "order_id": oid,
                    "symbol": sym,
                    "base_asset": base_asset,
                    "quote_currency": "USD",
                    "side": side,
                    "filled_qty": qty,
                    "filled_avg_price_usd": price,
                    "notional_usd": round(qty * price, 10),
                    "portfolio_value_usd": round(portfolio_value, 2),
                    "entry_price_usd_for_pnl": entry_price_for_log,
                    "estimated_roundtrip_profit_usd": round(profit, 8)
                    if profit is not None
                    else None,
                    "note_eur_comparison": (
                        "Alpaca crypto is USD-geciteerd; PnL in journal gebruikt fictieve "
                        "Bitvavo maker-fees ter vergelijking met EUR-spot."
                    ),
                    "order_snapshot": _order_audit_snapshot(o),
                }
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
            notify_trade_filled(
                side,
                sym,
                qty,
                price,
                profit,
                portfolio_value,
                entry_price=entry_price_for_log,
                send_telegram_message=send_tg,
            )

        if new_notified or entries_dirty:
            _save_state(
                entries=entries if entries_dirty else None,
                notified_ids=sorted(known_notified)[-1000:],
                cumulative_fictive_fees_usd=cum_fees if new_notified else None,
            )
        return len(new_notified)
    except Exception as e:
        log.warning("check filled orders: %s", e)
        return 0
