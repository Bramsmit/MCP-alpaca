# MCP-Alpaca — codebase context (v1 → v2 / Cursor)

Gebruik dit bestand als **projectcontext** in een nieuwe Cursor-workspace of om een **vervolgversie** van de bot te bouwen. Het beschrijft structuur, gedrag, data-bestanden en hoe je een **handoff-pakket** (JSON + MD) genereert met echte trade-historie.

---

## 1. Wat doet dit project?

**Paper trading** op **Alpaca crypto** met een **range-strategie**:

- Dagelijkse (1D) candles → **gemiddelde low/high** over de laatste `LEVELS_LOOKBACK_DAYS` (nu3).
- **Limit buy** net boven de gemiddelde low; **limit sell** net onder de gemiddelde high; minimale spread tussen beide.
- Uit een **pool** van symbolen worden de **top N** (`SYMBOLS_ACTIVE`) gekozen op een **score** (spread × volatiliteit-achtige term op recente bars). Open posities blijven **altijd** in de actieve set.
- Orders worden **bijgewerkt** als ze te oud zijn (24h), te ver van het nieuwe niveau (1%), of “stale” t.o.v. markt (5%).
- **Alpaca crypto:** maximaal **één exit-order per positie** (geen bracket: geen limit sell + stop tegelijk). Zie `docs/ALPACA_CRYPTO_LIMITATIONS.md`.

**Geen machine learning** en **geen learning loop** uit het journal: het journal is voor **rapportage**, niet voor automatische parameter-optimalisatie.

---

## 2. Mappen en bestanden

| Pad | Rol |
|-----|-----|
| `bot_live/config.py` | Strategie-constanten (range + hybrid), Bitvavo fee-constants, order-drempels. |
| `bot_live/alpaca_runtime.py` | **Gedeelde Alpaca-runtime:** clients, quotes, posities, sells, fill-notificaties, `.alpaca_trade_state.json`. |
| `alpaca_bot/live_trader.py` | Range-bot (paper): `run_once()`, symbol selectie; shim `bot_range_1000/live_trader.py`. |
| `bot_range_1000/backtest.py`, `backtest_all.py` | Historische simulatie range-strategie. |
| `bot_range_1000/export_handoff.py` | Handoff JSON/MD — zie §7. |
| `bot_hybrid/hybrid_trader.py` | Hybrid regime-trader (hourly); deelt Alpaca-helpers met range. |
| `bot_hybrid/` | `range_strategy`, `trend_strategy`, `market_regime_detector`, `indicators`, enz. |
| `bot_live/run_loop.py` | Eindeloze lus die `bot_range_1000.live_trader.run_once()` aanroept. |
| `bot_live/journal.py` | Append **gevulde trades** naar `trades.jsonl` (JSON-lines). |
| `bot_live/report.py` | Statistieken uit `trades.jsonl`. |
| `bot_live/telegram.py` | Telegram Bot API. |
| `bot_live/daily_report.py`, `bitvavo_*.py` | Rapportage / Bitvavo-runner. |
| `bot_live/status.py` | Status / diagnostiek (Alpaca). |
| `bot_live/cancel_all_orders.py` | Hulp voor orders (legacy Kraken-tekst in docstring mogelijk). |
| `.github/workflows/trade.yml` | Elk uur: cache state, `python -m alpaca_bot.live_trader` (of shim `bot_range_1000.live_trader`). |
| `.github/workflows/daily_report.yml`, `daily_status.yml` | Overige automatisering. |
| `docs/DEPLOY.md`, `docs/GITHUB_SETUP.md` | Deploy / GitHub. |
| `trades.jsonl` | **Lokaal / CI-cache:** één JSON-object per regel per gedetecteerde fill (gitignored). |
| `.alpaca_trade_state.json` | **State:** o.a. `entries` (entry voor P&L), `notified_order_ids` (gitignored). |

---

## 3. Entry points

- **Range (zoals CI):** `python -m alpaca_bot.live_trader` of `python -m bot_range_1000.live_trader` (shim)
- **Hybrid v2:** `python -m bot_hybrid.hybrid_trader`
- **Continu op server:** `python -m bot_live.run_loop` of `bot_range_1000/run_live.sh`
- **Handoff genereren:** `python -m bot_range_1000.export_handoff`

