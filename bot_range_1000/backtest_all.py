#!/usr/bin/env python3
"""
Backtest range-strategie voor alle beschikbare Alpaca cryptos.
Zoekt naar paren die even goed presteren als LINK en UNI.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

import pandas as pd
from bot_live.config import (
    SYMBOL_POOL,
    BUY_ABOVE_LOW_PCT,
    SELL_BELOW_HIGH_PCT,
    MIN_SPREAD_PCT,
    STOP_LOSS_PER_UNIT,
    CAPITAL_PER_ASSET,
)
from bot_range_1000.backtest import fetch_data, run_backtest


def main():
    print("Backtest alle cryptos (3 maanden, stop-loss $0.01)...")
    print()

    try:
        data = fetch_data(SYMBOL_POOL, months=3)
    except Exception as e:
        print(f"Fout: {e}")
        return

    results = []
    for symbol in SYMBOL_POOL:
        if symbol not in data or data[symbol].empty or len(data[symbol]) < 20:
            continue
        res = run_backtest(data[symbol], symbol, CAPITAL_PER_ASSET, STOP_LOSS_PER_UNIT)
        results.append((res["return_pct"], res["n_trades"], symbol))

    results.sort(reverse=True, key=lambda x: x[0])

    print("Resultaten (gesorteerd op return):")
    print("-" * 50)
    for ret, trades, sym in results:
        bar = "█" * min(50, int(abs(ret) / 4)) + "░" * (50 - min(50, int(abs(ret) / 4)))
        print(f"  {sym:12} {ret:+7.1f}%  ({trades:3} trades)  {bar}")
    print()
    print("Top 5 (vergelijkbaar met LINK +72%, UNI +178%):")
    for ret, trades, sym in results[:5]:
        print(f"  {sym}: {ret:+.1f}%")


if __name__ == "__main__":
    main()
