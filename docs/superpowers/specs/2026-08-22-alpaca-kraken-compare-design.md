# Design: Alpaca paper vs Kraken live — diagnose + herhaalbare compare

_Datum: 2026-08-22_  
_Repos: `MCP-alpaca v1 1000 eu` (Alpaca paper) ↔ `Kraken bot 500 eu 15 mei` (live)_

## Doel

1. **Diagnose:** verklaren waarom de live Kraken-bot achterblijft t.o.v. de Alpaca paper range-bot.
2. **Herhaalbaar:** CLI/tooling om dezelfde vergelijking later opnieuw te draaien zonder ad-hoc scripts.

## Scope

**In scope**

- Common fill-schema + loaders (Alpaca JSONL, Kraken JSONL/artifact, optioneel Kraken API-pull).
- Metrics: return %, maand-PnL, fills, win-rate, fees, per-symbool, fee-scenario overlay.
- Eenmalige diagnose-run + markdown/CSV output onder `metrics/output/`.
- Persistente Kraken trade-logs in de Kraken-repo (`data/`), analoog aan Alpaca.

**Out of scope (v1)**

- Repo’s mergen / gedeelde monorepo.
- Strategie-unificatie of parameter-sync automation.
- Nightly cross-repo CI compare.

## Access / blockers (audit 2026-08-22)

| Bron | Status | Opmerking |
|------|--------|-----------|
| Alpaca `data/alpaca_trades.jsonl` | ✅ | 574 fills, t/m 22 aug |
| Alpaca `.env` (API keys) | ✅ lokaal | Optioneel voor API-export |
| Kraken code + settings | ✅ | Zelfde range-params als Alpaca |
| Kraken `kraken_*.jsonl` lokaal | ❌ | Ontbreekt |
| Kraken Actions artifacts | ❌ | `gh` niet ingelogd; retention 7 dagen |
| Kraken `.env` (API keys) | ✅ lokaal | Nodig voor historie-pull als artifacts weg zijn |
| Kraken state | ⚠️ leeg | `.kraken_trade_state.json` zonder entries |

**Conclusie:** diagnose kan pas starten nadat Kraken-fills binnen zijn (API-pull met lokale `.env`, of gebruiker downloadt artifact / `gh auth login`).

## Data-model (common schema)

Eén genormaliseerde rij per fill:

| Veld | Type | Bron |
|------|------|------|
| `venue` | `alpaca` \| `kraken` | loader |
| `timestamp` | UTC ISO | fill time |
| `symbol` | `BASE/USD` | genormaliseerd |
| `side` | `buy` \| `sell` | |
| `qty` | float | |
| `price` | float | |
| `fee_usd` | float \| null | Kraken: exchange; Alpaca paper: 0 of fictief model |
| `portfolio_usd` | float \| null | indien gelogd |
| `trade_id` | string | dedupe-sleutel |
| `entry_price` | float \| null | bij sell, indien bekend |
| `profit_usd` | float \| null | netto indien bekend |

Loaders mappen:

- Alpaca: `data/alpaca_trades.jsonl` (`order_id`, `profit` / `portfolio_value`, …).
- Kraken audit: `kraken_bot_trades.jsonl` (`trade_id`, `exchange_fee_usd`, `portfolio_value_usd`, …).
- Kraken journal: `kraken_trades.jsonl` (via `log_trade`).

## Architectuur

```
Kraken-repo                     Alpaca-repo
───────────                     ───────────
data/kraken_trades.jsonl   ──►  metrics/kraken_compare/
(of API export / artifact)      ├── load_alpaca.py
                                ├── load_kraken.py
                                ├── normalize.py
                                ├── metrics.py
                                └── cli.py
                                        │
                                        ▼
                                metrics/output/
                                  kraken_compare_summary.md
                                  kraken_compare_*.csv/json
```

CLI (voorstel):

```bash
python -m metrics.kraken_compare \
  --alpaca data/alpaca_trades.jsonl \
  --kraken /pad/naar/kraken_bot_trades.jsonl \
  --start 2026-05-15 --end 2026-08-22
```

Optioneel in Kraken-repo of via env:

```bash
python -m metrics.kraken_compare.pull_kraken --since 2026-05-15
# schrijft metrics/output/kraken_fills_api.jsonl (gitignore)
```

## Diagnose-stappen (eenmalig)

1. **Kraken fills binnenhalen** (API of artifact).
2. **Overlapperiode** vastleggen (UTC); noteer startkapitaal (~$1000 paper vs ~$500 live).
3. **Parameter-diff** `bot_live/config.py` ↔ `src/rangebot/config/settings.py`.
4. **Metrics naast elkaar:** equity/return %, maand-PnL, #fills, win-rate, fees paid, top symbolen.
5. **Uitvoeringsgap:** fills die Alpaca wél heeft in venster X waar Kraken mist (of partial); avg hold-time; slippage vs limit.
6. **Conclusie:** fees vs fill-rate vs sizing vs downtime — gewogen oordeel.

## Persistente Kraken-logs (Kraken-repo)

Spiegel Alpaca-patroon:

- Append-only `data/kraken_bot_trades.jsonl` (dedupe op `trade_id`).
- CI: na run mergen + commit terug (of langer artifact + periodieke sync).
- Zonder dit blijft compare afhankelijk van 7-dagen artifacts / API-lookback.

## Success criteria

- [ ] Zelfde UTC-periode, common schema, één summary.md.
- [ ] Relatieve returns (niet alleen absolute $) gerapporteerd.
- [ ] Fees expliciet gescheiden (Alpaca paper ≈ 0 vs Kraken exchange fees).
- [ ] Diagnose noemt top 1–3 oorzaken met bewijs uit de cijfers.
- [ ] `python -m metrics.kraken_compare …` herhaalbaar zonder handmatige spreadsheet.

## Risico’s

- **Paper ≠ live:** Alpaca vult limieten optimistisch; verschil is deels structureel.
- **Kapitaalverschil:** $500 vs $1000 → absolute PnL niet 1:1; gebruik %.
- **Incomplete Kraken historie:** API-lookback / cache-verlies → onder-rapportage fills.
- **Secrets:** API-calls alleen lokaal via bestaande `.env`; nooit keys in output/commits.

## Implementatievolgorde (na goedkeuring plan)

1. Kraken fills pull/export + opslaan onder `metrics/output/` (gitignored).
2. `metrics/kraken_compare` package (normalize + metrics + CLI).
3. Eerste diagnose-rapport.
4. Kraken-repo: `data/` persist + CI-merge (aparte PR daar).
