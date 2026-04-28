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
