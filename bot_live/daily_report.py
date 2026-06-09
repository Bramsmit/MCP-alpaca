#!/usr/bin/env python3
"""
Dagelijks rapport: stuur portfoliowaarde + winst/verlies naar Telegram.
Draait via GitHub Actions om 8:00 UTC, of automatisch vanuit run_loop om 22:00.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from bot_live.alpaca_runtime import (
    get_trading_clients,
    get_portfolio_value,
    get_cumulative_fictive_fees_usd,
)
from bot_live.telegram import send_telegram
from bot_live.safety import format_safety_status

_DAY_STATE_PATH = Path(__file__).resolve().parent.parent / ".alpaca_day_state.json"


def save_day_start(value: float) -> None:
    """Sla de portfoliowaarde aan het begin van de dag op."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = {"date": today, "start_value": value}
    _DAY_STATE_PATH.write_text(json.dumps(data))


def load_day_start() -> tuple[str | None, float | None]:
    """Laad start-van-dag waarde. Retourneert (datum, waarde) of (None, None)."""
    if not _DAY_STATE_PATH.exists():
        return None, None
    try:
        data = json.loads(_DAY_STATE_PATH.read_text())
        return data.get("date"), data.get("start_value")
    except Exception:
        return None, None


def send_daily_report(trading_client=None) -> None:
    """Stuur eindrapport met start vs. huidige waarde en winst/verlies."""
    if trading_client is None:
        trading_client, _ = get_trading_clients()

    value = get_portfolio_value(trading_client)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_str = datetime.now(timezone.utc).strftime("%d-%m-%Y")

    start_date, start_value = load_day_start()

    if start_value and start_date == today:
        diff = value - start_value
        pct = (diff / start_value * 100) if start_value else 0
        arrow = "📈" if diff >= 0 else "📉"
        msg = (
            f"{arrow} Dagrapport {date_str}\n"
            f"Start:  ${start_value:.2f}\n"
            f"Nu:     ${value:.2f}\n"
            f"Winst:  ${diff:+.2f} ({pct:+.1f}%)"
        )
    else:
        msg = f"📊 Dagrapport {date_str}\nPortfolio: ${value:.2f}"

    cum_fees = get_cumulative_fictive_fees_usd()
    msg += (
        f"\n\n💸 Fictieve transactiekosten (cumulatief, model Bitvavo-stijl): "
        f"${cum_fees:.2f}"
    )
    msg += format_safety_status(value)

    send_telegram(msg)
    save_day_start(value)


def main():
    send_daily_report()


if __name__ == "__main__":
    main()
