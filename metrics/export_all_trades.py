#!/usr/bin/env python3
"""
Exporteer <repo>/trades.jsonl naar metrics/output/ als JSON + CSV.

Gebruik (repo-root):

    python -m metrics.export_all_trades

Als `trades.jsonl` ontbreekt: lege bestanden + korte melding op stderr.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_JOURNAL = _REPO / "trades.jsonl"
_OUT_DIR = _REPO / "metrics" / "output"

_CSV_FIELDS = (
    "timestamp",
    "order_id",
    "symbol",
    "side",
    "qty",
    "price",
    "entry_price",
    "profit",
    "profit_pct",
    "portfolio_value",
)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> int:
    trades = _load_jsonl(_JOURNAL)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = _OUT_DIR / "all_trades.json"
    csv_path = _OUT_DIR / "all_trades.csv"

    json_path.write_text(json.dumps(trades, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in trades:
            row = {k: r.get(k, "") for k in _CSV_FIELDS}
            w.writerow(row)

    print(f"Bron: {_JOURNAL}")
    print(f"  → {json_path} ({len(trades)} trades)")
    print(f"  → {csv_path}")
    if not _JOURNAL.exists():
        print(
            "\nGeen trades.jsonl gevonden — kopieer het bestand van je machine/CI "
            "naar de repo-root en draai dit commando opnieuw.",
            file=sys.stderr,
        )
    elif not trades:
        print("\ntrades.jsonl is leeg.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
