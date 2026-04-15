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

from bot.live_trader import (
    get_exchange,
    select_top_symbols,
    get_current_prices,
    get_positions,
    get_open_orders,
    get_balance,
    get_portfolio_value,
)
from bot.config import SYMBOL_POOL, SYMBOLS_ACTIVE, MAX_CAPITAL_EUR


def main():
    print("=" * 60)
    print("Kraken Range Trader — Status / Diagnose")
    print("=" * 60)

    exchange, dry_run = get_exchange()
    if dry_run:
        print("⚠️  DRY RUN MODE")

    symbols, levels = select_top_symbols(exchange, SYMBOL_POOL, SYMBOLS_ACTIVE)

    if not symbols:
        print("Geen symbolen geselecteerd uit pool")
        return

    print(f"\nGeselecteerd: {', '.join(symbols)}")
    balance_eur = get_balance(exchange)
    portfolio_value = get_portfolio_value(exchange)
    positions = get_positions(exchange, symbols)

    print(f"Vrij EUR:        €{balance_eur:.2f}")
    print(f"Max kapitaal:    €{MAX_CAPITAL_EUR:.2f}")
    print(f"Portfolio waarde: €{portfolio_value:.2f}")
    print(f"Posities: {positions or 'Geen'}")
    print()

    current_prices = get_current_prices(exchange, symbols)

    print("Prijs vs buy/sell levels:")
    print("-" * 60)
    for sym in symbols:
        if sym not in levels or sym not in current_prices:
            continue
        buy_level, sell_level = levels[sym]
        price = current_prices[sym]
        pct_to_buy = (price - buy_level) / buy_level * 100
        pos_qty = positions.get(sym, 0)
        status = f"HAS POSITION ({pos_qty:.6f})" if pos_qty > 0 else f"buy {pct_to_buy:+.1f}% away"
        print(f"  {sym:12} €{price:.4f}  buy €{buy_level:.4f}  sell €{sell_level:.4f}  → {status}")

    print()
    print("Open orders:")
    print("-" * 60)
    found_any = False
    for sym in symbols:
        orders = get_open_orders(exchange, sym)
        for o in orders:
            side = o.get("side", "?").upper()
            px = o.get("price", "?")
            amt = o.get("amount", "?")
            print(f"  {sym} {side} {amt} @ €{px}")
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
