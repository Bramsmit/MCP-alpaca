#!/usr/bin/env python3
"""
Bitvavo range-trading bot via ccxt.
Plaatst limit buy/sell orders op basis van rolling 3-daags high/low.
Draait 1x per uur via GitHub Actions.

Fees/spread/postOnly staan in bot_live/bitvavo_config.py. Optioneel: env BITVAVO_POST_ONLY=false
om postOnly uit te zetten als de exchange orders weigert.
"""

import json
import logging
import os
import time
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

import ccxt

from bot_live.bitvavo_config import (
    SYMBOL_POOL,
    SYMBOLS_ACTIVE,
    MAX_CAPITAL_EUR,
    LEVELS_LOOKBACK_DAYS,
    BUY_ABOVE_LOW_PCT,
    SELL_BELOW_HIGH_PCT,
    MIN_SPREAD_PCT,
    ESTIMATED_ROUND_TRIP_FEE_PCT,
    FEE_MAKER_PCT,
    POST_ONLY_LIMIT_ORDERS,
    ORDER_UPDATE_THRESHOLD,
    ORDER_MAX_AGE_HOURS,
    ORDER_STALE_PRICE_THRESHOLD,
    ORDER_REPLACE_DELAY_SEC,
)
from bot_live.telegram import send_telegram, notify_trade_filled
from bot_live.journal import log_trade

# Minimale bruto-spread = strategie-rand + geschatte round-trip fees (maker)
_EFFECTIVE_MIN_SPREAD_PCT = MIN_SPREAD_PCT + ESTIMATED_ROUND_TRIP_FEE_PCT

# Aparte state/journal bestanden voor Bitvavo (los van Alpaca)
_BITVAVO_STATE_FILE = ".bitvavo_trade_state.json"
_BITVAVO_JOURNAL_FILE = "bitvavo_trades.jsonl"

# Minimale qty om te verkopen (voorkomt dust-orders)
MIN_SELLABLE_QTY = 1e-6


def get_exchange():
    """Maak Bitvavo ccxt exchange. DRY_RUN=True logt orders maar plaatst ze niet."""
    api_key = os.environ.get("BITVAVO_API_KEY", "").strip()
    secret = os.environ.get("BITVAVO_SECRET_KEY", "").strip()
    if not api_key or not secret:
        raise ValueError("BITVAVO_API_KEY en BITVAVO_SECRET_KEY vereist in .env")
    dry_run = os.environ.get("BITVAVO_DRY_RUN", "True").strip().lower() in ("true", "1", "yes")
    if dry_run:
        log.warning("⚠️  DRY RUN — geen echte orders worden geplaatst")
    exchange = ccxt.bitvavo({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {
            "operatorId": 0,  # 0 = self-directed trading (geen broker/operator)
        },
    })
    exchange.load_markets()
    return exchange, dry_run


def get_balance(exchange) -> float:
    """
    Vrij EUR: `fetch_balance()['EUR']['free']` — nog niet vastgezet in open orders.
    Dat is het saldo dat Bitvavo beschikbaar noemt voor nieuwe orders; daarna bepalen we de buy-grootte.
    """
    b = exchange.fetch_balance()
    return float(b.get("EUR", {}).get("free", 0) or 0)


def get_portfolio_value(exchange) -> float:
    """
    Portfoliowaarde van het bot-gedeelte in EUR (max MAX_CAPITAL_EUR).
    = waarde crypto posities (SYMBOL_POOL) + EUR in open buy orders + resterende vrije EUR (gemaximeerd).
    Toont NIET de rest van het Kraken account.
    """
    b = exchange.fetch_balance()

    # Waarde van crypto posities in SYMBOL_POOL
    crypto_value = 0.0
    for symbol in SYMBOL_POOL:
        base = symbol.split("/")[0]
        qty = float(b.get(base, {}).get("total", 0) or 0)
        if qty > 0:
            try:
                ticker = exchange.fetch_ticker(symbol)
                price = float(ticker.get("last") or 0)
                crypto_value += qty * price
            except Exception:
                pass

    # EUR gelocked in open buy orders (bot-geplaatst)
    eur_in_orders = 0.0
    try:
        for symbol in SYMBOL_POOL:
            orders = exchange.fetch_open_orders(symbol)
            for o in orders:
                if o.get("side") == "buy":
                    amount = float(o.get("amount") or 0)
                    price = float(o.get("price") or 0)
                    eur_in_orders += amount * price
    except Exception:
        pass

    # Vrije EUR, gemaximeerd op MAX_CAPITAL_EUR minus al ingezet kapitaal
    free_eur = float(b.get("EUR", {}).get("free", 0) or 0)
    deployed = crypto_value + eur_in_orders
    free_eur_for_bot = min(free_eur, max(0.0, MAX_CAPITAL_EUR - deployed))

    return crypto_value + eur_in_orders + free_eur_for_bot


