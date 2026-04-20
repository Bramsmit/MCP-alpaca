#!/usr/bin/env python3
"""
Test of Telegram notificaties werken.
Run: python -m bot_live.test_telegram
(of: cd MCP-alpaca && python -m bot_live.test_telegram)
"""

import os
from pathlib import Path

# Laad .env uit project root
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

from bot_live.telegram import send_telegram

if __name__ == "__main__":
    print("Versturen testbericht naar Telegram...")
    if send_telegram("✅ MCP-Alpaca bot: Telegram werkt!"):
        print("Bericht verstuurd!")
    else:
        print("Mislukt. Controleer TELEGRAM_BOT_TOKEN en TELEGRAM_CHAT_ID in .env")
