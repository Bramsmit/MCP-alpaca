"""
Compat-shim: canonieke range-runner staat in `alpaca_bot.live_trader`.

Behoudt `python -m bot_range_1000.live_trader` en bestaande imports.
"""

from alpaca_bot.live_trader import main, run_once, select_top_symbols

__all__ = ["main", "run_once", "select_top_symbols"]

if __name__ == "__main__":
    main()
