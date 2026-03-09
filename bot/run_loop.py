#!/usr/bin/env python3
"""
Draai de live trader continu: elke INTERVAL_MINUTEN minuten.
Gebruik op een server met: nohup python3 -m bot.run_loop &
"""

import os
import sys
import time
from pathlib import Path

# Project root + werkmap
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

INTERVAL_MINUTEN = 60  # Elk uur

def main():
    from bot.telegram import send_telegram
    send_telegram("🟢 Bot gestart op server (elke {} min)".format(INTERVAL_MINUTEN))

    while True:
        try:
            from bot.live_trader import run_once
            run_once()
        except Exception as e:
            from bot.telegram import send_telegram
            send_telegram(f"❌ Bot fout: {e}")
            print(f"Fout: {e}")

        time.sleep(INTERVAL_MINUTEN * 60)

if __name__ == "__main__":
    main()
