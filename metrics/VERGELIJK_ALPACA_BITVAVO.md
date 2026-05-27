# Plan: Alpaca-bot vs Bitvavo-bot vergelijken

Dit document is een **stappenplan** om resultaten eerlijk naast elkaar te leggen. Voer dezelfde stappen voor **beide** bots uit (zelfde periode, zelfde soort exports).

---

## 1. Doel en scope vastleggen

- **Vergelijkingsperiode:** kies een vaste start- en einddatum in **UTC** (bijv. `2026-03-01` t/m `2026-03-31`). Noteer deze bovenaan je worksheet.
- **Wat je vergelijkt:** liever **relatieve** maten (return op ingezet kapitaal, PnL % per afgeronde ronde, win rate) dan alleen absolute euro’s — tenzij het ingezette kapitaal bij beide setups vergelijkbaar is.
- **Paper vs live:** noteer expliciet of de Alpaca-run **paper** is en Bitvavo **live**. Dat verklaart verschil in uitvoering; het is geen fout, maar wel context voor je conclusies.

---

## 2. Definities afspreken (één keer)

| Onderwerp | Afspraak |
|-----------|----------|
| **Afgeronde trade** | Bijv. buy + sell op hetzelfde symbool binnen jouw strategie, of alle legs los loggen en later bundelen. |
| **Winst** | Bruto verschil minus fees (consistent dezelfde fee-annames als in je bots, waar mogelijk). |
| **Symbool** | Zelfde basis-asset (BTC, ETH) — USD- vs EUR-paar is een **andere markt**; vergelijk per coin of houd rekening met koers/timing. |

---

## 3. Data verzamelen — Alpaca

1. **Primaire bron (in deze repo):** script dat rechtstreeks de **Alpaca Trading API** gebruikt (alle **FILLED** orders in een kalenderperiode UTC, geen 4-uur-limiet van het journal):

   ```bash
   cd /pad/naar/deze-repo
   python -m bot_live.export_alpaca_orders --start 2026-03-01 --end 2026-03-31
   # Of rollend venster (laatste 30 UTC-kalenderdagen t/m vandaag):
   python -m bot_live.export_alpaca_orders --days 30 --only-config-symbols
   ```

   **Lokaal:** zelfde `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` als de trading workflow; het script leest `.env` uit de repo-root des beschikbaar (`setdefault` — bestaande omgevingsvariabelen blijven leidend).

   Optioneel:
   - `--output-dir metrics` — standaard staat output al onder **`metrics/`** in de repo-root.
   - `--only-config-symbols` — alleen pairs uit `bot_live.config.SYMBOL_POOL` (zelfde universum als de range-bot).
   - `--submit-lookback-days N` — standaard 120; verhoog als je limit orders hebt die **veel eerder** zijn geplaatst dan in de exportperiode en pas in die periode vullen (Alpaca filtert API-zoekopdrachten op `submitted_at`).

   Uitvoer (allemaal `gitignore`, dus niet gecommit):  
   `metrics/alpaca_filled_orders_<start>_<end>.csv`, `.json`, en `*_summary.md` (kolommen o.a. `timestamp_utc`, `symbol`, `side`, `filled_qty`, `filled_avg_price`, `order_id`; JSON bevat `meta` met paper/live en periode).

2. **GitHub Actions (operationeel):** workflow `Alpaca — vergelijkings-export API` (`.github/workflows/alpaca_export_comparison.yml`).
   - Handmatig: *Actions* → die workflow → *Run workflow* (`days`, alleen pool ja/nee).
   - Gepland: maandag 05:30 UTC met **30 dagen** terug en `--only-config-symbols` (pas de `cron` aan indien gewenst).
   - Secrets: zelfde als range-bot trade-job — `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`; optioneel `ALPACA_PAPER_TRADE` (`True`/`False`).
   - Download de **Artifacts** (CSV + JSON + summary) na een succesvolle run.

3. **Secundair / check:** `trades.jsonl` in de root (journal) — vergelijk met de CSV; grote verschillen wijzen op gemiste journal-regels (bot offline, 4-uur-venster in de runtime).

4. **Optioneel — handoff-pakket** (config + journal, geen volledige API-historie):

   ```bash
   python -m bot_range_1000.export_handoff --output-dir metrics
   ```

---

## 4. Data verzamelen — Bitvavo

1. **Primaire bron:** Bitvavo **order- en trade-historie** (app of API) over **exact dezelfde periode** als bij Alpaca.
2. Als je **deze repo**-`bitvavo_trader` gebruikt: controleer dat logging overeenkomt met wat je verwacht; `log_trade` schrijft naar `trades.jsonl` — voor volledigheid liever exchange-data.
3. **Velden:** hetzelfde minimum als bij Alpaca (UTC, symbool, side, qty, prijs, fees indien beschikbaar).

---

## 5. Normaliseren en naast elkaar zetten

1. Zet beide exports in **één formaat** (bijv. twee tabbladen in één spreadsheet, of twee CSV’s met dezelfde kolomnamen).
2. **UTC** overal; geen mix van lokale tijd en UTC.
3. **Per symbool** (of per strategie-universe) totalen en gemiddelden berekenen naast **totaal over de periode**.
4. Bereken minimaal:
   - aantal afgeronde transacties (of buy/sell-paren volgens je definitie);
   - win rate (als je rondes definieert);
   - som / gemiddelde PnL;
   - waar mogelijk: **return op gemiddeld ingezet kapitaal** of PnL % t.o.v. nominale positiegrootte.

---

## 6. Caveats — kort afvinken

- [ ] Zelfde kalenderperiode (UTC) voor beide bots.
- [ ] Paper (Alpaca) vs live (Bitvavo) in het verslag genoemd.
- [ ] Verschillende trading pairs (USD vs EUR) niet blind als “dezelfde trade” tellen.
- [ ] Fees/spread in de vergelijking meegenomen of expliciet uitgesloten met reden.
- [ ] Journal alleen gebruikt als **aanvulling**, niet als enige bron als je volledige historie nodig hebt.

---

## 7. Wat je aan het eind vastlegt

Eén korte **conclusiepagina** (half A4 is genoeg):

- periode en bronnen (waar kwam elke export vandaan);
- kerngetallen naast elkaar (tabel);
- 2–3 zinnen: wat het verschil waarschijnlijk verklaart (paper/live, fees, andere coins, timing).

Daarmee kun je later opnieuw dezelfde methode toepassen zonder opnieuw te gissen.

---
