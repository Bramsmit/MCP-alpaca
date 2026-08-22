# alpaca_bot/

Alle **Alpaca paper** range-bot code en de **venue-neutrale strategie** (`strategy_core.py`, gebruikt ook door `kraken/`).

- Run: `python -m alpaca_bot.live_trader`
- Shim: `python -m bot_range_1000.live_trader` → zelfde module.

Naam **`alpaca_bot`** i.p.v. `alpaca`: voorkomt conflict met het pip-pakket `alpaca` (Alpaca SDK).

## Kapitaalinzet

Deze bot gebruikt eigen instellingen voor het aantal parallelle symbolen; `SYMBOLS_ACTIVE`
uit `bot_live/config.py` blijft op 3 voor hybrid, Kraken en de backtests.

| Env-var | Default | Betekenis |
|---|---|---|
| `ALPACA_RANGE_SYMBOLS_ACTIVE` | 5 | Aantal symbolen dat tegelijk een positie mag hebben. Meer symbolen = meer limietorders in de markt = vaker een fill, bij gelijk risico per trade. |
| `ALPACA_RANGE_MAX_DEPLOYED_PCT` | 0.60 | Plafond op de **totale** blootstelling. `SAFETY_MAX_ALLOC_PCT` begrenst alleen per symbool (20%), dus zonder deze grens kan de bot volledig belegd raken. |

`ALPACA_MIN_POSITION_NOTIONAL_USD` (afgeleid: vaste round-trip-fee ÷ `MIN_SPREAD_PCT` = $25)
bepaalt wanneer een restpositie meetelt. Daaronder krijgt hij geen exit-order en bezet hij
geen kapitaalslot, maar mag hij wel weer aangevuld worden tot een volwaardige positie.
Zonder die drempel deelden restjes van een paar cent de buying power in tienen.

Elke run logt `Ingezet: $X (Y%, max Z%) | Koopslots: n van m`; in `alpaca_runs.jsonl`
staan `deployed_pct`, `buy_slots` en `capital_per_usd` voor de historie.
