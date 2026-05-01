#!/usr/bin/env python3
"""
Live paper trading bot - range strategie voor AVAX, UNI, AAVE.
Draait 1x per dag of via cron. Plaatst limit buy/sell en stop-loss orders.

Alpaca-clients, posities, order placement en fill-journal zitten in
`bot_live.alpaca_runtime` (gedeeld met `bot_hybrid.hybrid_trader`).
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

from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from bot_live.config import (
    SYMBOL_POOL,
    SYMBOLS_ACTIVE,
    CAPITAL_PER_ASSET,
    LEVELS_LOOKBACK_DAYS,
    BUY_ABOVE_LOW_PCT,
    SELL_BELOW_HIGH_PCT,
    ALPACA_CRYPTO_MIN_ORDER_REF_USD,
    ALPACA_CRYPTO_ROUND_TRIP_FIXED_USD,
    ALPACA_CRYPTO_ESTIMATED_MAKER_ROUND_TRIP_PCT,
    required_min_spread_fraction_crypto_usd,
    STOP_LOSS_PER_UNIT,
    ORDER_UPDATE_THRESHOLD,
    ORDER_MAX_AGE_HOURS,
    ORDER_STALE_PRICE_THRESHOLD,
    ALPACA_CRYPTO_SINGLE_EXIT_ORDER,
    ORDER_REPLACE_DELAY_SEC,
)
from bot_live.telegram import send_telegram, notify_trade
from bot_live.alpaca_runtime import (
    get_trading_clients,
    get_current_prices,
    get_positions,
    get_open_orders,
    get_buying_power,
    get_portfolio_value,
    _find_position,
    _round_price,
    _sell_qty_decimal_from_position,
    _submit_crypto_sell,
    _check_and_notify_filled_orders,
    _save_state,
    MIN_SELLABLE_CRYPTO_QTY,
)
from bot_live.run_audit import ALPACA_RUNS_JSONL, log_run_audit


def get_24h_levels(
    data_client, symbols: list[str], min_spread_frac: float
) -> dict[str, tuple[float, float]]:
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
        if sell_level >= buy_level * (1 + min_spread_frac):
            result[symbol] = (buy_level, sell_level)
    return result


def _get_levels_and_scores(
    data_client, symbols: list[str], min_spread_frac: float
) -> dict[str, tuple[float, float, float]]:
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
        spread_ok = sell_level >= buy_level * (1 + min_spread_frac)
        spread_pct = (sell_level - buy_level) / buy_level if spread_ok else 0
        range_pct = (high - low) / low if low else 0
        score = spread_pct * (1 + range_pct)
        result[symbol] = (buy_level, sell_level, score)
    return result


def select_top_symbols(
    data_client,
    trading_client,
    pool: list[str],
    n: int,
    ref_notional_usd: float,
) -> tuple[list[str], dict[str, tuple[float, float]]]:
    """
    Selecteer top N meest winstgevende symbolen uit pool.
    Symbolen met open posities blijven altijd actief.
    Retourneert (symbols, levels).
    """
    min_spread_frac = required_min_spread_fraction_crypto_usd(ref_notional_usd)
    levels_scored = _get_levels_and_scores(data_client, pool, min_spread_frac)
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
        fallback = get_24h_levels(data_client, missing, min_spread_frac)
        levels.update(fallback)
    return selected, levels


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


def run_once():
    """Eén run van de trading bot."""
    trading_client, data_client = get_trading_clients()

    buying_power_pre = get_buying_power(trading_client)
    cap_target = (buying_power_pre / SYMBOLS_ACTIVE) * 0.995
    est_order_usd = min(cap_target, max(0.0, buying_power_pre * 0.99))
    ref_usd = max(ALPACA_CRYPTO_MIN_ORDER_REF_USD, est_order_usd) if est_order_usd > 0 else cap_target

    # Selecteer top N meest winstgevende symbolen uit pool
    symbols, levels = select_top_symbols(
        data_client, trading_client, SYMBOL_POOL, SYMBOLS_ACTIVE, ref_usd
    )
    if not symbols:
        log.warning("Geen symbolen geselecteerd uit pool")
        send_telegram("⚠️ Geen symbolen geselecteerd uit pool")
        log_run_audit(
            {
                "bot": "alpaca_range",
                "paper": os.environ.get("ALPACA_PAPER_TRADE", "True"),
                "event": "no_symbols_selected",
            },
            filename=ALPACA_RUNS_JSONL,
        )
        return {}

    new_trades = _check_and_notify_filled_orders(trading_client, SYMBOL_POOL)

    current_prices = get_current_prices(data_client, symbols)
    positions = get_positions(trading_client, symbols=symbols)
    buying_power = get_buying_power(trading_client)

    capital_per = buying_power / len(symbols)

    stats = {"placed": 0, "updated": 0, "unchanged": 0, "skipped": 0}

    log.info("Geselecteerd: %s", ", ".join(symbols))
    log.info(
        "Spread-drempel: ref-notional $%.2f → min. spread %.2f%% (incl. vast $%.2f round-trip + maker-%%)",
        ref_usd,
        required_min_spread_fraction_crypto_usd(ref_usd) * 100,
        ALPACA_CRYPTO_ROUND_TRIP_FIXED_USD,
    )
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
                    spread_frac = (
                        (sell_level - buy_level) / buy_level if buy_level > 0 else 0
                    )
                    gross_usd_est = capital_per * spread_frac
                    fee_usd_est = (
                        ALPACA_CRYPTO_ROUND_TRIP_FIXED_USD
                        + capital_per * ALPACA_CRYPTO_ESTIMATED_MAKER_ROUND_TRIP_PCT
                    )
                    if gross_usd_est < fee_usd_est:
                        log.warning(
                            "  %s: Buy overgeslagen: geschatte bruto $%.2f < fees $%.2f "
                            "(levels vs order $%.2f)",
                            symbol,
                            gross_usd_est,
                            fee_usd_est,
                            capital_per,
                        )
                        stats["skipped"] += 1
                        continue
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

    positions_final = get_positions(trading_client, symbols=symbols)
    portfolio_usd = get_portfolio_value(trading_client)
    buying_final = get_buying_power(trading_client)
    levels_snap = {
        s: [round(float(levels[s][0]), 8), round(float(levels[s][1]), 8)]
        for s in symbols
        if s in levels
    }
    pos_snap = {
        s: {
            "qty": round(float(q), 8),
            "avg_entry": round(float(e), 8),
        }
        for s, (q, e) in positions_final.items()
    }
    log_run_audit(
        {
            "bot": "alpaca_range",
            "paper": os.environ.get("ALPACA_PAPER_TRADE", "True"),
            "fills_new_this_run": new_trades,
            "symbols": list(symbols),
            "levels": levels_snap,
            "mid_prices": {k: round(float(v), 8) for k, v in current_prices.items()},
            "positions": pos_snap,
            "stats": dict(stats),
            "ref_notional_usd": round(float(ref_usd), 4),
            "buying_power_usd": round(buying_final, 4),
            "capital_per_usd": round(float(capital_per), 4),
            "portfolio_value_usd": round(portfolio_usd, 2),
            "summary_text": summary,
        },
        filename=ALPACA_RUNS_JSONL,
    )

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