def get_current_prices(exchange, symbols: list[str]) -> dict[str, float]:
    """Huidige midprijs per symbool."""
    result = {}
    for symbol in symbols:
        try:
            ticker = exchange.fetch_ticker(symbol)
            bid = float(ticker.get("bid") or 0)
            ask = float(ticker.get("ask") or 0)
            last = float(ticker.get("last") or 0)
            if bid and ask:
                result[symbol] = (bid + ask) / 2
            elif last:
                result[symbol] = last
        except Exception as e:
            log.warning("get_current_prices %s: %s", symbol, e)
    return result


def get_24h_levels(exchange, symbols: list[str]) -> dict[str, tuple[float, float]]:
    """Bereken buy/sell niveaus uit recente daily bars."""
    result = {}
    for symbol in symbols:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, "1d", limit=LEVELS_LOOKBACK_DAYS + 2)
            if len(ohlcv) < LEVELS_LOOKBACK_DAYS:
                continue
            recent = ohlcv[-LEVELS_LOOKBACK_DAYS:]
            low = sum(bar[3] for bar in recent) / len(recent)
            high = sum(bar[2] for bar in recent) / len(recent)
            buy_level = low * (1 + BUY_ABOVE_LOW_PCT)
            sell_level = high * (1 - SELL_BELOW_HIGH_PCT)
            if sell_level >= buy_level * (1 + _EFFECTIVE_MIN_SPREAD_PCT):
                result[symbol] = (buy_level, sell_level)
        except Exception as e:
            log.warning("get_24h_levels %s: %s", symbol, e)
    return result


def _get_levels_and_scores(exchange, symbols: list[str]) -> dict[str, tuple[float, float, float]]:
    """Levels + winstbaarheidsscore per symbool."""
    result = {}
    for symbol in symbols:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, "1d", limit=LEVELS_LOOKBACK_DAYS + 2)
            if len(ohlcv) < LEVELS_LOOKBACK_DAYS:
                continue
            recent = ohlcv[-LEVELS_LOOKBACK_DAYS:]
            low = sum(bar[3] for bar in recent) / len(recent)
            high = sum(bar[2] for bar in recent) / len(recent)
            buy_level = low * (1 + BUY_ABOVE_LOW_PCT)
            sell_level = high * (1 - SELL_BELOW_HIGH_PCT)
            spread_ok = sell_level >= buy_level * (1 + _EFFECTIVE_MIN_SPREAD_PCT)
            spread_pct = (sell_level - buy_level) / buy_level if spread_ok else 0
            range_pct = (high - low) / low if low else 0
            score = spread_pct * (1 + range_pct)
            result[symbol] = (buy_level, sell_level, score)
        except Exception as e:
            log.warning("_get_levels_and_scores %s: %s", symbol, e)
    return result


def get_positions(exchange, symbols: list[str]) -> dict[str, float]:
    """Huidige crypto holdings: {symbol: total_qty}. Inclusief qty in open sell orders."""
    b = exchange.fetch_balance()
    result = {}
    for symbol in symbols:
        base = symbol.split("/")[0]
        qty = float(b.get(base, {}).get("total", 0) or 0)
        if qty > MIN_SELLABLE_QTY:
            result[symbol] = qty
    return result


def get_free_sell_qty(exchange, symbol: str) -> float:
    """Vrije qty die verkocht mag worden (niet gelocked in open orders)."""
    b = exchange.fetch_balance()
    base = symbol.split("/")[0]
    return float(b.get(base, {}).get("free", 0) or 0)


