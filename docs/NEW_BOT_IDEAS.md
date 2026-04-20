# Nieuwe Bot Ideeën — Strategieën om te Testen

> Dit document dient als startpunt voor Cursor om een nieuwe bot op te zetten.
> Kies één strategie, maak een nieuwe GitHub repo aan, en laat Cursor alles uitwerken
> op basis van de structuur van de bestaande Bitvavo range bot.

---

## Context: Wat de huidige bot doet

De bestaande **range trading bot** koopt aan de onderkant van een prijsrange en verkoopt aan de bovenkant.
- Werkt goed in **zijwaartse markten**
- Werkt **niet** in sterk trending markten (dan koopt hij terwijl de prijs blijft dalen)
- Tijdshorizon: uren tot dagen per trade

De nieuwe strategieën hieronder zijn bewust **complementair** gekozen — ze werken in marktomstandigheden waar de range bot het moeilijk heeft.

---

## Strategie 1: RSI Mean Reversion Bot ⭐ (aanbevolen als eerste test)

### Idee
Koop wanneer een munt technisch gezien "oversold" is (te hard gedaald), verkoop wanneer hij "overbought" is (te hard gestegen). Gebruik de RSI-indicator als signaal.

### Logica
- Bereken RSI(14) op basis van 1-uurs candles
- **Koop** wanneer RSI < 30 (oversold) EN prijs > 200-EMA (niet in crash)
- **Verkoop** wanneer RSI > 65 (hersteld)
- Stop-loss: 4% onder koopprijs

### Parameters
```python
RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 30       # koop wanneer RSI onder dit niveau
RSI_SELL_THRESHOLD = 65      # verkoop wanneer RSI boven dit niveau
EMA_TREND_FILTER = 200       # alleen kopen als prijs boven 200-EMA (uptrend filter)
STOP_LOSS_PCT = 0.04         # 4% stop-loss
MAX_CAPITAL_EUR = 500
SYMBOLS_ACTIVE = 3
```

### Waarom interessant
- Werkt goed in volatile markten waar range bot faalt
- RSI is bewezen betrouwbaar voor crypto mean reversion
- De 200-EMA filter voorkomt kopen in een bear trend
- Meer trades dan range bot (RSI bereikt < 30 vaker dan een precieze range level)

### Exchange aanbeveling
**Bitvavo** — zelfde als huidige bot, makkelijk te vergelijken. Of **Kraken** als je twee live accounts wil scheiden.

### Technische vereisten
- `ccxt` voor exchange
- `pandas` + `ta` library voor RSI/EMA berekening
- Hourly GitHub Actions (zelfde als huidige bot)
- Geen aparte dataprovider nodig (OHLCV van exchange zelf)

---

## Strategie 2: Dip Buyer (Momentum DCA Bot)

### Idee
Koop wanneer een munt significant daalt van zijn recente high ("dip"). Verkoop in porties wanneer hij herstelt. Simpel, effectief, en intuïtief.

### Logica
- Houd per symbool de hoogste prijs bij van de afgelopen 24u (rolling high)
- **Koop** wanneer huidige prijs > X% onder rolling high (bijv. -6%)
- **Verkoop** in twee porties: helft op +4%, rest op +8%
- Stop-loss: -10% onder koopprijs

### Parameters
```python
DIP_THRESHOLD_PCT = 0.06     # koop bij 6% daling van 24h high
TAKE_PROFIT_1_PCT = 0.04     # verkoop 50% bij +4%
TAKE_PROFIT_2_PCT = 0.08     # verkoop rest bij +8%
STOP_LOSS_PCT = 0.10         # stop-loss bij -10%
LOOKBACK_HOURS = 24          # rolling high window
MAX_CAPITAL_EUR = 500
SYMBOLS_ACTIVE = 3
```

### Waarom interessant
- Geen complexe indicatoren nodig
- Werkt goed bij crypto volatiliteit (flash crashes, nieuws-dips)
- Twee take-profit levels = hogere kans op gedeeltelijke winst
- Logisch voor iedereen te begrijpen