Clients worden in `live_trader.get_trading_clients()` met **`paper=True`** aangemaakt. Live gaan = **live API-keys** + **`paper=False`** (bij voorkeur via environment variable i.p.v. hardcoded).

---

## 4. Belangrijke configuratie (`bot_live/config.py`)

- `SYMBOL_POOL` — lijst crypto-paren (Alpaca-notatie `BASE/USD`).
- `SYMBOLS_ACTIVE` — hoeveel symbolen tegelijk actief (nu3).
- `CAPITAL_PER_ASSET` — notioneel kapitaal per actief (afgeleid van `START_CAPITAL`).
- `BUY_ABOVE_LOW_PCT`, `SELL_BELOW_HIGH_PCT`, `MIN_SPREAD_PCT` — range-randen.
- `ORDER_UPDATE_THRESHOLD`, `ORDER_MAX_AGE_HOURS`, `ORDER_STALE_PRICE_THRESHOLD` — dynamisch orderbeheer.
- `ALPACA_CRYPTO_SINGLE_EXIT_ORDER` — moet `True` blijven voor huidige crypto-gedrag.
- `ORDER_REPLACE_DELAY_SEC` — pauze na cancel vóór nieuwe order (balance sync).

Exacte waarden staan in de repo; voor een snapshot na import: draai `export_handoff`.

---

## 5. Logging vs journal vs state

1. **Console/log:** Python `logging` in `live_trader.py` → o.a. GitHub Actions log.
2. **Journal:** `_check_and_notify_filled_orders` haalt **recent gesloten** orders op; nieuwe fills → Telegram + `log_trade()` → `trades.jsonl`.
3. **State:** aan het eind van `run_once()` worden `entries` uit **huidige posities** opgeslagen voor **profit** op de volgende sell in het journal.

**Let op:** fill-detectie gebruikt een **beperkt tijdsvenster** (uren). Als de bot lang niet draait, kunnen sommige fills ontbreken in journal/Telegram.

---

## 6. Omgeving (geen secrets in repo)

- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optioneel)

Zie `.env.example`. Handoff-export bevat **geen** API-keys.

---

## 7. Handoff-pakket voor v2 / Cursor

Genereer een **JSON** (machineleesbaar) + **Markdown** (leesbaar) met dezelfde timestamp in de bestandsnaam:

```bash
cd /path/to/MCP-alpaca
python -m bot_range_1000.export_handoff
# optioneel:
python -m bot_range_1000.export_handoff --output-dir metrics --max-trades-md 80
```

Uitvoer (voorbeeld):

- `metrics/alpaca_range_bot_v1_handoff_2026-04-13_143022Z.json`
- `metrics/alpaca_range_bot_v1_handoff_2026-04-13_143022Z.md`

**Inhoud (concept):**

- `meta` — generator, tijd, pad naar repo
- `config_snapshot` — relevante constanten uit `bot_live.config`
- `trades` — volledige lijst uit `trades.jsonl` (als bestand bestaat)
- `trade_summary` — aantallen, win rate, totaal profit (indien sells met profit)
- `state_summary` — of state bestaat, aantal symbols in entries, aantal notified IDs (geen volledige order-id dump verplicht; zie JSON)

Het **Markdown**-bestand vat dit samen + tabel met de laatste N trades (configureerbaar).

**Tip voor Cursor v2:** voeg in de nieuwe workspace toe:

1. Dit bestand `docs/CODEBASE_CONTEXT_FOR_V2.md`
2. De laatste `metrics/alpaca_range_bot_v1_handoff_*.md` en/of `.json`

Zo heeft het model **architectuur + jouw historische trades + instellingen** zonder de hele oude repo te hoeven kennen.

---

## 8. Bekende beperkingen (kort)

- Strategie: **range**; in sterke trends kunnen fills en P&L anders uitpakken.
- Crypto: **geen tweede exit-order**; stop-loss als aparte order naast limit sell werkt niet zoals bij equities.
- CI-cache: bij verlies van cache verlies je **lokale journal-historie** in die omgeving (Alpaca blijft bron van waarheid voor orders).

---

## 9. Gerelateerde docs in repo

- `README.md`, `bot_range_1000/README.md`, `SETUP_GUIDE.md`
- `docs/ALPACA_CRYPTO_LIMITATIONS.md`
- `docs/DEPLOY.md`, `docs/GITHUB_SETUP.md`
