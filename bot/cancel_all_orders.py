#!/usr/bin/env python3
"""Annuleer alle open orders op Alpaca paper account."""

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

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

def main():
    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    client = TradingClient(api_key, secret, paper=True)

    result = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    orders = result if isinstance(result, list) else result.get("orders", [])

    print(f"Gevonden: {len(orders)} open orders")
    for o in orders:
        try:
            client.cancel_order_by_id(o.id)
            print(f"  Geannuleerd: {o.symbol} {o.side} {o.id}")
        except Exception as e:
            print(f"  Fout {o.id}: {e}")
    print("Klaar.")

if __name__ == "__main__":
    main()