### Exchange aanbeveling
**Bitvavo** — goede liquiditeit voor de top crypto's. Of **Kraken** (heeft iets betere API voor meerdere orders tegelijk).

### Technische vereisten
- `ccxt` voor exchange
- Alleen OHLCV + ticker data nodig (geen externe library)
- State bijhouden per symbool: {entry_price, qty_remaining, take_profit_1_filled}
- Hourly GitHub Actions

---

## Strategie 3: EMA Crossover Trend Bot

### Idee
Volg de trend. Koop wanneer een kortetermijn EMA boven een langetermijn EMA kruist (uptrend start), verkoop wanneer hij er weer onder kruist.

### Logica
- Bereken EMA(9) en EMA(21) op dagelijkse candles
- **Koop** wanneer EMA(9) kruist boven EMA(21) ("golden cross")
- **Verkoop** wanneer EMA(9) kruist onder EMA(21) ("death cross")
- Trailing stop-loss: 5% onder hoogste prijs na entry

### Parameters
```python
EMA_FAST = 9
EMA_SLOW = 21
TRAILING_STOP_PCT = 0.05     # 5% trailing stop
TIMEFRAME = "1d"             # dagelijkse candles
MAX_CAPITAL_EUR = 500
SYMBOLS_ACTIVE = 3
```

### Waarom interessant
- **Tegenovergestelde van range bot**: werkt juist in trending markten
- Houdt posities langer vast (dagen tot weken)
- Trailing stop beschermt winst automatisch
- Minder trades = minder transactiekosten

### Exchange aanbeveling
**Kraken** — betere liquiditeit voor langere posities en iets lagere fees dan Bitvavo voor grotere bedragen.

### Technische vereisten
- `ccxt` voor exchange
- `pandas` + `ta` library voor EMA berekening
- **Dagelijkse** GitHub Actions (niet hourly — dagelijkse candles)
- State bijhouden: {in_position, entry_price, highest_price_since_entry}

---

## Vergelijkingstabel

| | Range Bot (huidig) | RSI Mean Reversion | Dip Buyer | EMA Trend |
|---|---|---|---|---|
| **Markttype** | Zijwaarts | Volatile/herstel | Volatile/dips | Trending |
| **Trades per week** | 2-5 | 3-8 | 1-4 | 0-2 |
| **Houdt positie** | Uren-dagen | Uren-dagen | Uren | Dagen-weken |
| **Complexiteit** | ★★★ | ★★★ | ★★ | ★★★ |
| **Extra libraries** | Geen | `ta` | Geen | `ta` |
| **Aanbevolen exchange** | Bitvavo | Bitvavo | Bitvavo/Kraken | Kraken |

---

## Instructies voor Cursor

Gebruik dit document om een nieuwe bot op te zetten. Doe het volgende:

1. **Maak een nieuwe GitHub repo aan** (bijv. `crypto-bot-rsi` of `crypto-bot-dip`)
2. **Gebruik de structuur van de Bitvavo bot** als template:
   - `bot_range_1000/live_trader.py` of `bot_hybrid/hybrid_trader.py` — voorbeeld entrypoints
   - `bot_live/config.py` — strategie parameters (gedeeld)
   - `bot_live/telegram.py`, `bot_live/journal.py` — notificaties / logging
   - `bot_live/daily_report.py` — dagrapport
   - `bot_live/requirements.txt` — dependencies
3. **GitHub Actions** (3 workflows):
   - `trade.yml` — hourly (of daily voor EMA trend bot)
   - `daily_report.yml` — 20:00 UTC
   - `daily_status.yml` — heartbeat 09:00 UTC
4. **Secrets** op GitHub:
   - `EXCHANGE_API_KEY`
   - `EXCHANGE_SECRET_KEY`
   - `DRY_RUN` — start altijd op `True`
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. **Start altijd in dry run** — minimaal 1 week draaien zonder geld
6. **Gebruik `ccxt`** als exchange library (ondersteunt Bitvavo én Kraken)
7. **Maximaal kapitaal** via `MAX_CAPITAL_EUR` in config — nooit meer dan je wil riskeren
