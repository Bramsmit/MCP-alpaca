#!/usr/bin/env python3
"""
Live paper trading bot - range strategie voor AVAX, UNI, AAVE.
Draait 1x per dag of via cron. Plaatst limit buy/sell en stop-loss orders.
"""

import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Laad .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce, QueryOrderStatus, OrderStatus
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, CryptoLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame

from bot.config import (
    SYMBOL_POOL,
    SYMBOLS_ACTIVE,
    CAPITAL_PER_ASSET,
    LEVELS_LOOKBACK_DAYS,
    BUY_ABOVE_LOW_PCT,
    SELL_BELOW_HIGH_PCT,
    MIN_SPREAD_PCT,
    BITVAVO_FEE_BUY_RATE,
    BITVAVO_FEE_SELL_LIMIT_RATE,
    STOP_LOSS_PER_UNIT,
    ORDER_UPDATE_THRESHOLD,
    ORDER_MAX_AGE_HOURS,
    ORDER_STALE_PRICE_THRESHOLD,
    ALPACA_CRYPTO_SINGLE_EXIT_ORDER,
    ORDER_REPLACE_DELAY_SEC,
)
from bot.telegram import send_telegram, notify_trade, notify_trade_filled
from bot.journal import log_trade


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


def get_24h_levels(data_client, symbols: list[str]) -> dict[str, tuple[float, float]]:
    """Haal vorige dag high/low op voor buy/sell niveaus."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=5)

    request = CryptoBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = data_client.get_crypto_bars(request)
    result = {}

    for symbol in symbols:
        if symbol not in bars.df.index.get_level_values(0):
            continue
        df = bars.df.loc[symbol].tail(LEVELS_LOOKBACK_DAYS + 2)
        if len(df) < LEVELS_LOOKBACK_DAYS:
            continue
        # Gemiddelde van laatste N dagen (minder gevoelig voor uitschieters dan 1 dag)
        recent = df.tail(LEVELS_LOOKBACK_DAYS)
        low = float(recent["low"].mean())
        high = float(recent["high"].mean())
        buy_level = low * (1 + BUY_ABOVE_LOW_PCT)
        sell_level = high * (1 - SELL_BELOW_HIGH_PCT)
        if sell_level >= buy_level * (1 + MIN_SPREAD_PCT):
            result[symbol] = (buy_level, sell_level)
    return result


def _get_levels_and_scores(data_client, symbols: list[str]) -> dict[str, tuple[float, float, float]]:
    """Levels + score per symbol. score = spread_pct * (1 + range_volatility)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=5)
    request = CryptoBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = data_client.get_crypto_bars(request)
    result = {}

    for symbol in symbols:
        if symbol not in bars.df.index.get_level_values(0):
            continue
        df = bars.df.loc[symbol].tail(LEVELS_LOOKBACK_DAYS + 2)
        if len(df) < LEVELS_LOOKBACK_DAYS:
            continue
        recent = df.tail(LEVELS_LOOKBACK_DAYS)
        low = float(recent["low"].mean())
        high = float(recent["high"].mean())
        buy_level = low * (1 + BUY_ABOVE_LOW_PCT)
        sell_level = high * (1 - SELL_BELOW_HIGH_PCT)
        spread_ok = sell_level >= buy_level * (1 + MIN_SPREAD_PCT)
        spread_pct = (sell_level - buy_level) / buy_level if spread_ok else 0
        range_pct = (high - low) / low if low else 0
        score = spread_pct * (1 + range_pct)
        result[symbol] = (buy_level, sell_level, score)
    return result


