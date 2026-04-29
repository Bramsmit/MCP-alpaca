#!/usr/bin/env python3
"""
Hybrid regime-aware trader.

Pipeline per run:
    1. Fetch hourly bars voor de pool.
    2. Detecteer regime per symbool (ADX + EMA-richting + hysteresis).
    3. Route naar range_strategy / trend_strategy / hold.
    4. Voer StrategySignal uit via Alpaca (of log-only in DRY_RUN).
    5. Persist per-symbol regime + highest-close-since-entry in
       `.alpaca_hybrid_state.json`.

Dit bestand vervangt de range-bot niet. Alpaca-order/positie-hulp komt uit
`bot_live.alpaca_runtime` (gedeeld met `bot_range_1000.live_trader`).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

import pandas as pd
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import LimitOrderRequest

from bot_live.config import (
    SYMBOL_POOL,
    SYMBOLS_ACTIVE,
    CAPITAL_PER_ASSET,
    HYBRID_ENABLED,
    ADX_PERIOD,
    HYBRID_ADX_TREND_THRESHOLD,
    HYBRID_ADX_RANGE_THRESHOLD,
    HYBRID_REGIME_CONFIRMATION_BARS,
    HYBRID_RANGE_LOOKBACK_HOURS,
    EMA_FAST,
    EMA_SLOW,
    RANGE_LOOKBACK_HOURS,
    ORDER_UPDATE_THRESHOLD,
    ORDER_REPLACE_DELAY_SEC,
    ALPACA_CRYPTO_SINGLE_EXIT_ORDER,
    DRY_RUN,
)
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
    MIN_SELLABLE_CRYPTO_QTY,
)
from bot_hybrid.market_regime_detector import (
    RegimeSnapshot,
    detect_regime,
    get_prev_regime,
)
from bot_hybrid.strategy_base import StrategyContext, StrategySignal
from bot_live.hybrid_signals import pick_hybrid_signal
from bot_live.telegram import send_telegram


# ---------------------------------------------------------------------------
# State (regime per symbool + highest close sinds entry voor trailing stop)
# ---------------------------------------------------------------------------


def _hybrid_state_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".alpaca_hybrid_state.json"


def _load_hybrid_state() -> dict:
    path = _hybrid_state_path()
    if not path.exists():
        return {"regimes": {}, "trend_trades": {}}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {"regimes": {}, "trend_trades": {}}
        data.setdefault("regimes", {})
        data.setdefault("trend_trades", {})
        return data
    except Exception:
        return {"regimes": {}, "trend_trades": {}}


def _save_hybrid_state(
    *,
    regimes: dict[str, RegimeSnapshot] | None = None,
    trend_trades: dict[str, dict] | None = None,
) -> None:
    path = _hybrid_state_path()
    state = _load_hybrid_state()
    if regimes is not None:
        state["regimes"] = {s: asdict(snap) for s, snap in regimes.items()}
    if trend_trades is not None:
        state["trend_trades"] = trend_trades
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Data fetching (hourly)
# ---------------------------------------------------------------------------


def fetch_hourly_bars(data_client, symbols: list[str], bars_needed: int) -> dict[str, pd.DataFrame]:
    """Haal de laatste N hourly bars op per symbol."""
    end = datetime.now(timezone.utc)
    # Extra buffer zodat we ruim genoeg bars hebben ook bij downtime van Alpaca.
    start = end - timedelta(hours=bars_needed + 48)
    request = CryptoBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Hour,
        start=start,
        end=end,
    )
    bars = data_client.get_crypto_bars(request)
    result: dict[str, pd.DataFrame] = {}
    if bars.df is None or bars.df.empty:
        return result
    for symbol in symbols:
        if symbol not in bars.df.index.get_level_values(0):
            continue
        df = bars.df.loc[symbol].copy()
        df = df[["open", "high", "low", "close", "volume"]].sort_index()
        result[symbol] = df
    return result


# ---------------------------------------------------------------------------
# Signal execution
# ---------------------------------------------------------------------------


def _cancel_orders(trading_client, orders: list, symbol: str, note: str) -> None:
    for o in orders:
        try:
            trading_client.cancel_order_by_id(o.id)
            log.info("  %s: %s order %s geannuleerd (%s)", symbol, o.side, str(o.id)[:8], note)
        except Exception as e:
            log.warning("  %s: kon order %s niet annuleren: %s", symbol, o.id, e)


def _submit_limit_buy(trading_client, symbol: str, qty: float, limit_price: float) -> None:
    trading_client.submit_order(
        LimitOrderRequest(
            symbol=symbol,
            qty=round(qty, 6),
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.GTC,
            limit_price=_round_price(limit_price),
        )
    )


def _execute_signal(
    trading_client,
    symbol: str,
    signal: StrategySignal,
    ctx: StrategyContext,
    open_orders: list,
    current_price: float,
) -> str:
    """Voer StrategySignal uit via Alpaca. Retourneert menselijke status-string."""
    if signal.action in ("hold", "skip"):
        return f"no-op: {signal.reason}"

    if DRY_RUN:
        return f"DRY_RUN | {signal.as_log_line()}"

    if signal.action == "enter_long":
        if ctx.has_position:
            return "enter_long geskipt: positie bestaat al"
        if signal.entry_price is None or signal.qty is None or signal.qty <= 0:
            return "enter_long geskipt: ongeldige entry/qty"

        existing_buy = next((o for o in open_orders if o.side == OrderSide.BUY), None)
        if existing_buy:
            old_price = float(existing_buy.limit_price or 0)
            if old_price > 0 and abs(old_price - signal.entry_price) / old_price <= ORDER_UPDATE_THRESHOLD:
                return f"buy order ongewijzigd @ ${old_price:.4f}"
            _cancel_orders(trading_client, [existing_buy], symbol, "replace (hybrid)")
            if ORDER_REPLACE_DELAY_SEC > 0:
                time.sleep(ORDER_REPLACE_DELAY_SEC)

        _submit_limit_buy(trading_client, symbol, signal.qty, signal.entry_price)
        return f"limit buy @ ${signal.entry_price:.4f} qty={signal.qty:.6f}"

    if signal.action == "update_exit":
        if not ctx.has_position:
            # Geen positie: verwijder eventuele orphan sell orders
            orphan_sells = [o for o in open_orders if o.side == OrderSide.SELL]
            if orphan_sells:
                _cancel_orders(trading_client, orphan_sells, symbol, "orphan sell")
            return "geen positie; orphan sells opgeruimd"
        if signal.exit_price is None:
            return "update_exit geskipt: exit_price ontbreekt"

        pos_live = _find_position(trading_client, symbol)
        d_live = _sell_qty_decimal_from_position(pos_live)
        if pos_live is None or d_live <= 0 or d_live < MIN_SELLABLE_CRYPTO_QTY:
            return f"te weinig qty voor sell (d={d_live})"

        existing_sell = next(
            (o for o in open_orders if o.side == OrderSide.SELL and o.order_type == OrderType.LIMIT),
            None,
        )
        if existing_sell:
            old_price = float(existing_sell.limit_price or 0)
            if old_price > 0 and abs(old_price - signal.exit_price) / old_price <= ORDER_UPDATE_THRESHOLD:
                return f"sell order ongewijzigd @ ${old_price:.4f}"
            _cancel_orders(trading_client, [existing_sell], symbol, "replace (hybrid)")
            if ORDER_REPLACE_DELAY_SEC > 0:
                time.sleep(ORDER_REPLACE_DELAY_SEC)
            pos_live = _find_position(trading_client, symbol)
            if pos_live is None:
                return "positie verdwenen na cancel"

        assert ALPACA_CRYPTO_SINGLE_EXIT_ORDER, "Alpaca crypto: max 1 exit order per positie"
        _submit_crypto_sell(trading_client, symbol, pos_live, signal.exit_price)
        return f"limit sell @ ${signal.exit_price:.4f}"

    if signal.action == "exit_now":
        if not ctx.has_position:
            return "exit_now geskipt: geen positie"
        # Cancel bestaande sells, plaats dan een agressieve limit-sell net onder bid.
        sells = [o for o in open_orders if o.side == OrderSide.SELL]
        if sells:
            _cancel_orders(trading_client, sells, symbol, "exit_now")
            if ORDER_REPLACE_DELAY_SEC > 0:
                time.sleep(ORDER_REPLACE_DELAY_SEC)
        pos_live = _find_position(trading_client, symbol)
        d_live = _sell_qty_decimal_from_position(pos_live)
        if pos_live is None or d_live <= 0 or d_live < MIN_SELLABLE_CRYPTO_QTY:
            return "exit_now geskipt: geen positie/qty"
        aggressive = (signal.exit_price or current_price) * 0.999
        _submit_crypto_sell(trading_client, symbol, pos_live, aggressive)
        return f"exit limit sell @ ${aggressive:.4f}"

    return f"onbekende action: {signal.action}"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _log_regime_line(symbol: str, snap: RegimeSnapshot, strategy: str, exec_status: str) -> None:
    log.info(
        "%s | regime=%s (adx=%.1f, ema%s=%.4f %s ema%s=%.4f) | strategy=%s | %s",
        symbol,
        snap.regime,
        snap.adx,
        EMA_FAST,
        snap.ema_fast,
        ">" if snap.ema_fast > snap.ema_slow else "<",
        EMA_SLOW,
        snap.ema_slow,
        strategy,
        exec_status,
    )


def run_once() -> dict:
    """Eén run van de hybride bot."""
    if not HYBRID_ENABLED:
        log.info("HYBRID_ENABLED=False -> hybrid bot niet actief (zet in bot_live/config.py)")
        return {"skipped": "hybrid_disabled"}

    trading_client, data_client = get_trading_clients()

    # Check filled orders van vorige run (journal + Telegram)
    new_trades = _check_and_notify_filled_orders(trading_client, SYMBOL_POOL)

    bars_needed = max(ADX_PERIOD * 4, EMA_SLOW * 3, RANGE_LOOKBACK_HOURS, HYBRID_RANGE_LOOKBACK_HOURS) + 24
    bars = fetch_hourly_bars(data_client, SYMBOL_POOL, bars_needed)
    if not bars:
        log.warning("Geen hourly bars ontvangen")
        send_telegram("⚠️ Hybrid: geen hourly bars")
        return {"skipped": "no_bars"}

    # Selecteer top N symbolen: alle symbolen met posities + aanvullen uit pool
    positions = get_positions(trading_client, symbols=SYMBOL_POOL)
    selected = list(positions.keys())
    for sym in SYMBOL_POOL:
        if sym in selected:
            continue
        if sym in bars and len(bars[sym]) >= EMA_SLOW * 2:
            selected.append(sym)
        if len(selected) >= SYMBOLS_ACTIVE:
            break
    if not selected:
        log.warning("Geen geldige symbolen uit pool")
        return {"skipped": "no_symbols"}

    current_prices = get_current_prices(data_client, selected)
    buying_power = get_buying_power(trading_client)
    equity = get_portfolio_value(trading_client)
    capital_per = min(CAPITAL_PER_ASSET, buying_power / max(len(selected), 1))

    state = _load_hybrid_state()
    prev_regimes = state.get("regimes", {})
    trend_trades: dict[str, dict] = state.get("trend_trades", {})

    log.info("Hybrid run | equity=$%.2f | buying_power=$%.2f | per_asset=$%.2f",
             equity, buying_power, capital_per)
    log.info("Selected: %s", ", ".join(selected))
    log.info("Filled orders sinds vorige run: %d", new_trades)
    log.info("")

    new_regimes: dict[str, RegimeSnapshot] = {}
    stats = {"enter": 0, "update": 0, "exit": 0, "hold": 0, "skip": 0}

    for symbol in selected:
        df = bars.get(symbol)
        if df is None or df.empty:
            log.info("%s | geen bars, skip", symbol)
            stats["skip"] += 1
            continue

        prev_regime = get_prev_regime(prev_regimes, symbol)
        snap = detect_regime(
            df,
            prev_regime=prev_regime,
            adx_period=ADX_PERIOD,
            trend_threshold=HYBRID_ADX_TREND_THRESHOLD,
            range_threshold=HYBRID_ADX_RANGE_THRESHOLD,
            confirmation_bars=HYBRID_REGIME_CONFIRMATION_BARS,
            ema_fast_period=EMA_FAST,
            ema_slow_period=EMA_SLOW,
        )
        new_regimes[symbol] = snap

        pos_qty, avg_entry = positions.get(symbol, (0.0, 0.0))
        has_position = pos_qty > 0 and Decimal(str(pos_qty)) >= MIN_SELLABLE_CRYPTO_QTY
        price = current_prices.get(symbol, float(df["close"].iloc[-1]))

        # Bijhouden: hoogste close sinds entry (voor trailing stop in trend strategy)
        trade_state = trend_trades.get(symbol, {})
        highest_close = float(trade_state.get("highest_close", 0.0))
        if has_position:
            highest_close = max(highest_close, avg_entry or 0.0, price, float(df["close"].iloc[-1]))
        else:
            highest_close = 0.0  # reset als geen positie
        trend_trades[symbol] = {
            "highest_close": highest_close,
            "entry_price": avg_entry if has_position else 0.0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        ctx = StrategyContext(
            symbol=symbol,
            current_price=price,
            equity=equity,
            capital_cap=capital_per,
            has_position=has_position,
            position_qty=pos_qty,
            avg_entry_price=avg_entry,
            highest_close_since_entry=highest_close,
        )

        signal, strategy_label = pick_hybrid_signal(df, ctx, snap)

        # Execute
        open_orders = get_open_orders(trading_client, symbol)
        try:
            status = _execute_signal(trading_client, symbol, signal, ctx, open_orders, price)
        except Exception as e:
            status = f"ERROR: {e}"
            log.warning("  %s: executie-fout: %s", symbol, e)

        _log_regime_line(symbol, snap, strategy_label, f"{signal.as_log_line()} | exec={status}")

        if signal.action == "enter_long":
            stats["enter"] += 1
        elif signal.action == "update_exit":
            stats["update"] += 1
        elif signal.action == "exit_now":
            stats["exit"] += 1
        elif signal.action == "hold":
            stats["hold"] += 1
        else:
            stats["skip"] += 1

    _save_hybrid_state(regimes=new_regimes, trend_trades=trend_trades)

    regime_map = ", ".join(f"{s}={snap.regime}" for s, snap in new_regimes.items())
    summary = (
        f"Hybrid run: enter={stats['enter']} update={stats['update']} "
        f"exit={stats['exit']} hold={stats['hold']} skip={stats['skip']}"
    )
    if regime_map:
        summary += f"\nRegimes: {regime_map}"
    if new_trades:
        summary += f"\nNieuwe fills: {new_trades}"
    if DRY_RUN:
        summary = "[DRY_RUN] " + summary

    log.info("")
    log.info(summary)
    send_telegram(f"📊 {summary}")
    return stats


def main() -> None:
    log.info("=" * 60)
    log.info("MCP-Alpaca Hybrid Regime-Aware Trader")
    log.info("=" * 60)
    log.info("Pool: %s (top %d actief)", ", ".join(SYMBOL_POOL), SYMBOLS_ACTIVE)
    log.info("DRY_RUN=%s | HYBRID_ENABLED=%s", DRY_RUN, HYBRID_ENABLED)
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
                send_telegram(f"❌ Hybrid bot fout: {e}")
                raise


if __name__ == "__main__":
    main()
