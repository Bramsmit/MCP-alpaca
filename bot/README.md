# Trading Bot

## Backtest

```bash
python -m bot.backtest
```

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
- **Stop-loss:** $0.01/eenheid
- **Alpaca:** Paper trading (zie .env)

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
