# Alpaca ↔ Kraken Compare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull Kraken live fills, build `metrics/kraken_compare`, and produce a first Alpaca-vs-Kraken diagnosis report.

**Architecture:** Normalize both venues to one fill schema in the Alpaca repo; load Alpaca from `data/alpaca_trades.jsonl` and Kraken from API export / JSONL; CLI writes gitignored `metrics/output/`.

**Tech Stack:** Python 3.11+, ccxt (Kraken pull via Kraken-bot `.env`), stdlib argparse/json/csv.

## Global Constraints

- Never commit secrets or `metrics/output/*` fills.
- Prefer relative returns (%) over absolute $ when capitals differ (~$1000 vs ~$500).
- Separate Alpaca paper (fee≈0) from Kraken exchange fees explicitly.

---

## File map

| Path | Role |
|------|------|
| `metrics/kraken_compare/__init__.py` | Package |
| `metrics/kraken_compare/schema.py` | Common fill dict + normalize helpers |
| `metrics/kraken_compare/load_alpaca.py` | Load Alpaca JSONL |
| `metrics/kraken_compare/load_kraken.py` | Load Kraken JSONL / API export rows |
| `metrics/kraken_compare/pull_kraken.py` | CLI helper: pull via ccxt using Kraken `.env` |
| `metrics/kraken_compare/metrics.py` | FIFO PnL, monthly, fees, compare tables |
| `metrics/kraken_compare/cli.py` | `python -m metrics.kraken_compare` |
| `metrics/kraken_compare/__main__.py` | Entry |
| `docs/superpowers/plans/2026-08-22-alpaca-kraken-compare.md` | This plan |

---

### Task 1: Pull Kraken fills via API

- [x] Load keys from Kraken-bot `.env` (not printed)
- [x] `fetch_my_trades` per SYMBOL_POOL since 2026-05-15 (paginate)
- [x] Write `metrics/output/kraken_fills_api.jsonl` (gitignored)
- [x] Verify row count > 0

### Task 2: `metrics/kraken_compare` package

- [x] schema + loaders + metrics + CLI
- [x] Smoke: load Alpaca sample + Kraken export, print summary

### Task 3: First diagnosis report

- [x] Run compare for overlap window
- [x] Write `metrics/output/kraken_compare_summary.md`
- [x] Summarize top causes for user (chat + canvas optional)

### Task 4: Kraken persist note (defer code in other repo if time)

- [x] Document follow-up: commit journals to `data/` in Kraken-bot (separate PR)
- [x] Implemented: `rangebot.live.export_trade_log` + CI commit in Kraken-bot repo
