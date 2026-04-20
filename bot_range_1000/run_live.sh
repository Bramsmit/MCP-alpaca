#!/bin/bash
# Run de live paper trader. Gebruik in cron voor dagelijkse runs.
cd "$(dirname "$0")/.."
python3 -m bot_range_1000.live_trader
