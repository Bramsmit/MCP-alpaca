#!/usr/bin/env python3
"""
Draai de live trader continu: elke INTERVAL_MINUTEN minuten.
Gebruik op een server met: nohup python3 -m bot_live.run_loop &
Stuurt automatisch een dagrapport (start vs. einde + winst/verlies) om DAGRAPPORT_UUR.
"""

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Project root + werkmap
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

INTERVAL_MINUTEN = 60   # Elk uur
DAGRAPPORT_UUR = 22     # Lokale tijd: 22:00 stuur dagrapport

from bot_range_1000.live_trader import run_once, get_trading_clients, get_portfolio_value
from bot_live.telegram import send_telegram
from bot_live.daily_report import send_daily_report, save_day_start, load_day_start


def _init_day_start(trading_client) -> None:
    """Sla start-van-dag waarde op als dat nog niet voor vandaag is gedaan."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date, _ = load_day_start()
    if start_date != today:
        value = get_portfolio_value(trading_client)
        save_day_start(value)


def main():
    trading_client, _ = get_trading_clients()
    _init_day_start(trading_client)

    send_telegram(
        f"🟢 Bot gestart (elke {INTERVAL_MINUTEN} min | dagrapport om {DAGRAPPORT_UUR}:00)"
    )

    last_report_day = None

    while True:
        now = datetime.now()
        try:
            run_once()
        except Exception as e:
            send_telegram(f"❌ Bot fout: {e}")
            print(f"Fout: {e}")

        # Dagrapport sturen om DAGRAPPORT_UUR (één keer per dag)
        if now.hour == DAGRAPPORT_UUR and now.strftime("%Y-%m-%d") != last_report_day:
            try:
                send_daily_report()
                last_report_day = now.strftime("%Y-%m-%d")
            except Exception as e:
                send_telegram(f"⚠️ Dagrapport fout: {e}")

        time.sleep(INTERVAL_MINUTEN * 60)


if __name__ == "__main__":
    main()