def select_top_symbols(
    data_client, trading_client, pool: list[str], n: int
) -> tuple[list[str], dict[str, tuple[float, float]]]:
    """
    Selecteer top N meest winstgevende symbolen uit pool.
    Symbolen met open posities blijven altijd actief.
    Retourneert (symbols, levels).
    """
    levels_scored = _get_levels_and_scores(data_client, pool)
    positions = get_positions(trading_client, symbols=pool)
    symbols_with_positions = set(positions.keys())

    # Sorteer op score (hoogste eerst)
    sorted_by_score = sorted(
        levels_scored.items(),
        key=lambda x: x[1][2],
        reverse=True,
    )

    selected = list(symbols_with_positions)
    for sym, (buy, sell, _) in sorted_by_score:
        if sym not in selected and len(selected) < n:
            selected.append(sym)

    levels = {sym: (buy, sell) for sym, (buy, sell, _) in sorted_by_score if sym in selected}
    # Voor symbolen met posities zonder levels (geen bar data): haal levels apart op
    missing = [s for s in selected if s not in levels]
    if missing:
        fallback = get_24h_levels(data_client, missing)
        levels.update(fallback)
    return selected, levels


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
MIN_SELLABLE_CRYPTO_QTY = Decimal("0.0001")  # strikter: 1e-4 (was 1e-5; vangt AVAX dust)


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

    Primair: qty_available (niet gelocked in open orders) — zelfde als 'available' in API-fouten.
    Fallback: qty als qty_available ontbreekt (oude clients / edge cases).

    Let op: na cancel van een sell-order even wachten + positie verversen, anders kan
    qty_available nog 0 zijn.
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
            # Expliciet 0: niets vrij te verkopen (o.a. nog gelocked)
            return Decimal(0)

    raw_qty = data.get("qty")
    d_qty = _decimal_from_json_qty(raw_qty)
    return d_qty if d_qty is not None and d_qty > 0 else Decimal(0)


def _decimal_to_submit_sell_qty(d: Decimal) -> float:
    """Decimal -> float voor LimitOrderRequest (qty komt uit Alpaca-strings, geen round()-bugs)."""
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


def _order_age_hours(order) -> float:
    """Leeftijd van order in uren. Gebruik submitted_at of created_at."""
    ts = getattr(order, "submitted_at", None) or getattr(order, "created_at", None)
    if not ts:
        return 0.0
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - ts
    return delta.total_seconds() / 3600


def get_buying_power(trading_client) -> float:
    """Beschikbaar cash."""
    acc = trading_client.get_account()
    return float(acc.cash)


def get_portfolio_value(trading_client) -> float:
    """Totaal portfolio waarde (equity)."""
    acc = trading_client.get_account()
    return float(getattr(acc, "equity", 0) or getattr(acc, "portfolio_value", 0) or 0)


def _state_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".alpaca_trade_state.json"


def _load_state() -> dict:
    """Laad state uit file."""
    path = _state_path()
    if not path.exists():
        return {"entries": {}, "notified_order_ids": []}
    try:
        import json
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
        import json
        path.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.warning("Kon state niet opslaan: %s", e)


def _check_and_notify_filled_orders(trading_client, symbols: list[str]) -> int:
    """Check gevulde orders sinds vorige run, stuur Telegram notificatie. Retourneert aantal nieuwe trades."""
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
                    # Bitvavo per trade: notional × (1 ± fee); limiet ≈ maker
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


