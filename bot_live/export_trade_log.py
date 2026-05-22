"""
Persistente trade-log voor Alpaca paper-bot.

Leest trades.jsonl (werkbestand CI/lokaal) en de bestaande data/alpaca_trades.jsonl
(versioned in repo), merged ze op order_id en schrijft:
  - data/alpaca_trades.jsonl  (canonieke log, deduped)
  - data/alpaca_trades.csv    (zelfde data als CSV voor evaluatie)

Gebruik:
    python -m bot_live.export_trade_log
    python -m bot_live.export_trade_log --source trades.jsonl
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _REPO_ROOT / "data"
_PERSISTENT_JSONL = _DATA_DIR / "alpaca_trades.jsonl"
_PERSISTENT_CSV = _DATA_DIR / "alpaca_trades.csv"

CSV_FIELDS = [
    "timestamp",
    "order_id",
    "symbol",
    "side",
    "qty",
    "price",
    "entry_price",
    "notional_usd",
    "profit_usd",
    "profit_pct",
    "portfolio_value_usd",
    "fee_model",
]

_FEE_MODEL = "maker 0.15% + $0.25 vast per zijde (fictief Bitvavo-model)"


def _enrich(record: dict) -> dict:
    """Voeg berekende velden toe als ze ontbreken."""
    qty = float(record.get("qty") or 0)
    price = float(record.get("price") or 0)
    out = dict(record)
    if "notional_usd" not in out:
        out["notional_usd"] = round(qty * price, 4) if qty and price else None
    if "profit_usd" not in out:
        out["profit_usd"] = record.get("profit")
    if "fee_model" not in out:
        out["fee_model"] = _FEE_MODEL
    # Zorg dat profit_pct aanwezig is
    if "profit_pct" not in out:
        out["profit_pct"] = record.get("profit_pct")
    return out


def _load_jsonl(path: Path) -> dict[str, dict]:
    """Laad JSONL → dict geïndexeerd op order_id (dupes: laatste wint)."""
    result: dict[str, dict] = {}
    if not path.exists():
        return result
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                oid = str(rec.get("order_id") or "")
                if oid:
                    result[oid] = rec
            except json.JSONDecodeError:
                continue
    return result


def merge_and_export(source_jsonl: Path | None = None) -> int:
    """
    Merge source_jsonl (nieuw) met persistente log (repo).
    Retourneert aantal nieuw toegevoegde trades.
    """
    if source_jsonl is None:
        source_jsonl = _REPO_ROOT / "trades.jsonl"

    persistent = _load_jsonl(_PERSISTENT_JSONL)
    new_records = _load_jsonl(source_jsonl)

    added = 0
    for oid, rec in new_records.items():
        if oid not in persistent:
            persistent[oid] = _enrich(rec)
            added += 1

    # Sorteren op timestamp
    sorted_records = sorted(
        persistent.values(),
        key=lambda r: r.get("timestamp") or "",
    )

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # JSONL schrijven
    with _PERSISTENT_JSONL.open("w", encoding="utf-8") as f:
        for rec in sorted_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # CSV schrijven
    with _PERSISTENT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=CSV_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        for rec in sorted_records:
            enriched = _enrich(rec)
            writer.writerow({k: enriched.get(k, "") for k in CSV_FIELDS})

    total = len(sorted_records)
    print(
        f"export_trade_log: {total} trades totaal, {added} nieuw toegevoegd"
        f" → {_PERSISTENT_JSONL.relative_to(_REPO_ROOT)}"
        f" + {_PERSISTENT_CSV.relative_to(_REPO_ROOT)}"
    )
    return added


if __name__ == "__main__":
    source = None
    args = sys.argv[1:]
    if "--source" in args:
        idx = args.index("--source")
        if idx + 1 < len(args):
            source = Path(args[idx + 1])

    added = merge_and_export(source)
    sys.exit(0)
