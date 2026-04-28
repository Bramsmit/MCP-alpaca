# Bitvavo — journal export en metrics

Leest `trades.jsonl` (projectroot) en optioneel een tweede JSONL (`bitvavo_trades.jsonl`), filtert op **EUR-paren** (Bitvavo, bv. `BTC/EUR`), schrijft een genormaliseerde **CSV** onder **`metrics/output/`**. Commando `metrics` geeft een korte markdown-samenvatting.

Zie ook [`docs/PLAN_ALPACA_VS_BITVAVO_VERGELIJKING.md`](../../docs/PLAN_ALPACA_VS_BITVAVO_VERGELIJKING.md) (§8).

## Setup

```bash
cd "/pad/naar/deze-repo"
pip install -r bot_live/requirements.txt
```

## Commands

### `journal-export`

```bash
python -m metrics.bitvavo_compare journal-export \
  --start 2026-03-01 \
  --end 2026-03-31 \
  --output-dir metrics/output
```

Standaard uitvoer: **`metrics/output/bitvavo_journal.csv`**.  
Rijen met andere quote dan EUR (bv. Alpaca `*/USD` in hetzelfde `trades.jsonl`) worden **overgeslagen**; aantal wordt op stderr getoond.

Optioneel:

- `--trades /pad/trades.jsonl`
- `--bitvavo-journal /pad/bitvavo_trades.jsonl` (merge met trades, dedupe op order_id)

### `metrics`

```bash
python -m metrics.bitvavo_compare metrics metrics/output/bitvavo_journal.csv \
  --label "Bitvavo" \
  --output-md metrics/output/bitvavo_summary.md
```

## Help

```bash
python -m metrics.bitvavo_compare --help
python -m metrics.bitvavo_compare journal-export --help
```

*Voor volledige historie: gebruik altijd Bitvavo order/trade-export naast dit journal.*
