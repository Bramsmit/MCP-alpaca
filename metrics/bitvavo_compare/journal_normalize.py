"""Lees trades.jsonl (en optioneel bitvavo_trades.jsonl); exporteer alleen EUR/Bitvavo-rijen."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_instant_utc(s: str) -> datetime:
    """Parse ISO timestamp; assume UTC if no tz."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_range(start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
    """--start/--end als '2026-03-01' of volledige ISO. Inclusief hele einddag voor date-only."""
    lo: datetime | None = None
    hi: datetime | None = None
    if start:
        if len(start) <= 10 and "T" not in start:
            lo = datetime.fromisoformat(start + "T00:00:00+00:00")
        else:
            lo = parse_instant_utc(start)
    if end:
        if len(end) <= 10 and "T" not in end:
            hi = datetime.fromisoformat(end + "T23:59:59.999999+00:00")
        else:
            hi = parse_instant_utc(end)
    return lo, hi


def _classify_quote(symbol: str) -> str | None:
    if "/" not in symbol:
        return None
    q = symbol.split("/", 1)[1].upper()
    if q in ("EUR",):
        return "EUR"
    return q


def base_asset(symbol: str) -> str:
    if "/" in symbol:
        return symbol.split("/", 1)[0].upper()
    return symbol.upper()


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
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


CSV_HEADERS = (
    "timestamp_utc",
    "symbol",
    "base_asset",
    "quote_ccy",
    "side",
    "qty",
    "price",
    "entry_price",
    "profit",
    "profit_pct",
    "order_id",
    "portfolio_value",
    "source_file",
)


def row_to_normalized(r: dict, source_path: Path) -> dict[str, object]:
    sym = str(r.get("symbol", ""))
    quote = _classify_quote(sym) or ""
    return {
        "timestamp_utc": r.get("timestamp", ""),
        "symbol": sym,
        "base_asset": base_asset(sym),
        "quote_ccy": quote,
        "side": str(r.get("side", "")).lower(),
        "qty": r.get("qty"),
        "price": r.get("price"),
        "entry_price": r.get("entry_price"),
        "profit": r.get("profit"),
        "profit_pct": r.get("profit_pct"),
        "order_id": r.get("order_id", ""),
        "portfolio_value": r.get("portfolio_value"),
        "source_file": source_path.name,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in CSV_HEADERS})


def merge_bitvavo_only(
    repo_root: Path,
    trades_path: Path | None,
    bitvavo_extra_path: Path | None,
    lo: datetime | None,
    hi: datetime | None,
) -> tuple[list[dict[str, object]], int]:
    """
    EUR-quote rows uit journals (Bitvavo-symbolen zoals BTC/EUR).

    Retourneert (bitvavo_rows, skipped_non_eur_count).
    """
    combined: list[tuple[dict, Path]] = []

    tp = trades_path or (repo_root / "trades.jsonl")
    combined.extend((r, tp) for r in load_jsonl(tp))

    if bitvavo_extra_path and bitvavo_extra_path.resolve() != tp.resolve():
        combined.extend((r, bitvavo_extra_path) for r in load_jsonl(bitvavo_extra_path))

    seen_order_side: set[tuple[str, str, str]] = set()
    deduped: list[tuple[dict, Path]] = []
    for r, src in combined:
        oid = str(r.get("order_id", ""))
        side = str(r.get("side", "")).lower()
        ts = str(r.get("timestamp", ""))
        if oid:
            key = (oid, side, ts)
            if key in seen_order_side:
                continue
            seen_order_side.add(key)
        deduped.append((r, src))

    filtered: list[tuple[dict, Path]] = []
    for r, src in deduped:
        ts = r.get("timestamp")
        if not ts:
            continue
        try:
            t = parse_instant_utc(str(ts))
        except (ValueError, TypeError):
            continue
        if lo is not None and t < lo:
            continue
        if hi is not None and t > hi:
            continue
        filtered.append((r, src))

    out: list[dict[str, object]] = []
    skipped_non_eur = 0

    for r, src in filtered:
        sym = str(r.get("symbol", ""))
        quote = _classify_quote(sym)
        norm = row_to_normalized(r, src)
        if quote == "EUR":
            out.append(norm)
        else:
            skipped_non_eur += 1

    return out, skipped_non_eur