def select_top_symbols(
    exchange, pool: list[str], n: int
) -> tuple[list[str], dict[str, tuple[float, float]]]:
    """Selecteer top N symbolen op score. Symbolen met posities blijven altijd actief."""
    levels_scored = _get_levels_and_scores(exchange, pool)
    positions = get_positions(exchange, pool)
    symbols_with_positions = set(positions.keys())

    sorted_by_score = sorted(
        levels_scored.items(),
        key=lambda x: x[1][2],
        reverse=True,
    )

    selected = list(symbols_with_positions)
    for sym, _ in sorted_by_score:
        if sym not in selected and len(selected) < n:
            selected.append(sym)

    levels = {sym: (buy, sell) for sym, (buy, sell, _) in sorted_by_score if sym in selected}
    missing = [s for s in selected if s not in levels]
    if missing:
        fallback = get_24h_levels(exchange, missing)
        levels.update(fallback)
    return selected, levels


def get_bot_open_orders(exchange, symbol: str, bot_order_ids: set) -> list:
    """
    Haal alleen open orders op die door deze bot geplaatst zijn.
    Filtert op opgeslagen order IDs — andere orders (Bitsgap, app, etc.) worden genegeerd.
    """
    if not bot_order_ids:
        return []
    try:
        all_orders = exchange.fetch_open_orders(symbol)
        return [o for o in all_orders if o["id"] in bot_order_ids]
    except Exception as e:
        log.warning("get_bot_open_orders %s: %s", symbol, e)
        return []


def _order_age_hours(order: dict) -> float:
    """Leeftijd van order in uren (ccxt order dict)."""
    ts = order.get("timestamp")
    if not ts:
        return 0.0
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


def _round_amount(exchange, symbol: str, amount: float) -> float:
    """Afronden naar exchange precisie voor hoeveelheid."""
    try:
        return float(exchange.amount_to_precision(symbol, amount))
    except Exception:
        return round(amount, 8)


def _round_price(exchange, symbol: str, price: float) -> float:
    """Afronden naar exchange precisie voor prijs."""
    try:
        return float(exchange.price_to_precision(symbol, price))
    except Exception:
        p = float(price)
        return round(p, 2) if p >= 1 else round(p, 6)


def _limit_order_params() -> dict:
    """postOnly=True: Bitvavo annuleert als de limit direct zou matchen (maker fee)."""
    po = os.environ.get("BITVAVO_POST_ONLY")
    if po is not None and str(po).strip():
        use_post_only = str(po).strip().lower() not in ("false", "0", "no")
    else:
        use_post_only = POST_ONLY_LIMIT_ORDERS
    return {"postOnly": True} if use_post_only else {}


def _order_size_ok(exchange, symbol: str, qty: float, price: float) -> tuple[bool, str]:
    """Controleer ccxt market limits (min notional / min amount)."""
    try:
        m = exchange.market(symbol)
        limits = m.get("limits") or {}
        cost = qty * price
        cmin = (limits.get("cost") or {}).get("min")
        amin = (limits.get("amount") or {}).get("min")
        if cmin is not None and float(cmin) > 0 and cost < float(cmin) - 1e-12:
            return False, f"notional €{cost:.2f} < min €{float(cmin):.2f}"
        if amin is not None and float(amin) > 0 and qty < float(amin) - 1e-12:
            return False, f"qty {qty} < min {float(amin)}"
    except Exception as e:
        log.warning("order size check %s: %s", symbol, e)
    return True, ""


def _state_path() -> Path:
    return Path(__file__).resolve().parent.parent / _BITVAVO_STATE_FILE


def _load_state() -> dict:
    path = _state_path()
    if not path.exists():
        return {"entries": {}, "notified_trade_ids": [], "bot_orders": {}}
    try:
        data = json.loads(path.read_text())
        return {
            "entries": data.get("entries", {}),
            "notified_trade_ids": data.get("notified_trade_ids", data.get("notified_order_ids", [])),
            # bot_orders: {symbol: {"buy": order_id, "sell": order_id}}
            "bot_orders": data.get("bot_orders", {}),
        }
    except Exception:
        return {"entries": {}, "notified_trade_ids": [], "bot_orders": {}}


def _save_state(
    entries: dict | None = None,
    notified_ids: list[str] | None = None,
    bot_orders: dict | None = None,
) -> None:
    path = _state_path()
    state = _load_state()
    if entries is not None:
        state["entries"] = entries
    if notified_ids is not None:
        state["notified_trade_ids"] = notified_ids[-200:]
    if bot_orders is not None:
        state["bot_orders"] = bot_orders
    try:
        path.write_text(json.dumps(state, indent=2))
    except Exception as e:
        log.warning("Kon state niet opslaan: %s", e)


