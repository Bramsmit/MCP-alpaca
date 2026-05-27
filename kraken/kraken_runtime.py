"""
Kraken spot USD — ccxt-runtime: balances, candles, limits, fills → journal/Telegram.

Gescheiden van Alpaca: eigen state `.kraken_trade_state.json` en journal `kraken_trades.jsonl`.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

import ccxt

from bot_live.config import (
    ALPACA_FILLED_ORDERS_LOOKBACK_HOURS,
    BITVAVO_FEE_BUY_RATE,
    BITVAVO_FEE_SELL_LIMIT_RATE,
    JOURNAL_FIXED_FEE_PER_FILL_USD,
    TELEGRAM_NOTIFY_BUY_FILLS,
)
from bot_live.journal import known_order_ids, log_trade
from bot_live.telegram import notify_trade_filled

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _state_path() -> Path:
    return _REPO_ROOT / ".kraken_trade_state.json"


def _norm_symbol(s: str) -> str:
    if "/" in s:
        return s
    if s.endswith("USD"):
        return f"{s[:-3]}/USD"
    return f"{s}/USD"


def _round_price(price: float) -> float:
    p = float(price)
    if p < 0.0001:
        return round(p, 8)
    if p < 1:
        return round(p, 6)
    return round(p, 4)


def make_exchange() -> ccxt.kraken:
    api_key = os.environ.get("KRAKEN_API_KEY", "").strip()
    secret = os.environ.get("KRAKEN_SECRET_KEY", "").strip()
    if not api_key or not secret:
        raise ValueError("KRAKEN_API_KEY en KRAKEN_SECRET_KEY vereist in .env")
    ex = ccxt.kraken(
        {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        }
    )
    ex.load_markets()
    return ex


def filter_kraken_usd_pool(exchange: ccxt.kraken, pool: list[str]) -> list[str]:
    """Behoud alleen symbolen die op Kraken als spot USD unified market bestaan."""
    out: list[str] = []
    for sym in pool:
        u = _norm_symbol(sym)
        if u.endswith("/USD") and u in exchange.markets:
            m = exchange.markets[u]
            if m.get("active", True):
                out.append(u)
        else:
            log.warning("Kraken: market ontbreekt of inactief, skip %s", u)
    return out


def fetch_daily_rows_ccxt(
    exchange: ccxt.kraken, symbol: str, *, limit: int = 15
) -> list[dict[str, float]]:
    """1D OHLCV → rijen voor strategy_core."""
    raw = exchange.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
    rows: list[dict[str, float]] = []
    for o in raw:
        _ts, ope, hi, lo, clo, _vol = o
        rows.append(
            {
                "open": float(ope),
                "high": float(hi),
                "low": float(lo),
                "close": float(clo),
            }
        )
    return rows


def fetch_symbol_rows_for_pool(
    exchange: ccxt.kraken, pool: list[str]
) -> dict[str, list[dict[str, float]]]:
    out: dict[str, list[dict[str, float]]] = {}
    for sym in pool:
        try:
            out[sym] = fetch_daily_rows_ccxt(exchange, sym)
        except Exception as e:
            log.warning("Kraken OHLCV %s: %s", sym, e)
    return out


def _balance_entry(
    balance: dict[str, Any], code: str
) -> tuple[float, float]:
    """(free, total) voor unified currency code."""
    b = balance.get(code) or {}
    if isinstance(b, dict):
        return float(b.get("free") or 0), float(b.get("total") or 0)
    return 0.0, float(b or 0)


def get_buying_power_usd(exchange: ccxt.kraken) -> float:
    bal = exchange.fetch_balance()
    free, _total = _balance_entry(bal, "USD")
    if free <= 0:
        free_z, _ = _balance_entry(bal, "ZUSD")
        free = free_z
    return free


def estimate_portfolio_usd(
    exchange: ccxt.kraken, reference_symbols: list[str]
) -> float:
    """Ruwe schatting: vrije USD + som vrije base * last voor watchlist."""
    bal = exchange.fetch_balance()
    usd_free, _ = _balance_entry(bal, "USD")
    if usd_free <= 0:
        usd_free, _ = _balance_entry(bal, "ZUSD")
    total = usd_free
    for sym in reference_symbols:
        base = sym.split("/")[0]
        qf, _ = _balance_entry(bal, base)
        if qf and qf > 0:
            try:
                t = exchange.fetch_ticker(sym)
                total += float(qf) * float(t.get("last") or t.get("close") or 0)
            except Exception as e:
                log.warning("ticker %s: %s", sym, e)
    return total


def get_qty_for_symbol(exchange: ccxt.kraken, symbol: str) -> tuple[float, float]:
    """(free_base, total_base) voor BASE/USD."""
    base = symbol.split("/")[0]
    bal = exchange.fetch_balance()
    return _balance_entry(bal, base)


def get_positions_map(
    exchange: ccxt.kraken, symbols: list[str], entries_state: dict[str, Any]
) -> dict[str, tuple[float, float]]:
    """
    Zoals Alpaca posities: {symbol: (qty_vrij, avg_entry)}.
    avg_entry uit state entries; qty = free voor order logic.
    """
    out: dict[str, tuple[float, float]] = {}
    for sym in symbols:
        free_q, _tot = get_qty_for_symbol(exchange, sym)
        ent = entries_state.get(sym) or {}
        ep = float(ent.get("entry") or 0)
        out[sym] = (free_q, ep)
    return out


def fetch_open_orders(exchange: ccxt.kraken, symbol: str) -> list[dict[str, Any]]:
    try:
        return exchange.fetch_open_orders(symbol) or []
    except Exception as e:
        log.warning("fetch_open_orders %s: %s", symbol, e)
        return []


def cancel_order_safe(exchange: ccxt.kraken, order_id: str, symbol: str) -> None:
    exchange.cancel_order(order_id, symbol)


def _post_only_params() -> dict[str, Any]:
    po = os.environ.get("KRAKEN_POST_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return {"postOnly": True} if po else {}


def submit_limit_buy(
    exchange: ccxt.kraken,
    symbol: str,
    qty: float,
    price: float,
    *,
    dry_run: bool,
) -> dict[str, Any] | None:
    px = float(exchange.price_to_precision(symbol, price))
    amt = float(exchange.amount_to_precision(symbol, qty))
    if dry_run:
        log.info("DRY_RUN Kraken BUY %s amt=%s @ %s", symbol, amt, px)
        return None
    params = _post_only_params()
    return exchange.create_limit_buy_order(symbol, amt, px, params=params)


def submit_limit_sell_all_free(
    exchange: ccxt.kraken,
    symbol: str,
    price: float,
    *,
    dry_run: bool,
) -> dict[str, Any] | None:
    free_q, _ = get_qty_for_symbol(exchange, symbol)
    if free_q <= 0:
        raise ValueError(f"Geen vrije qty voor sell {symbol}")
    px = float(exchange.price_to_precision(symbol, price))
    amt = float(exchange.amount_to_precision(symbol, free_q))
    if amt <= 0:
        raise ValueError(f"Sell amt na precision is 0 voor {symbol}")
    if dry_run:
        log.info("DRY_RUN Kraken SELL %s amt=%s @ %s", symbol, amt, px)
        return None
    params = _post_only_params()
    return exchange.create_limit_sell_order(symbol, amt, px, params=params)


def order_age_hours(order: dict[str, Any]) -> float:
    ts = order.get("timestamp")
    if not ts:
        return 0.0
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


def get_mid_price(exchange: ccxt.kraken, symbol: str) -> float | None:
    try:
        t = exchange.fetch_ticker(symbol)
        bid = float(t.get("bid") or 0)
        ask = float(t.get("ask") or 0)
        last = float(t.get("last") or t.get("close") or 0)
        if bid and ask:
            return (bid + ask) / 2
        return last or None
    except Exception:
        return None


def _load_state() -> dict[str, Any]:
    base = {"entries": {}, "notified_trade_ids": [], "cumulative_fictive_fees_usd": 0.0}
    path = _state_path()
    if not path.exists():
        return base.copy()
    try:
        data = json.loads(path.read_text())
        out = base.copy()
        out["entries"] = data.get("entries", {})
        out["notified_trade_ids"] = data.get("notified_trade_ids", [])
        out["cumulative_fictive_fees_usd"] = float(
            data.get("cumulative_fictive_fees_usd", 0) or 0
        )
        return out
    except Exception:
        return base.copy()


def save_kraken_state(
    *,
    entries: dict[str, Any] | None = None,
    notified_trade_ids: list[str] | None = None,
    cumulative_fictive_fees_usd: float | None = None,
) -> None:
    path = _state_path()
    state = _load_state()
    if entries is not None:
        state["entries"] = entries
    if notified_trade_ids is not None:
        state["notified_trade_ids"] = notified_trade_ids[-500:]
    if cumulative_fictive_fees_usd is not None:
        state["cumulative_fictive_fees_usd"] = float(cumulative_fictive_fees_usd)
    try:
        path.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.warning("Kraken state schrijven mislukt: %s", e)


def _kraken_trade_log_path() -> Path | None:
    raw = os.environ.get("KRAKEN_BOT_TRADE_LOG")
    if raw is None:
        return _REPO_ROOT / "kraken_bot_trades.jsonl"
    s = raw.strip()
    if s.lower() in ("", "0", "false", "no", "off"):
        return None
    p = Path(s).expanduser()
    return p if p.is_absolute() else _REPO_ROOT / p


def append_kraken_fill_audit(record: dict[str, Any]) -> None:
    path = _kraken_trade_log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        log.warning("kraken_bot_trade_log: %s", e)


def check_and_notify_kraken_fills(
    exchange: ccxt.kraken,
    symbols_pool: list[str],
    *,
    portfolio_usd: float,
) -> tuple[int, dict[str, Any]]:
    """
    Poll recent trades; journal + Telegram; werk entries bij voor PnL-model (Bitvavo-fees fictief).

    Retourneert (aantal_nieuwe_trades, entries_dict_geüpdatet).
    """
    try:
        since_ms = int(
            (
                datetime.now(timezone.utc)
                - timedelta(hours=ALPACA_FILLED_ORDERS_LOOKBACK_HOURS)
            ).timestamp()
            * 1000
        )
        pool_set = {_norm_symbol(s) for s in symbols_pool}
        trades_raw: list[dict[str, Any]] = []
        for sym in pool_set:
            try:
                batch = exchange.fetch_my_trades(sym, since=since_ms, limit=80)
                trades_raw.extend(batch or [])
            except Exception as e:
                log.warning("fetch_my_trades %s: %s", sym, e)

        dedup: dict[str, dict[str, Any]] = {}
        for tr in trades_raw:
            tid = str(tr.get("id") or "")
            if tid:
                dedup[tid] = tr
        trades_sorted = sorted(dedup.values(), key=lambda x: x.get("timestamp") or 0)

        state = _load_state()
        entries: dict[str, Any] = dict(state.get("entries", {}))
        notified_set = {str(x) for x in state.get("notified_trade_ids", []) if x}
        notified_set.update(known_order_ids("kraken_trades.jsonl"))
        cum_fees = float(state.get("cumulative_fictive_fees_usd", 0) or 0)
        new_count = 0

        for tr in trades_sorted:
            tid = str(tr.get("id") or "")
            if not tid or tid in notified_set:
                continue
            sym = _norm_symbol(tr.get("symbol") or "")
            if sym not in pool_set:
                continue
            qty = float(tr.get("amount") or 0)
            price = float(tr.get("price") or 0)
            if qty <= 0 or price <= 0:
                continue
            side = str(tr.get("side") or "").lower()
            if side not in ("buy", "sell"):
                continue

            if side == "buy":
                cum_fees += qty * price * BITVAVO_FEE_BUY_RATE + JOURNAL_FIXED_FEE_PER_FILL_USD
                prev = entries.get(sym)
                if prev and float(prev.get("qty") or 0) > 0:
                    pq = float(prev["qty"])
                    pe = float(prev.get("entry") or 0)
                    new_qty = pq + qty
                    new_entry = (pe * pq + price * qty) / new_qty if new_qty > 0 else price
                    entries[sym] = {"qty": new_qty, "entry": new_entry}
                else:
                    entries[sym] = {"qty": qty, "entry": price}
                profit = None
                entry_price_for_log = None
            else:
                cum_fees += (
                    qty * price * BITVAVO_FEE_SELL_LIMIT_RATE + JOURNAL_FIXED_FEE_PER_FILL_USD
                )
                profit = None
                entry_price_for_log = None
                if sym in entries:
                    entry = float(entries[sym].get("entry") or 0)
                    entry_price_for_log = entry if entry > 0 else None
                    if entry > 0:
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

            ts_ms = tr.get("timestamp")
            ts_iso = (
                datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
                if ts_ms
                else None
            )
            append_kraken_fill_audit(
                {
                    "logged_at": datetime.now(timezone.utc).isoformat(),
                    "exchange_trade_timestamp": ts_iso,
                    "trade_id": tid,
                    "symbol": sym,
                    "quote_currency": "USD",
                    "side": side,
                    "filled_qty": qty,
                    "filled_avg_price_usd": price,
                    "notional_usd": round(qty * price, 10),
                    "portfolio_value_usd": round(portfolio_usd, 2),
                    "entry_price_usd_for_pnl": entry_price_for_log,
                    "estimated_roundtrip_profit_usd": round(profit, 8)
                    if profit is not None
                    else None,
                    "note": "Kraken spot USD; journal gebruikt fictief Bitvavo maker-model.",
                }
            )

            send_tg = (side == "buy" and TELEGRAM_NOTIFY_BUY_FILLS) or (
                side == "sell" and entry_price_for_log and entry_price_for_log > 0
            )
            log_trade(
                order_id=tid,
                symbol=sym,
                side=side,
                qty=qty,
                price=price,
                entry_price=entry_price_for_log,
                profit=profit,
                portfolio_value=portfolio_usd,
                journal_filename="kraken_trades.jsonl",
            )
            notify_trade_filled(
                side,
                sym,
                qty,
                price,
                profit,
                portfolio_usd,
                entry_price=entry_price_for_log,
                send_telegram_message=send_tg,
                currency_label="USD",
            )
            notified_set.add(tid)
            new_count += 1

        if new_count:
            save_kraken_state(
                entries=entries,
                notified_trade_ids=sorted(notified_set)[-1000:],
                cumulative_fictive_fees_usd=cum_fees,
            )
        return new_count, entries
    except Exception as e:
        log.warning("Kraken fill-check: %s", e)
        return 0, dict(_load_state().get("entries", {}))


MIN_SELLABLE_CRYPTO_QTY = Decimal("0.0001")


def persist_entries_from_balances(
    exchange: ccxt.kraken,
    symbols: list[str],
    entries_memory: dict[str, Any],
    mid_prices: dict[str, float],
) -> dict[str, Any]:
    """Schrijf entries compatibel met Alpaca-einde-run: qty uit balance, entry uit state of mid."""
    out: dict[str, Any] = {}
    for sym in symbols:
        free_q, _ = get_qty_for_symbol(exchange, sym)
        if free_q <= 0:
            continue
        if Decimal(str(free_q)) < MIN_SELLABLE_CRYPTO_QTY:
            continue
        mem = entries_memory.get(sym)
        if mem and float(mem.get("entry") or 0) > 0:
            out[sym] = {"qty": float(free_q), "entry": float(mem["entry"])}
        else:
            px = float(mid_prices.get(sym) or 0)
            out[sym] = {"qty": float(free_q), "entry": px}
    return out
