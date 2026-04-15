#!/usr/bin/env python3
"""Annuleer alle open orders op Kraken (via .env credentials)."""

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

import ccxt

from bot.config import SYMBOL_POOL


def main():
    api_key = os.environ.get("KRAKEN_API_KEY", "")
    secret = os.environ.get("KRAKEN_SECRET_KEY", "")
    if not api_key or not secret:
        print("❌ KRAKEN_API_KEY en KRAKEN_SECRET_KEY vereist in .env")
        return

    exchange = ccxt.kraken({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
    })
    exchange.load_markets()

    print(f"⚠️  Kraken account: {api_key[:8]}...")
    print("Open orders ophalen...")

    total_cancelled = 0
    for symbol in SYMBOL_POOL:
        try:
            orders = exchange.fetch_open_orders(symbol)
            for o in orders:
                try:
                    exchange.cancel_order(o["id"], symbol)
                    print(f"  Geannuleerd: {symbol} {o.get('side','?')} @ {o.get('price','?')} (id={o['id'][:8]})")
                    total_cancelled += 1
                except Exception as e:
                    print(f"  Fout bij annuleren {o['id']}: {e}")
        except Exception as e:
            print(f"  Fout bij ophalen orders {symbol}: {e}")

    print(f"\nKlaar. {total_cancelled} order(s) geannuleerd.")


if __name__ == "__main__":
    main()
