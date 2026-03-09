#!/bin/bash
# Run de live paper trader. Gebruik in cron voor dagelijkse runs.
cd "$(dirname "$0")/.."
python3 -m bot.live_trader
