#!/usr/bin/env python3
"""
Live paper trading bot - range strategie voor AVAX, UNI, AAVE.
Draait 1x per dag of via cron. Plaatst limit buy/sell en stop-loss orders.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

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
from alpaca.trading.requests import LimitOrderRequest, StopLimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce, QueryOrderStatus
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from bot.config import (
    SYMBOLS,
    CAPITAL_PER_ASSET,
    BUY_ABOVE_LOW_PCT,
    SELL_BELOW_HIGH_PCT,
    MIN_SPREAD_PCT,
    STOP_LOSS_PER_UNIT,
    ORDER_UPDATE_THRESHOLD,
    ORDER_MAX_AGE_HOURS,
)
from bot.telegram import send_telegram, notify_trade


def get_trading_clients():
    """Maak Alpaca clients (paper trading)."""
    api_key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret:
        raise ValueError("ALPACA_API_KEY en ALPACA_SECRET_KEY vereist in .env")
    return (
        TradingClient(api_key, secret, paper=True),
        CryptoHistoricalDataClient(api_key, secret),
    )


def get_24h_levels(data_client, symbols: list[str]) -> dict[str, tuple[float, float]]:
    """Haal vorige dag high/low op voor buy/sell niveaus."""
    end = datetime.utcnow()
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
        df = bars.df.loc[symbol].tail(3)
        if len(df) < 2:
            continue
        prev = df.iloc[-2]
        high, low = prev["high"], prev["low"]
        buy_level = low * (1 + BUY_ABOVE_LOW_PCT)
        sell_level = high * (1 - SELL_BELOW_HIGH_PCT)
        if sell_level >= buy_level * (1 + MIN_SPREAD_PCT):
            result[symbol] = (buy_level, sell_level)
    return result


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


def get_positions(trading_client) -> dict[str, tuple[float, float]]:
    """Posities per symbol: {symbol: (qty, avg_entry_price)}."""
    positions = trading_client.get_all_positions()
    out = {}
    for p in positions:
        sym = _norm_symbol(p.symbol)
        if sym in SYMBOLS:
            out[sym] = (float(p.qty), float(p.avg_entry_price or 0))
    return out


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


def run_once():
    """Eén run van de trading bot."""
    trading_client, data_client = get_trading_clients()

    levels = get_24h_levels(data_client, SYMBOLS)
    positions = get_positions(trading_client)
    buying_power = get_buying_power(trading_client)

    # Cash per asset: 1/3 van totaal
    capital_per = min(CAPITAL_PER_ASSET, buying_power / 3)

    print(f"Buying power: ${buying_power:.2f} | Per asset: ${capital_per:.2f}")
    print(f"Levels: {levels}")
    print(f"Positions: {positions}")
    print()

    for symbol in SYMBOLS:
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
                        print(f"  {symbol}: Orphan sell order geannuleerd")
                    except Exception:
                        pass

        if pos_qty > 0:
            # We hebben positie: zorg voor sell + stop-loss, update als prijs bewogen is
            existing_sell = next((o for o in open_orders if o.side == OrderSide.SELL and o.order_type == OrderType.LIMIT), None)
            existing_stop = next((o for o in open_orders if o.side == OrderSide.SELL and o.order_type == OrderType.STOP_LIMIT), None)
            entry = avg_entry if avg_entry > 0 else buy_level
            stop_price = entry - STOP_LOSS_PER_UNIT
            limit_sell = sell_level
            qty = pos_qty

            needs_new_sell = True

            if existing_sell:
                old_sell_price = float(existing_sell.limit_price)
                age_hours = _order_age_hours(existing_sell)
                price_diff = abs(old_sell_price - limit_sell) / old_sell_price

                if age_hours >= ORDER_MAX_AGE_HOURS:
                    try:
                        trading_client.cancel_order_by_id(existing_sell.id)
                        if existing_stop:
                            trading_client.cancel_order_by_id(existing_stop.id)
                        print(f"  {symbol}: Sell order vervangen na {age_hours:.0f}h (verse 24h window)")
                        send_telegram(f"🔄 {symbol}: Sell order vervangen na {age_hours:.0f}h, nieuwe levels @ ${limit_sell:.4f}")
                    except Exception as e:
                        print(f"  {symbol}: Fout bij annuleren sell order: {e}")
                        needs_new_sell = False
                elif price_diff > ORDER_UPDATE_THRESHOLD:
                    try:
                        trading_client.cancel_order_by_id(existing_sell.id)
                        if existing_stop:
                            trading_client.cancel_order_by_id(existing_stop.id)
                        print(f"  {symbol}: Sell order bijgewerkt ({old_sell_price:.4f} -> {limit_sell:.4f}, {price_diff*100:.1f}% verschil)")
                        send_telegram(f"🔄 {symbol}: Sell order bijgewerkt @ ${limit_sell:.4f} (was ${old_sell_price:.4f})")
                    except Exception as e:
                        print(f"  {symbol}: Fout bij annuleren sell order: {e}")
                        needs_new_sell = False
                else:
                    print(f"  {symbol}: Sell order ongewijzigd @ ${old_sell_price:.4f} ({price_diff*100:.1f}% verschil, {age_hours:.0f}h oud)")
                    needs_new_sell = False

            if needs_new_sell:
                try:
                    trading_client.submit_order(
                        LimitOrderRequest(
                            symbol=symbol,
                            qty=qty,
                            side=OrderSide.SELL,
                            type=OrderType.LIMIT,
                            time_in_force=TimeInForce.GTC,
                            limit_price=_round_price(limit_sell),
                        )
                    )
                    trading_client.submit_order(
                        StopLimitOrderRequest(
                            symbol=symbol,
                            qty=qty,
                            side=OrderSide.SELL,
                            type=OrderType.STOP_LIMIT,
                            time_in_force=TimeInForce.GTC,
                            stop_price=_round_price(stop_price),
                            limit_price=_round_price(stop_price),
                        )
                    )
                    print(f"  {symbol}: Sell limit @ ${limit_sell:.4f} + stop @ ${stop_price:.4f}")
                    if not existing_sell:
                        send_telegram(f"📊 {symbol}: Sell limit @ ${limit_sell:.4f} + stop @ ${stop_price:.4f} geplaatst")
                except Exception as e:
                    print(f"  {symbol}: Fout: {e}")
                    send_telegram(f"❌ {symbol}: Fout orders: {e}")
        else:
            # Geen positie: plaats of update limit buy order
            if capital_per <= 1:
                print(f"  {symbol}: Te weinig kapitaal (${capital_per:.2f}), skip")
            elif buy_level < 0.0001:
                # Alpaca: "limit price must be > 0" voor zeer lage prijzen (SHIB ~5e-6, PEPE)
                print(f"  {symbol}: Prijs ${float(buy_level):.8f} te laag - Alpaca API accepteert dit niet")
                send_telegram(f"⚠️ {symbol}: Overgeslagen (prijs te laag voor Alpaca limit orders)")
            else:
                existing_buy = next((o for o in open_orders if o.side == OrderSide.BUY), None)
                needs_new_order = True

                if existing_buy:
                    old_price = float(existing_buy.limit_price)
                    age_hours = _order_age_hours(existing_buy)
                    price_diff = abs(old_price - buy_level) / old_price

                    if age_hours >= ORDER_MAX_AGE_HOURS:
                        try:
                            trading_client.cancel_order_by_id(existing_buy.id)
                            print(f"  {symbol}: Buy order vervangen na {age_hours:.0f}h (verse 24h window)")
                            send_telegram(f"🔄 {symbol}: Buy order vervangen na {age_hours:.0f}h, nieuwe levels @ ${buy_level:.4f}")
                        except Exception as e:
                            print(f"  {symbol}: Fout bij annuleren buy order: {e}")
                            needs_new_order = False
                    elif price_diff > ORDER_UPDATE_THRESHOLD:
                        try:
                            trading_client.cancel_order_by_id(existing_buy.id)
                            print(f"  {symbol}: Buy order bijgewerkt ({old_price:.4f} -> {buy_level:.4f}, {price_diff*100:.1f}% verschil)")
                            send_telegram(f"🔄 {symbol}: Buy order bijgewerkt @ ${buy_level:.4f} (was ${old_price:.4f})")
                        except Exception as e:
                            print(f"  {symbol}: Fout bij annuleren buy order: {e}")
                            needs_new_order = False
                    else:
                        print(f"  {symbol}: Buy order ongewijzigd @ ${old_price:.4f} ({price_diff*100:.1f}% verschil, {age_hours:.0f}h oud)")
                        needs_new_order = False

                if needs_new_order:
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
                        print(f"  {symbol}: Limit buy @ {price_str} (${capital_per:.0f})")
                        if not existing_buy:
                            send_telegram(f"📊 {symbol}: Limit buy @ ${buy_level:.4f} (${capital_per:.0f}) geplaatst")
                    except Exception as e:
                        print(f"  {symbol}: Fout buy: {e}")
                        send_telegram(f"❌ {symbol}: Fout buy order: {e}")


def main():
    print("=" * 50)
    print("MCP-Alpaca Live Paper Trader")
    print("=" * 50)
    print(f"Assets: {', '.join(SYMBOLS)}")
    print(f"Run op: {datetime.now().isoformat()}")
    print()
    try:
        run_once()
        print("Klaar.")
    except Exception as e:
        print(f"Fout: {e}")
        send_telegram(f"❌ Bot fout: {e}")
        raise


if __name__ == "__main__":
    main()