def run_once():
    """Eén run van de trading bot."""
    trading_client, data_client = get_trading_clients()

    # Selecteer top N meest winstgevende symbolen uit pool
    symbols, levels = select_top_symbols(
        data_client, trading_client, SYMBOL_POOL, SYMBOLS_ACTIVE
    )
    if not symbols:
        log.warning("Geen symbolen geselecteerd uit pool")
        send_telegram("⚠️ Geen symbolen geselecteerd uit pool")
        return {}

    new_trades = _check_and_notify_filled_orders(trading_client, SYMBOL_POOL)

    current_prices = get_current_prices(data_client, symbols)
    positions = get_positions(trading_client, symbols=symbols)
    buying_power = get_buying_power(trading_client)

    capital_per = buying_power / len(symbols)

    stats = {"placed": 0, "updated": 0, "unchanged": 0, "skipped": 0}

    log.info("Geselecteerd: %s", ", ".join(symbols))
    log.info("Buying power: $%.2f | Per asset: $%.2f", buying_power, capital_per)
    log.info("Levels: %s", levels)
    log.info("Current prices: %s", current_prices)
    log.info("Positions: %s", positions)
    log.info("")

    for symbol in symbols:
        if symbol not in levels:
            continue
        buy_level, sell_level = levels[symbol]
        pos_data = positions.get(symbol, (0, 0))
        pos_qty, avg_entry = pos_data
        open_orders = get_open_orders(trading_client, symbol)

        # Cleanup: geen positie maar wel sell orders -> annuleer
        if pos_qty <= 0:
            for o in open_orders:
                if o.side == OrderSide.SELL:
                    try:
                        trading_client.cancel_order_by_id(o.id)
                        log.info("  %s: Orphan sell order geannuleerd", symbol)
                    except Exception:
                        pass

        if pos_qty > 0 and Decimal(str(pos_qty)) < MIN_SELLABLE_CRYPTO_QTY:
            # Dust: annuleer sell orders, geen nieuwe plaatsen (voorkomt qty must be > 0 / insufficient balance)
            for o in open_orders:
                if o.side == OrderSide.SELL:
                    try:
                        trading_client.cancel_order_by_id(o.id)
                        log.info("  %s: Dust positie (qty=%s), sell order geannuleerd", symbol, pos_qty)
                    except Exception:
                        pass
            continue

        if pos_qty > 0:
            # We hebben positie: zorg voor sell + stop-loss, update als prijs bewogen is
            existing_sell = next((o for o in open_orders if o.side == OrderSide.SELL and o.order_type == OrderType.LIMIT), None)
            existing_stop = next((o for o in open_orders if o.side == OrderSide.SELL and o.order_type == OrderType.STOP_LIMIT), None)
            entry = avg_entry if avg_entry > 0 else buy_level
            stop_price = entry - STOP_LOSS_PER_UNIT
            limit_sell = sell_level

            needs_new_sell = True

            if existing_sell:
                old_sell_price = float(existing_sell.limit_price)
                age_hours = _order_age_hours(existing_sell)
                price_diff = abs(old_sell_price - limit_sell) / old_sell_price
                current_price = current_prices.get(symbol)

                # Stale price: huidige prijs >5% onder sell target -> order te optimistisch
                if current_price and current_price < limit_sell * (1 - ORDER_STALE_PRICE_THRESHOLD):
                    try:
                        trading_client.cancel_order_by_id(existing_sell.id)
                        if existing_stop:
                            trading_client.cancel_order_by_id(existing_stop.id)
                        pct_below = (limit_sell - current_price) / limit_sell * 100
                        log.info("  %s: Sell order vervangen (prijs $%.2f is %.1f%% onder target)", symbol, current_price, pct_below)
                        send_telegram(f"🔄 {symbol}: Sell order vervangen, prijs {pct_below:.1f}% onder target, nieuwe @ ${limit_sell:.4f}")
                        stats["updated"] += 1
                    except Exception as e:
                        log.warning("  %s: Fout bij annuleren sell order: %s", symbol, e)
                        needs_new_sell = False
                elif age_hours >= ORDER_MAX_AGE_HOURS:
                    try:
                        trading_client.cancel_order_by_id(existing_sell.id)
                        if existing_stop:
                            trading_client.cancel_order_by_id(existing_stop.id)
                        log.info("  %s: Sell order vervangen na %.0fh (verse 24h window)", symbol, age_hours)
                        send_telegram(f"🔄 {symbol}: Sell order vervangen na {age_hours:.0f}h, nieuwe levels @ ${limit_sell:.4f}")
                        stats["updated"] += 1
                    except Exception as e:
                        log.warning("  %s: Fout bij annuleren sell order: %s", symbol, e)
                        needs_new_sell = False
                elif price_diff > ORDER_UPDATE_THRESHOLD:
                    try:
                        trading_client.cancel_order_by_id(existing_sell.id)
                        if existing_stop:
                            trading_client.cancel_order_by_id(existing_stop.id)
                        log.info("  %s: Sell order bijgewerkt (%.4f -> %.4f, %.1f%% verschil)", symbol, old_sell_price, limit_sell, price_diff * 100)
                        send_telegram(f"🔄 {symbol}: Sell order bijgewerkt @ ${limit_sell:.4f} (was ${old_sell_price:.4f})")
                        stats["updated"] += 1
                    except Exception as e:
                        log.warning("  %s: Fout bij annuleren sell order: %s", symbol, e)
                        needs_new_sell = False
                else:
                    log.info("  %s: Sell order ongewijzigd @ $%.4f (%.1f%% verschil, %.0fh oud)", symbol, old_sell_price, price_diff * 100, age_hours)
                    stats["unchanged"] += 1
                    needs_new_sell = False

            if needs_new_sell:
                try:
                    # Na cancel: wacht tot balance vrijkomt (Alpaca heeft vertraging)
                    if existing_sell and ORDER_REPLACE_DELAY_SEC > 0:
                        time.sleep(ORDER_REPLACE_DELAY_SEC)
                    assert ALPACA_CRYPTO_SINGLE_EXIT_ORDER, "Alpaca crypto: max 1 exit order per positie"
                    pos_live = _find_position(trading_client, symbol)
                    d_live = _sell_qty_decimal_from_position(pos_live)
                    if pos_live is None or d_live <= 0:
                        log.warning(
                            "  %s: Geen sell geplaatst: geen positie of qty=0 (na cancel / sync)",
                            symbol,
                        )
                    else:
                        _submit_crypto_sell(trading_client, symbol, pos_live, limit_sell)
                        log.info(
                            "  %s: Sell limit @ $%.4f (stop @ $%.4f niet geplaatst - crypto 1 order/positie)",
                            symbol,
                            limit_sell,
                            stop_price,
                        )
                        if not existing_sell:
                            send_telegram(f"📊 {symbol}: Sell limit @ ${limit_sell:.4f} geplaatst")
                            stats["placed"] += 1
                except Exception as e:
                    err_str = str(e)
                    if "insufficient balance" in err_str.lower() or "40310000" in err_str:
                        log.info("  %s: Retry na insufficient balance...", symbol)
                        time.sleep(ORDER_REPLACE_DELAY_SEC + 2)
                        pos_live = _find_position(trading_client, symbol)
                        d_live = _sell_qty_decimal_from_position(pos_live)
                        try:
                            if pos_live is not None and d_live > 0:
                                _submit_crypto_sell(trading_client, symbol, pos_live, limit_sell)
                                log.info("  %s: Sell limit @ $%.4f (retry ok)", symbol, limit_sell)
                                if not existing_sell:
                                    send_telegram(f"📊 {symbol}: Sell limit @ ${limit_sell:.4f} geplaatst")
                                    stats["placed"] += 1
                            else:
                                log.warning("  %s: Geen positie na balance-retry", symbol)
                        except Exception as e2:
                            log.warning("  %s: Fout (retry): %s", symbol, e2)
                            send_telegram(f"❌ {symbol}: Fout orders: {e2}")
                    elif "40010001" in err_str or "qty must be" in err_str.lower():
                        log.info("  %s: Retry na qty-fout, positie opnieuw ophalen...", symbol)
                        time.sleep(ORDER_REPLACE_DELAY_SEC + 2)
                        pos_live = _find_position(trading_client, symbol)
                        d_live = _sell_qty_decimal_from_position(pos_live)
                        try:
                            if pos_live is not None and d_live > 0:
                                _submit_crypto_sell(trading_client, symbol, pos_live, limit_sell)
                                log.info("  %s: Sell limit @ $%.4f (retry na qty)", symbol, limit_sell)
                                if not existing_sell:
                                    send_telegram(f"📊 {symbol}: Sell limit @ ${limit_sell:.4f} geplaatst")
                                    stats["placed"] += 1
                            else:
                                log.warning("  %s: Geen positie na qty-retry", symbol)
                        except Exception as e2:
                            log.warning("  %s: Fout (qty retry): %s", symbol, e2)
                            send_telegram(f"❌ {symbol}: Fout orders: {e2}")
                    else:
                        log.warning("  %s: Fout: %s", symbol, e)
                        send_telegram(f"❌ {symbol}: Fout orders: {e}")
        else:
            # Geen positie: plaats of update limit buy order
            if capital_per < 10:
                log.info("  %s: Te weinig kapitaal ($%.2f, min $10), skip", symbol, capital_per)
                stats["skipped"] += 1
            elif buy_level < 0.0001:
                # Alpaca: "limit price must be > 0" voor zeer lage prijzen (SHIB ~5e-6, PEPE)
                log.info("  %s: Prijs $%.8f te laag - Alpaca API accepteert dit niet", symbol, float(buy_level))
                send_telegram(f"⚠️ {symbol}: Overgeslagen (prijs te laag voor Alpaca limit orders)")
                stats["skipped"] += 1
            else:
                existing_buy = next((o for o in open_orders if o.side == OrderSide.BUY), None)
                needs_new_order = True

                if existing_buy:
                    old_price = float(existing_buy.limit_price)
                    age_hours = _order_age_hours(existing_buy)
                    price_diff = abs(old_price - buy_level) / old_price
                    current_price = current_prices.get(symbol)

                    # Stale price: huidige prijs >5% boven order -> vult waarschijnlijk niet
                    if current_price and current_price > old_price * (1 + ORDER_STALE_PRICE_THRESHOLD):
                        try:
                            trading_client.cancel_order_by_id(existing_buy.id)
                            pct_above = (current_price - old_price) / old_price * 100
                            log.info("  %s: Buy order vervangen (prijs $%.2f is %.1f%% boven order)", symbol, current_price, pct_above)
                            send_telegram(f"🔄 {symbol}: Buy order vervangen, prijs {pct_above:.1f}% boven order, nieuwe @ ${buy_level:.4f}")
                            stats["updated"] += 1
                        except Exception as e:
                            log.warning("  %s: Fout bij annuleren buy order: %s", symbol, e)
                            needs_new_order = False
                    elif age_hours >= ORDER_MAX_AGE_HOURS:
                        try:
                            trading_client.cancel_order_by_id(existing_buy.id)
                            log.info("  %s: Buy order vervangen na %.0fh (verse 24h window)", symbol, age_hours)
                            send_telegram(f"🔄 {symbol}: Buy order vervangen na {age_hours:.0f}h, nieuwe levels @ ${buy_level:.4f}")
                            stats["updated"] += 1
                        except Exception as e:
                            log.warning("  %s: Fout bij annuleren buy order: %s", symbol, e)
                            needs_new_order = False
                    elif price_diff > ORDER_UPDATE_THRESHOLD:
                        try:
                            trading_client.cancel_order_by_id(existing_buy.id)
                            log.info("  %s: Buy order bijgewerkt (%.4f -> %.4f, %.1f%% verschil)", symbol, old_price, buy_level, price_diff * 100)
                            send_telegram(f"🔄 {symbol}: Buy order bijgewerkt @ ${buy_level:.4f} (was ${old_price:.4f})")
                            stats["updated"] += 1
                        except Exception as e:
                            log.warning("  %s: Fout bij annuleren buy order: %s", symbol, e)
                            needs_new_order = False
                    else:
                        log.info("  %s: Buy order ongewijzigd @ $%.4f (%.1f%% verschil, %.0fh oud)", symbol, old_price, price_diff * 100, age_hours)
                        stats["unchanged"] += 1
                        needs_new_order = False

                if needs_new_order:
                    # Na cancel: wacht tot balance vrijkomt
                    if existing_buy and ORDER_REPLACE_DELAY_SEC > 0:
                        time.sleep(ORDER_REPLACE_DELAY_SEC)
                    qty = capital_per / buy_level
                    limit_px = _round_price(buy_level)
                    try:
                        trading_client.submit_order(
                            LimitOrderRequest(
                                symbol=symbol,
                                qty=round(qty, 6),
                                side=OrderSide.BUY,
                                type=OrderType.LIMIT,
                                time_in_force=TimeInForce.GTC,
                                limit_price=limit_px,
                            )
                        )
                        price_str = f"${buy_level:.8f}" if buy_level < 0.001 else f"${buy_level:.4f}"
                        log.info("  %s: Limit buy @ %s ($%.0f)", symbol, price_str, capital_per)
                        if not existing_buy:
                            send_telegram(f"📊 {symbol}: Limit buy @ ${buy_level:.4f} (${capital_per:.0f}) geplaatst")
                            stats["placed"] += 1
                    except Exception as e:
                        log.warning("  %s: Fout buy: %s", symbol, e)
                        send_telegram(f"❌ {symbol}: Fout buy order: {e}")

    # Bewaar entry prices voor volgende run (profit berekening bij sell)
    entries = {sym: {"qty": qty, "entry": entry} for sym, (qty, entry) in positions.items() if entry > 0}
    _save_state(entries=entries)

    # Run summary (incl. trade-status en actieve symbolen)
    trade_status = f"{new_trades} nieuwe trade(s) gevuld" if new_trades else "Geen nieuwe trades gevuld"
    summary = f"Run: {stats['placed']} geplaatst, {stats['updated']} bijgewerkt, {stats['unchanged']} ongewijzigd, {stats['skipped']} overgeslagen | {trade_status}"
    if symbols:
        summary += f"\nActief: {', '.join(symbols)}"
    log.info(summary)
    send_telegram(f"📋 {summary}")
    return stats


def main():
    log.info("=" * 50)
    log.info("MCP-Alpaca Live Paper Trader")
    log.info("=" * 50)
    log.info("Pool: %s (top %d actief)", ", ".join(SYMBOL_POOL), SYMBOLS_ACTIVE)
    log.info("Run op: %s", datetime.now().isoformat())
    log.info("")

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            run_once()
            log.info("Klaar.")
            return
        except Exception as e:
            log.warning("Fout (poging %d/%d): %s", attempt + 1, max_retries + 1, e)
            if attempt < max_retries:
                wait_sec = 5 * (attempt + 1)
                log.info("Retry over %d sec...", wait_sec)
                time.sleep(wait_sec)
            else:
                send_telegram(f"❌ Bot fout: {e}")
                raise


if __name__ == "__main__":
    main()
