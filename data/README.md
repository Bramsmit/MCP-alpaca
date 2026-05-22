# data/

Persistente trade-logs voor de Alpaca paper-bot. Automatisch bijgewerkt door GitHub Actions na elke run.

| Bestand | Inhoud |
|---|---|
| `alpaca_trades.jsonl` | Alle gevulde trades (JSONL, append-only, deduped op order_id) |
| `alpaca_trades.csv` | Zelfde data als CSV voor eenvoudige evaluatie in Excel/Numbers |

## Kolommen (CSV / JSONL)

| Kolom | Uitleg |
|---|---|
| `timestamp` | Tijdstip waarop de fill geregistreerd werd (UTC ISO-8601) |
| `order_id` | Alpaca order-ID (unieke sleutel voor dedup) |
| `symbol` | Handelspaar, bijv. `DOT/USD` |
| `side` | `buy` of `sell` |
| `qty` | Gevulde hoeveelheid |
| `price` | Gemiddelde vulprijs |
| `entry_price` | Gemiddelde inkoop (alleen bij sell, voor PnL-berekening) |
| `notional_usd` | Handelsvolume in USD (qty × price) |
| `profit_usd` | Netto winst/verlies na fictieve fees (alleen bij sell) |
| `profit_pct` | Rendement t.o.v. kostbasis (%) |
| `portfolio_value_usd` | Totale portfoliowaarde op moment van fill |
| `fee_model` | Beschrijving van het gehanteerde fee-model |

## Bron

CI leest `trades.jsonl` uit de workspace (nieuw per run), merged het met `data/alpaca_trades.jsonl` uit de repo, dedupliceert op `order_id`, en commit het resultaat terug.
