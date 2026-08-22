# Metrics

Hier staat tooling om **`trades.jsonl`** (EUR/Bitvavo) naar CSV te exporteren en korte stats te tonen.

| Pad | Inhoud |
|-----|--------|
| **`bitvavo_compare/`** | Python-package: `journal-export`, `metrics` |
| **`output/`** | Standaarduitvoer (CSV/markdown); inhoud staat onder `.gitignore` |

```bash
python -m metrics.bitvavo_compare journal-export --start 2026-03-01 --end 2026-03-31
python -m metrics.bitvavo_compare metrics metrics/output/bitvavo_journal.csv --label Bitvavo
```

Details: [`bitvavo_compare/README.md`](bitvavo_compare/README.md).

### Run-audits Alpaca vs Bitvavo (levels, stats per uur)

Bron: repo-root **`alpaca_runs.jsonl`** en **`bitvavo_runs.jsonl`** (geschreven door de bots).

```bash
python -m metrics.run_compare --days 14
python -m metrics.run_compare --start 2026-04-01 --end 2026-04-30
```

Uitvoer onder **`metrics/output/`** (gitignored behalve `.gitkeep`):

- **`run_compare_summary.md`** — leesbare vergelijking
- **`run_compare_timeline.json`** — volledige runs in het venster + totalen

### Alleen Bitvavo (EUR) — volledige historie voor analyse

```bash
python -m metrics.export_bitvavo_trades
```

De Bitvavo-bot schrijft fills naar **`bitvavo_trades.jsonl`** (repo-root); GitHub Actions cached dat bestand tussen runs (`trade_bitvavo.yml`). Het script merged ook **`trades.jsonl`** als die nog EUR-regels heeft (legacy/local mix). Export filtert op **`*/EUR`**.

Output (`.gitignore`, niet committen):

- **`metrics/output/bitvavo_all_trades.json`**
- **`metrics/output/bitvavo_all_trades.csv`**

Eigen journal-bestand:

```bash
python -m metrics.export_bitvavo_trades --trades /pad/naar/bitvavo_trades.jsonl
```

### Alle trades (Alpaca + Bitvavo gemengd)

```bash
python -m metrics.export_all_trades
```

Schrijft **`metrics/output/all_trades.json`** en **`all_trades.csv`** zonder filter.

### Alpaca vs Kraken (USD range)

```bash
# Optioneel: pulls fills via sibling Kraken-bot .env → metrics/output/kraken_fills_api.jsonl
python -m metrics.kraken_compare.pull_kraken --since 2026-05-01

# Of gebruik de persistente log uit de Kraken-repo (na CI export):
#   ../Kraken\ bot\ 500\ eu\ 15\ mei/data/kraken_trades.jsonl

python -m metrics.kraken_compare \
  --kraken "../Kraken bot 500 eu 15 mei/data/kraken_trades.jsonl" \
  --start 2026-07-16 --end 2026-08-22 \
  --alpaca-equity 1494.69 --kraken-equity 535.44
```

Zie `metrics/kraken_compare/` en `docs/superpowers/specs/2026-08-22-alpaca-kraken-compare-design.md`.
