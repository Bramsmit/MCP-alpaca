#!/usr/bin/env python3
"""
Status/diagnose: toon waarom de bot wel/niet trade.
- Huidige prijzen vs buy/sell levels
- Open orders
- Posities
- Afstand tot fill (hoe ver is prijs van buy level)
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

from bot.live_trader import (
    get_trading_clients,
    select_top_symbols,
    get_current_prices,
    get_positions,
    get_open_orders,
    get_buying_power,
    get_portfolio_value,
)
from bot.config import SYMBOL_POOL, SYMBOLS_ACTIVE


def main():
    print("=" * 60)
    print("MCP-Alpaca Status / Diagnose")
    print("=" * 60)

    trading_client, data_client = get_trading_clients()
    symbols, levels = select_top_symbols(
        data_client, trading_client, SYMBOL_POOL, SYMBOLS_ACTIVE
    )

    if not symbols:
        print("Geen symbolen geselecteerd uit pool")
        return

    print(f"\nGeselecteerd: {', '.join(symbols)}")
    buying_power = get_buying_power(trading_client)
    portfolio_value = get_portfolio_value(trading_client)
    positions = get_positions(trading_client, symbols=symbols)

    print(f"Buying power: ${buying_power:.2f}")
    print(f"Portfolio waarde: ${portfolio_value:.2f}")
    print(f"Posities: {positions or 'Geen'}")
    print()

    current_prices = get_current_prices(data_client, symbols)

    print("Prijs vs buy/sell levels (trade vult wanneer prijs buy level raakt):")
    print("-" * 60)
    for sym in symbols:
        if sym not in levels or sym not in current_prices:
            continue
        buy_level, sell_level = levels[sym]
        price = current_prices[sym]
        buy_level_f = float(buy_level)
        sell_level_f = float(sell_level)

        # Hoe ver is prijs van buy level? (negatief = prijs onder buy = zou fillen)
        pct_to_buy = (price - buy_level_f) / buy_level_f * 100
        pct_to_sell = (sell_level_f - price) / price * 100 if price else 0

        pos = positions.get(sym, (0, 0))
        pos_qty = pos[0]

        status = "HAS POSITION" if pos_qty > 0 else f"buy {pct_to_buy:+.1f}% away"
        print(f"  {sym:12} prijs ${price:.4f}  buy ${buy_level_f:.4f}  sell ${sell_level_f:.4f}  -> {status}")

    print()
    print("Open orders:")
    print("-" * 60)
    for sym in symbols:
        orders = get_open_orders(trading_client, sym)
        for o in orders:
            side = "BUY" if o.side.value == "buy" else "SELL"
            px = getattr(o, "limit_price", "?")
            print(f"  {sym} {side} @ ${px}")

    if not any(get_open_orders(trading_client, s) for s in symbols):
        print("  Geen open orders")

    print()
    print("=" * 60)
    print("Range strategie: buy alleen wanneer prijs onder buy level komt.")
    print("Geen trades = prijzen zijn niet gedaald tot de buy levels.")
    print("=" * 60)


if __name__ == "__main__":
    main()
