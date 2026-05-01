"""
Append-only JSONL: één record per bot-run (niveaus, prijzen, stats, posities).

- bitvavo_runs.jsonl — Bitvavo range-bot (`bitvavo_trader`)
- alpaca_runs.jsonl — Alpaca range-bot (`bot_range_1000.live_trader`)

Vul aan naast bestaande fill-journals (bitvavo_trades.jsonl /
trades.jsonl) voor vergelijking en omdat de exchange-UI soms onhandig
is voor historie.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

BITVAVO_RUNS_JSONL = "bitvavo_runs.jsonl"
ALPACA_RUNS_JSONL = "alpaca_runs.jsonl"


def _audit_path(filename: str) -> Path:
    return _REPO_ROOT / filename


def log_run_audit(record: dict[str, Any], *, filename: str) -> None:
    """Schrijf één JSON-object per regel (UTF-8). Fout → log-warning."""
    row = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), **record}
    path = _audit_path(filename)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError as e:
        log.warning("Kon run-audit niet schrijven naar %s: %s", filename, e)


def load_run_audits(filename: str) -> list[dict[str, Any]]:
    """Lees alle run-auditregels uit repo-root (bestand mag ontbreken)."""
    path = _audit_path(filename)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