def _check_and_notify_filled_trades(
    exchange, symbols: list[str], state_entries: dict
) -> tuple[int, dict]:
    """
    Detecteer gevulde trades (fills) van de laatste 4 uur.
    Stuurt Telegram notificatie per fill. Retourneert (aantal_nieuw, updated_entries).
    """
    try:
        since_ms = int((datetime.now(timezone.utc) - timedelta(hours=4)).timestamp() * 1000)
        state = _load_state()
        notified_ids = list(state.get("notified_trade_ids", []))
        entries = dict(state_entries)
        new_notified = []
        new_count = 0

        portfolio_value = get_portfolio_value(exchange)

        for symbol in symbols:
            try:
                trades = exchange.fetch_my_trades(symbol, since=since_ms)
            except Exception as e:
                log.warning("fetch_my_trades %s: %s", symbol, e)
                continue

            for t in trades:
                tid = str(t.get("id", ""))
                if not tid or tid in notified_ids:
                    continue
                side = t.get("side", "")
                qty = float(t.get("amount") or 0)
                price = float(t.get("price") or 0)
                if not qty or not price:
                    continue

                profit = None
                entry_price_for_log = None

                if side == "sell" and symbol in entries:
                    entry = entries[symbol].get("entry", 0)
                    entry_price_for_log = entry if entry else None
                    if entry:
                        buy_fee = entry * qty * FEE_MAKER_PCT
                        sell_fee = price * qty * FEE_MAKER_PCT
                        profit = (price - entry) * qty - buy_fee - sell_fee
                    del entries[symbol]
                elif side == "buy":
                    entries[symbol] = {"qty": qty, "entry": price}

                notify_trade_filled(
                    side,
                    symbol,
                    qty,
                    price,
                    profit,
                    portfolio_value,
                    entry_price=entry_price_for_log,
                )
                log_trade(
                    order_id=tid,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    price=price,
                    entry_price=entry_price_for_log,
                    profit=profit,
                    portfolio_value=portfolio_value,
                )
                new_notified.append(tid)
                new_count += 1

        if new_notified:
            _save_state(notified_ids=notified_ids + new_notified)

        return new_count, entries

    except Exception as e:
        log.warning("check filled trades: %s", e)
        return 0, state_entries


