# Trading Bot

## Backtest

```bash
python -m bot.backtest
```

## Context voor v2 / Cursor (architectuur + trade-handoff)

- Overzicht: [docs/CODEBASE_CONTEXT_FOR_V2.md](../docs/CODEBASE_CONTEXT_FOR_V2.md)
- Export (JSON + MD, geen API keys): `python -m bot.export_handoff` → bestanden in `exports/`

## Live Paper Trading

```bash
python -m bot.live_trader
```

### Alle orders annuleren

```bash
python -m bot.cancel_all_orders
```

### Op een server draaien

Zie [docs/DEPLOY.md](../docs/DEPLOY.md) voor VPS, GitHub Actions, of Railway.

### Dagelijks draaien (cron)

```bash
# Elke dag om 9:00
0 9 * * * cd /Users/bramsmits/Documents/Cursor/Hobby/MCP-alpaca && python3 -m bot.live_trader
```

Of vaker (bijv. elk uur) voor snellere order-updates:

```bash
0 * * * * cd /path/to/MCP-alpaca && python3 -m bot.live_trader
```

### Configuratie

- **Assets:** AVAX, UNI, AAVE (SHIB/PEPE: prijs te laag voor Alpaca limit orders)
- **Strategie:** Koop 0.5% boven 24h low, verkoop 2% onder 24h high
- **Stop-loss:** $0.01/eenheid (Alpaca crypto: max 1 exit order/positie – zie [docs/ALPACA_CRYPTO_LIMITATIONS.md](../docs/ALPACA_CRYPTO_LIMITATIONS.md))
- **Alpaca:** Paper trading (zie .env)

### Dynamische order updates

- **1% drempel:** Order wordt bijgewerkt als het nieuwe niveau >1% afwijkt
- **24h window:** Na 24 uur zonder fill: cancel en herplaats met verse 24h levels
- **Stale price (5%):** Buy: als huidige prijs >5% boven order, direct herplaats. Sell: als prijs >5% onder target, herplaats
- **Retry:** Bij API-fout: 2 retries met 5–10 sec pauze
- **Run summary:** Elke run stuurt een Telegram-samenvatting (geplaatst, bijgewerkt, ongewijzigd, overgeslagen)

### GitHub Actions

De bot draait elk uur via `.github/workflows/trade.yml`. Secrets: ALPACA_API_KEY, ALPACA_SECRET_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

## Telegram notificaties

### 1. Chat ID ophalen

1. Stuur `/start` naar [@mcp_alpaca_bram_bot](https://t.me/mcp_alpaca_bram_bot)
2. Open: `https://api.telegram.org/bot<JOUW_TOKEN>/getUpdates` (vervang `<JOUW_TOKEN>` door je bot token)
3. Zoek `"chat":{"id":123456789,...}` – dat getal is je Chat ID
4. Vul in `.env`: `TELEGRAM_CHAT_ID=123456789`

### 2. Testen

```bash
cd /Users/bramsmits/Documents/Cursor/Hobby/MCP-alpaca
python -m bot.test_telegram
```

### 3. Gebruik in je trading script

```python
from bot.telegram import send_telegram, notify_trade

# Simpel bericht
send_telegram("Order geplaatst!")

# Trade-notificatie
notify_trade("buy", "DOT/USD", 10, 7.50, order_id="abc-123")
```

### ⚠️ Token beveiligen

Je bot token is eerder gedeeld. Genereer een nieuwe via @BotFather → je bot → /revoke, en update `TELEGRAM_BOT_TOKEN` in `.env`.
