#!/usr/bin/env python3
"""
Status/diagnose: toon waarom de bot wel/niet trade.
- Huidige prijzen vs buy/sell levels
- Open orders
- Posities (crypto holdings)
- Afstand tot fill
"""

import os
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

from alpaca.trading.enums import OrderSide

from bot_live.alpaca_runtime import (
    get_trading_clients,
    get_current_prices,
    get_positions,
    get_open_orders,
    get_portfolio_value,
    get_buying_power,
)
from bot_range_1000.live_trader import select_top_symbols
from bot_live.config import (
    SYMBOL_POOL,
    ALPACA_RANGE_SYMBOLS_ACTIVE,
    ALPACA_CRYPTO_MIN_ORDER_REF_USD,
)


def main():
    print("=" * 60)
    print("Alpaca Range Bot — Status / Diagnose")
    print("=" * 60)

    trading_client, data_client = get_trading_clients()
    cash_pre = get_buying_power(trading_client)
    cap_target = (cash_pre / ALPACA_RANGE_SYMBOLS_ACTIVE) * 0.995
    est_order_usd = min(cap_target, max(0.0, cash_pre * 0.99))
    ref_usd = max(ALPACA_CRYPTO_MIN_ORDER_REF_USD, est_order_usd) if est_order_usd > 0 else cap_target

    symbols, levels = select_top_symbols(
        data_client, trading_client, SYMBOL_POOL, ALPACA_RANGE_SYMBOLS_ACTIVE, ref_usd
    )

    if not symbols:
        print("Geen symbolen geselecteerd uit pool")
        return

    print(f"\nGeselecteerd: {', '.join(symbols)}")
    cash = get_buying_power(trading_client)
    portfolio_value = get_portfolio_value(trading_client)
    positions = get_positions(trading_client, symbols=symbols)

    print(f"Cash:              ${cash:.2f}")
    print(f"Portfolio (equity): ${portfolio_value:.2f}")
    print(f"Posities: {positions or 'Geen'}")
    print()

    current_prices = get_current_prices(data_client, symbols)

    print("Prijs vs buy/sell levels:")
    print("-" * 60)
    for sym in symbols:
        if sym not in levels or sym not in current_prices:
            continue
        buy_level, sell_level = levels[sym]
        price = current_prices[sym]
        pct_to_buy = (price - buy_level) / buy_level * 100
        pos_qty, _ = positions.get(sym, (0.0, 0.0))
        status = (
            f"HAS POSITION ({pos_qty:.6f})"
            if pos_qty > 0
            else f"buy {pct_to_buy:+.1f}% away"
        )
        print(
            f"  {sym:12} ${price:.4f}  buy ${buy_level:.4f}  "
            f"sell ${sell_level:.4f}  → {status}"
        )

    print()
    print("Open orders:")
    print("-" * 60)
    found_any = False
    for sym in symbols:
        orders = get_open_orders(trading_client, sym)
        for o in orders:
            side = "BUY" if o.side == OrderSide.BUY else "SELL"
            px = getattr(o, "limit_price", None) or getattr(o, "stop_price", "?")
            amt = getattr(o, "qty", "?")
            print(f"  {sym} {side} {amt} @ {px}")
            found_any = True
    if not found_any:
        print("  Geen open orders")

    print()
    print("=" * 60)
    print("Range strategie: buy wanneer prijs daalt tot buy level.")
    print("Geen trades = prijzen zijn niet gedaald tot de buy levels.")
    print("=" * 60)


if __name__ == "__main__":
    main()