def run_once():
    """Eén run van de trading bot."""
    exchange, dry_run = get_exchange()

    state = _load_state()
    state_entries = dict(state.get("entries", {}))
    # bot_orders: {symbol: {"buy": order_id, "sell": order_id}}
    # Alleen orders in dit dict worden aangeraakt — andere orders blijven ongemoeid.
    bot_orders = dict(state.get("bot_orders", {}))

    symbols, levels = select_top_symbols(exchange, SYMBOL_POOL, SYMBOLS_ACTIVE)
    if not symbols:
        log.warning("Geen symbolen geselecteerd")
        send_telegram("⚠️ Geen symbolen geselecteerd uit pool")
        return {}

    new_trades, state_entries = _check_and_notify_filled_trades(exchange, SYMBOL_POOL, state_entries)

    current_prices = get_current_prices(exchange, symbols)
    balance_eur = get_balance(exchange)
    positions = get_positions(exchange, symbols)

    # Doelkapitaal per symbool op basis van MAX_CAPITAL_EUR (niet vrije balance).
    # Replacement orders annuleren eerst (vrijmaken) en plaatsen daarna,
    # dus het kapitaal is altijd tijdelijk beschikbaar.
    # 0.5% buffer voor afrondingsverschillen en Bitvavo order locking.
    capital_per = (MAX_CAPITAL_EUR / len(symbols)) * 0.995

    stats = {"placed": 0, "updated": 0, "unchanged": 0, "skipped": 0}

    log.info("Geselecteerd: %s", ", ".join(symbols))
    log.info(
        "Fees/spread: maker %.2f%%/zijde | effectieve min. spread %.2f%% (strategie %.2f%% + round-trip fees %.2f%%)",
        FEE_MAKER_PCT * 100,
        _EFFECTIVE_MIN_SPREAD_PCT * 100,
        MIN_SPREAD_PCT * 100,
        ESTIMATED_ROUND_TRIP_FEE_PCT * 100,
    )
    log.info("Vrij EUR: €%.2f | Max: €%.2f | Per asset: €%.2f", balance_eur, MAX_CAPITAL_EUR, capital_per)
    log.info("Levels: %s", levels)
    log.info("Prijzen: %s", current_prices)
    log.info("Posities: %s", positions)
    log.info("")

    for symbol in symbols:
        if symbol not in levels:
            continue
        buy_level, sell_level = levels[symbol]
        pos_qty = positions.get(symbol, 0)

        # Haal alleen bot-eigen orders op (andere orders worden volledig genegeerd)
        sym_bot_ids = set(v for v in bot_orders.get(symbol, {}).values() if v)
        open_orders = get_bot_open_orders(exchange, symbol, sym_bot_ids)

        # Cleanup: geen positie maar bot heeft sell order → annuleer
        if pos_qty <= 0:
            for o in open_orders:
                if o.get("side") == "sell":
                    try:
                        if not dry_run:
                            exchange.cancel_order(o["id"], symbol)
                        bot_orders.setdefault(symbol, {}).pop("sell", None)
                        log.info("  %s: Orphan bot sell order geannuleerd", symbol)
                    except Exception:
                        pass

        if 0 < pos_qty <= MIN_SELLABLE_QTY:
            log.info("  %s: Dust positie (qty=%.8f), skip", symbol, pos_qty)
            continue

        if pos_qty > 0:
            existing_sell = next(
                (o for o in open_orders if o.get("side") == "sell" and o.get("type") == "limit"),
                None,
            )
            limit_sell = sell_level
            needs_new_sell = True

            if existing_sell:
                old_sell_price = float(existing_sell.get("price") or 0)
                age_hours = _order_age_hours(existing_sell)
                price_diff = abs(old_sell_price - limit_sell) / old_sell_price if old_sell_price else 1
                current_price = current_prices.get(symbol)

                if current_price and current_price < limit_sell * (1 - ORDER_STALE_PRICE_THRESHOLD):
                    try:
                        if not dry_run:
                            exchange.cancel_order(existing_sell["id"], symbol)
                        bot_orders.setdefault(symbol, {}).pop("sell", None)
                        pct = (limit_sell - current_price) / limit_sell * 100
                        tag = " [DRY RUN]" if dry_run else ""
                        log.info("  %s: Sell vervangen (prijs %.1f%% onder target)%s", symbol, pct, tag)
                        send_telegram(f"🔄 {symbol}: Sell vervangen, prijs {pct:.1f}% onder target, nieuwe @ €{limit_sell:.4f}{tag}")
                        stats["updated"] += 1
                    except Exception as e:
                        log.warning("  %s: Fout annuleren sell: %s", symbol, e)
                        needs_new_sell = False
                elif age_hours >= ORDER_MAX_AGE_HOURS:
                    try:
                        if not dry_run:
                            exchange.cancel_order(existing_sell["id"], symbol)
                        bot_orders.setdefault(symbol, {}).pop("sell", None)
                        tag = " [DRY RUN]" if dry_run else ""
                        log.info("  %s: Sell vervangen na %.0fh%s", symbol, age_hours, tag)
                        send_telegram(f"🔄 {symbol}: Sell vervangen na {age_hours:.0f}h, nieuwe @ €{limit_sell:.4f}{tag}")
                        stats["updated"] += 1
                    except Exception as e:
                        log.warning("  %s: Fout annuleren sell: %s", symbol, e)
                        needs_new_sell = False
                elif price_diff > ORDER_UPDATE_THRESHOLD:
                    try:
                        if not dry_run:
                            exchange.cancel_order(existing_sell["id"], symbol)
                        bot_orders.setdefault(symbol, {}).pop("sell", None)
                        tag = " [DRY RUN]" if dry_run else ""
                        log.info("  %s: Sell bijgewerkt (%.4f → %.4f)%s", symbol, old_sell_price, limit_sell, tag)
                        send_telegram(f"🔄 {symbol}: Sell bijgewerkt @ €{limit_sell:.4f} (was €{old_sell_price:.4f}){tag}")
                        stats["updated"] += 1
                    except Exception as e:
                        log.warning("  %s: Fout annuleren sell: %s", symbol, e)
                        needs_new_sell = False
                else:
                    log.info(
                        "  %s: Sell ongewijzigd @ €%.4f (%.1f%% diff, %.0fh oud)",
                        symbol, old_sell_price, price_diff * 100, age_hours,
                    )
                    stats["unchanged"] += 1
                    needs_new_sell = False

            if needs_new_sell:
                if existing_sell and ORDER_REPLACE_DELAY_SEC > 0:
                    time.sleep(ORDER_REPLACE_DELAY_SEC)
                free_qty = get_free_sell_qty(exchange, symbol)
                if free_qty <= MIN_SELLABLE_QTY:
                    log.warning("  %s: free qty %.8f te klein voor sell", symbol, free_qty)
                else:
                    sell_qty = _round_amount(exchange, symbol, free_qty)
                    sell_price = _round_price(exchange, symbol, limit_sell)
                    ok_sz, sz_reason = _order_size_ok(exchange, symbol, sell_qty, sell_price)
                    if not ok_sz:
                        log.warning("  %s: Sell overgeslagen: %s", symbol, sz_reason)
                        stats["skipped"] += 1
                    else:
                        try:
                            tag = " [DRY RUN]" if dry_run else ""
                            lim_params = _limit_order_params()
                            if not dry_run:
                                result = exchange.create_limit_sell_order(
                                    symbol, sell_qty, sell_price, params=lim_params
                                )
                                bot_orders.setdefault(symbol, {})["sell"] = result["id"]
                            log.info("  %s: Sell limit @ €%.4f (qty=%.6f)%s", symbol, limit_sell, sell_qty, tag)
                            if not existing_sell:
                                send_telegram(f"📊 {symbol}: Sell limit @ €{limit_sell:.4f} geplaatst{tag}")
                                stats["placed"] += 1
                        except Exception as e:
                            log.warning("  %s: Fout sell order: %s", symbol, e)
                            send_telegram(f"❌ {symbol}: Fout sell order: {e}")
        else:
            if capital_per < 10:
                log.info("  %s: Te weinig kapitaal (€%.2f, min €10), skip", symbol, capital_per)
                stats["skipped"] += 1
            else:
                existing_buy = next((o for o in open_orders if o.get("side") == "buy"), None)
                needs_new_order = True

                if existing_buy:
                    old_price = float(existing_buy.get("price") or 0)
                    age_hours = _order_age_hours(existing_buy)
                    price_diff = abs(old_price - buy_level) / old_price if old_price else 1
                    current_price = current_prices.get(symbol)

                    if current_price and current_price > old_price * (1 + ORDER_STALE_PRICE_THRESHOLD):
                        try:
                            if not dry_run:
                                exchange.cancel_order(existing_buy["id"], symbol)
                            bot_orders.setdefault(symbol, {}).pop("buy", None)
                            pct = (current_price - old_price) / old_price * 100
                            tag = " [DRY RUN]" if dry_run else ""
                            log.info("  %s: Buy vervangen (prijs %.1f%% boven order)%s", symbol, pct, tag)
                            send_telegram(f"🔄 {symbol}: Buy vervangen, prijs {pct:.1f}% boven order, nieuwe @ €{buy_level:.4f}{tag}")
                            stats["updated"] += 1
                        except Exception as e:
                            log.warning("  %s: Fout annuleren buy: %s", symbol, e)
                            needs_new_order = False
                    elif age_hours >= ORDER_MAX_AGE_HOURS:
                        try:
                            if not dry_run:
                                exchange.cancel_order(existing_buy["id"], symbol)
                            bot_orders.setdefault(symbol, {}).pop("buy", None)
                            tag = " [DRY RUN]" if dry_run else ""
                            log.info("  %s: Buy vervangen na %.0fh%s", symbol, age_hours, tag)
                            send_telegram(f"🔄 {symbol}: Buy vervangen na {age_hours:.0f}h, nieuwe @ €{buy_level:.4f}{tag}")
                            stats["updated"] += 1
                        except Exception as e:
                            log.warning("  %s: Fout annuleren buy: %s", symbol, e)
                            needs_new_order = False
                    elif price_diff > ORDER_UPDATE_THRESHOLD:
                        try:
                            if not dry_run:
                                exchange.cancel_order(existing_buy["id"], symbol)
                            bot_orders.setdefault(symbol, {}).pop("buy", None)
                            tag = " [DRY RUN]" if dry_run else ""
                            log.info("  %s: Buy bijgewerkt (%.4f → %.4f)%s", symbol, old_price, buy_level, tag)
                            send_telegram(f"🔄 {symbol}: Buy bijgewerkt @ €{buy_level:.4f} (was €{old_price:.4f}){tag}")
                            stats["updated"] += 1
                        except Exception as e:
                            log.warning("  %s: Fout annuleren buy: %s", symbol, e)
                            needs_new_order = False
                    else:
                        log.info(
                            "  %s: Buy ongewijzigd @ €%.4f (%.1f%% diff, %.0fh oud)",
                            symbol, old_price, price_diff * 100, age_hours,
                        )
                        stats["unchanged"] += 1
                        needs_new_order = False

                if needs_new_order:
                    if existing_buy and ORDER_REPLACE_DELAY_SEC > 0:
                        time.sleep(ORDER_REPLACE_DELAY_SEC)

                    # Eerst actueel vrij EUR opvragen, dan pas ordergrootte (geen vaste som per asset die het saldo overschrijdt).
                    free_now = get_balance(exchange)
                    order_eur = min(
                        capital_per, max(0.0, free_now * 0.992)
                    )
                    try:
                        m = exchange.market(symbol)
                        cost_min = (m.get("limits") or {}).get("cost") or {}
                        min_eur = float(cost_min.get("min") or 5.0)
                    except Exception:
                        min_eur = 5.0

                    if order_eur < min_eur:
                        log.warning(
                            "  %s: Buy overgeslagen: vrij €%.2f (doel €%.2f), onder minimum order €%.2f",
                            symbol,
                            free_now,
                            capital_per,
                            min_eur,
                        )
                        stats["skipped"] += 1
                    else:
                        if order_eur < capital_per * 0.999:
                            log.info(
                                "  %s: Buy met verlaagd bedrag €%.2f i.p.v. €%.2f "
                                "(vrij EUR gedeeld over assets)",
                                symbol,
                                order_eur,
                                capital_per,
                            )
                        qty = order_eur / buy_level
                        buy_qty = _round_amount(exchange, symbol, qty)
                        buy_price = _round_price(exchange, symbol, buy_level)
                        ok_sz, sz_reason = _order_size_ok(exchange, symbol, buy_qty, buy_price)
                        if not ok_sz:
                            log.warning("  %s: Buy overgeslagen: %s", symbol, sz_reason)
                            stats["skipped"] += 1
                        else:
                            try:
                                tag = " [DRY RUN]" if dry_run else ""
                                lim_params = _limit_order_params()
                                if not dry_run:
                                    result = exchange.create_limit_buy_order(
                                        symbol, buy_qty, buy_price, params=lim_params
                                    )
                                    bot_orders.setdefault(symbol, {})["buy"] = result["id"]
                                log.info(
                                    "  %s: Limit buy @ €%.4f (€%.2f notional)%s",
                                    symbol,
                                    buy_level,
                                    order_eur,
                                    tag,
                                )
                                if not existing_buy:
                                    send_telegram(
                                        f"📊 {symbol}: Limit buy @ €{buy_level:.4f} "
                                        f"(€{order_eur:.0f}) geplaatst{tag}"
                                    )
                                    stats["placed"] += 1
                            except Exception as e:
                                log.warning("  %s: Fout buy order: %s", symbol, e)
                                send_telegram(f"❌ {symbol}: Fout buy order: {e}")

    _save_state(entries=state_entries, bot_orders=bot_orders)

    trade_status = f"{new_trades} nieuwe trade(s) gevuld" if new_trades else "Geen nieuwe trades gevuld"
    summary = (
        f"Run: {stats['placed']} geplaatst, {stats['updated']} bijgewerkt, "
        f"{stats['unchanged']} ongewijzigd, {stats['skipped']} overgeslagen | {trade_status}"
    )
    if symbols:
        summary += f"\nActief: {', '.join(symbols)}"
    log.info(summary)
    send_telegram(f"📋 {summary}")
    return stats


def main():
    log.info("=" * 50)
    log.info("Bitvavo Range Trader")
    log.info("=" * 50)
    log.info("Pool: %s (top %d actief)", ", ".join(SYMBOL_POOL), SYMBOLS_ACTIVE)
    log.info("Max kapitaal: €%.0f", MAX_CAPITAL_EUR)
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
