#!/usr/bin/env python3
"""
Dagelijks rapport: stuur totale portfoliowaarde naar Telegram.
Draait via GitHub Actions om 8:00 UTC (9:00 Amsterdam).
"""

from datetime import datetime, timezone

from bot.live_trader import get_trading_clients, get_portfolio_value
from bot.telegram import send_telegram


def main():
    trading_client, _ = get_trading_clients()
    value = get_portfolio_value(trading_client)
    date_str = datetime.now(timezone.utc).strftime("%d-%m-%Y")
    msg = f"📊 Dagelijks rapport {date_str}\nTotaal portfolio: ${value:.2f}"
    send_telegram(msg)


if __name__ == "__main__":
    main()
