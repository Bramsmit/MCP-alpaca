#!/usr/bin/env python3
"""
Dagelijks rapport voor Bitvavo bot: portfoliowaarde + winst/verlies naar Telegram.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from bot_live.bitvavo_trader import get_exchange, get_portfolio_value
from bot_live.telegram import send_telegram

_DAY_STATE_PATH = Path(__file__).resolve().parent.parent / ".bitvavo_day_state.json"


def save_day_start(value: float) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _DAY_STATE_PATH.write_text(json.dumps({"date": today, "start_value": value}))


def load_day_start() -> tuple[str | None, float | None]:
    if not _DAY_STATE_PATH.exists():
        return None, None
    try:
        data = json.loads(_DAY_STATE_PATH.read_text())
        return data.get("date"), data.get("start_value")
    except Exception:
        return None, None


def send_daily_report(exchange=None) -> None:
    if exchange is None:
        exchange, _ = get_exchange()

    value = get_portfolio_value(exchange)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_str = datetime.now(timezone.utc).strftime("%d-%m-%Y")

    start_date, start_value = load_day_start()

    if start_value and start_date == today:
        diff = value - start_value
        pct = (diff / start_value * 100) if start_value else 0
        arrow = "📈" if diff >= 0 else "📉"
        msg = (
            f"{arrow} Dagrapport {date_str}\n"
            f"Start:  €{start_value:.2f}\n"
            f"Nu:     €{value:.2f}\n"
            f"Winst:  €{diff:+.2f} ({pct:+.1f}%)"
        )
    else:
        msg = f"📊 Dagrapport {date_str}\nPortfolio: €{value:.2f}"

    send_telegram(msg)
    save_day_start(value)


def main():
    send_daily_report()


if __name__ == "__main__":
    main()
