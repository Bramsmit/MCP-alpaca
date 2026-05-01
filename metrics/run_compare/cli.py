"""CLI: vergelijk alpaca_runs.jsonl en bitvavo_runs.jsonl."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .load_export import (
    build_report,
    filter_by_window,
    load_jsonl,
    repo_root_from_here,
    write_outputs,
)


def _parse_utc_date(s: str) -> datetime:
    """2026-04-01 of 2026-04-01T00:00:00."""
    s = s.strip()
    if "T" in s:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    d = datetime.fromisoformat(s + "T00:00:00")
    return d.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Vergelijk hourly run-audits: alpaca_runs.jsonl vs "
            "bitvavo_runs.jsonl. Schrijft naar metrics/output/ "
            "(run_compare_summary.md + run_compare_timeline.json)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=str,
        default="",
        help="Repo-root (default: boven metrics/).",
    )
    parser.add_argument(
        "--days",
        type=float,
        default=7.0,
        help=(
            "Venster: laatste N dagen UTC (default 7). "
            "Genegeerd als --start/--end gezet."
        ),
    )
    parser.add_argument(
        "--start",
        type=str,
        default="",
        help="Start UTC (2026-04-01).",
    )
    parser.add_argument(
        "--end",
        type=str,
        default="",
        help="Einde UTC (2026-04-30). Default: nu.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimale stdout (alleen paden).",
    )
    args = parser.parse_args(argv)

    root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else repo_root_from_here()
    )
    alpaca_path = root / "alpaca_runs.jsonl"
    bitvavo_path = root / "bitvavo_runs.jsonl"
    out_dir = root / "metrics" / "output"

    end = _parse_utc_date(args.end) if args.end else datetime.now(timezone.utc)
    if args.start:
        start = _parse_utc_date(args.start)
    else:
        start = end - timedelta(days=float(args.days))

    if start > end:
        print("Fout: --start na --end", file=sys.stderr)
        return 2

    alpaca_all = load_jsonl(alpaca_path)
    bitvavo_all = load_jsonl(bitvavo_path)
    alpaca_f = filter_by_window(alpaca_all, start, end)
    bitvavo_f = filter_by_window(bitvavo_all, start, end)

    report = build_report(alpaca_f, bitvavo_f, start, end)
    md_path, json_path = write_outputs(report, out_dir)

    if not args.quiet:
        print(
            f"Alpaca runs in venster: {len(alpaca_f)} "
            f"(totaal in bestand: {len(alpaca_all)})"
        )
        print(
            f"Bitvavo runs in venster: {len(bitvavo_f)} "
            f"(totaal in bestand: {len(bitvavo_all)})"
        )
        print(f"Markdown: {md_path}")
        print(f"JSON:     {json_path}")
    else:
        print(md_path)
        print(json_path)

    if not alpaca_all and not bitvavo_all:
        print(
            "Waarschuwing: geen bronbestanden of leeg — run de bots eerst om "
            "JSONL te vullen.",
            file=sys.stderr,
        )
    return 0
