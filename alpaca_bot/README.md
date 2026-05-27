# alpaca_bot/

Alle **Alpaca paper** range-bot code en de **venue-neutrale strategie** (`strategy_core.py`, gebruikt ook door `kraken/`).

- Run: `python -m alpaca_bot.live_trader`
- Shim: `python -m bot_range_1000.live_trader` → zelfde module.

Naam **`alpaca_bot`** i.p.v. `alpaca`: voorkomt conflict met het pip-pakket `alpaca` (Alpaca SDK).
