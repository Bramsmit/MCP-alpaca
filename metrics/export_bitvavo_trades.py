#!/usr/bin/env python3
"""
Exporteer alleen Bitvavo-trades (symbol eindigt op /EUR) naar metrics/output/.

Bronnen (merge, dedupe):
  - <repo>/bitvavo_trades.jsonl — hoofdjournal Bitvavo-bot (idem CI-cache)
  - <repo>/trades.jsonl — alleen voor oude/local mixes met niet-EUR; EUR staat hier ook als je legacy kopieën hebt

Output (onder .gitignore, niet committen):
  - metrics/output/bitvavo_all_trades.json
  - metrics/output/bitvavo_all_trades.csv

Gebruik (repo-root):

    python -m metrics.export_bitvavo_trades

Optioneel eigen pad naar journal:

    python -m metrics.export_bitvavo_trades --trades pad/trades.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bitvavo_compare.journal_normalize import merge_bitvavo_only, write_csv

_REPO = Path(__file__).resolve().parent.parent
_DEFAULT_OUT = _REPO / "metrics" / "output"


def main() -> int:
    p = argparse.ArgumentParser(description="Export Bitvavo journal (EUR) naar JSON + CSV.")
    p.add_argument(
        "--trades",
        default="",
        help="Pad naar trades.jsonl (default: <repo>/trades.jsonl).",
    )
    p.add_argument(
        "--bitvavo-journal",
        default="",
        help=(
            "Extra pad bv. bitvavo_trades.jsonl "
            "(default: repo/bitvavo_trades.jsonl als aanwezig)."
        ),
    )
    p.add_argument(
        "--output-dir",
        default=str(_DEFAULT_OUT),
        help=f"Map voor uitvoer (default: {_DEFAULT_OUT}).",
    )
    args = p.parse_args()

    ts = str(args.trades).strip()
    bs = str(args.bitvavo_journal).strip()
    tp = Path(ts).resolve() if ts else None
    if bs:
        bp = Path(bs).resolve()
    else:
        extra = _REPO / "bitvavo_trades.jsonl"
        bp = extra if extra.exists() else None

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, skipped_other = merge_bitvavo_only(_REPO, tp, bp, None, None)

    json_path = out_dir / "bitvavo_all_trades.json"
    csv_path = out_dir / "bitvavo_all_trades.csv"

    json_path.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    write_csv(csv_path, rows)

    print(f"Bitvavo (EUR): {len(rows)} rijen")
    print(f"  → {json_path}")
    print(f"  → {csv_path}")
    if skipped_other:
        print(
            f"Overgeslagen niet-EUR symbolen in journal: {skipped_other}",
            file=sys.stderr,
        )

    src = tp or (_REPO / "trades.jsonl")
    if not src.exists() and not (bp and bp.exists()):
        print(
            "\nGeen trades.jsonl (of alleen lege bronnen). Kopieer journal naar "
            "de repo-root (trades.jsonl / bitvavo_trades.jsonl) en probeer opnieuw.",
            file=sys.stderr,
        )
    elif not rows:
        print(
            "\nGeen EUR-trades gevonden in de gekozen bestanden.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
