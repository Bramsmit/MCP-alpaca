# Bot op een server draaien

## Opties

| Optie | Kosten | Moeite | Geschikt voor |
|-------|--------|--------|---------------|
| **VPS + cron** | ~€5/maand | Laag | Meest betrouwbaar |
| **GitHub Actions** | Gratis | Laag | Max 1x per uur (limiet) |
| **Railway / Render** | Gratis tier | Medium | Altijd aan |

---

## 1. VPS (aanbevolen)

### Stap 1: Server

- [DigitalOcean](https://digitalocean.com) – $6/maand
- [Hetzner](https://hetzner.com) – €4/maand
- [Oracle Cloud](https://oracle.com/cloud/free) – gratis tier

### Stap 2: Setup

```bash
# SSH naar je server
ssh root@jouw-server-ip

# Python 3 + git
apt update && apt install -y python3 python3-pip git

# Project clonen
cd /opt
git clone https://github.com/JOUW-USER/MCP-alpaca.git
cd MCP-alpaca

# Dependencies
pip3 install -r bot/requirements.txt
pip3 install alpaca-py pandas requests

# .env aanmaken (kopieer van je Mac)
nano .env
# Plak ALPACA_API_KEY, ALPACA_SECRET_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

### Stap 3: Cron (elke uur)

```bash
crontab -e
```

Voeg toe:

```
0 * * * * cd /opt/MCP-alpaca && python3 -m bot.live_trader >> /var/log/alpaca-bot.log 2>&1
```

### Of: continu draaien met run_loop

```bash
cd /opt/MCP-alpaca
nohup python3 -m bot.run_loop >> /var/log/alpaca-bot.log 2>&1 &
```

---

## 2. GitHub Actions (gratis)

Maak `.github/workflows/trade.yml`:

```yaml
name: Trade Bot
on:
  schedule:
    - cron: '0 * * * *'   # Elk uur
  workflow_dispatch:
jobs:
  trade:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install alpaca-py pandas requests
      - run: python -m bot.live_trader
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
          ALPACA_SECRET_KEY: ${{ secrets.ALPACA_SECRET_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

Voeg secrets toe: **Settings → Secrets → Actions**

---

## 3. Railway / Render

1. Push project naar GitHub
2. Maak account op [Railway](https://railway.app) of [Render](https://render.com)
3. Nieuwe service → "Background Worker"
4. Build: `pip install -r bot/requirements.txt`
5. Start: `python -m bot.run_loop`
6. Environment variables: ALPACA_API_KEY, etc.

---

## Beveiliging

- **Commit nooit je .env** – staat in .gitignore
- Gebruik **secrets** of **environment variables** op de server
- Paper trading keys zijn minder kritiek, maar hou ze privé
