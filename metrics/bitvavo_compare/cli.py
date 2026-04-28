"""CLI: Bitvavo journal normaliseren en metrics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .journal_normalize import merge_bitvavo_only, parse_range, write_csv
from .metrics_summary import format_summary_md, load_rows, summarize_label


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def cmd_journal_export(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    lo, hi = parse_range(args.start, args.end)
    out_dir = Path(args.output_dir).resolve()
    ts = str(args.trades).strip()
    bs = str(args.bitvavo_journal).strip()
    tp = Path(ts).resolve() if ts else None
    bp = Path(bs).resolve() if bs else None

    rows, skipped_other = merge_bitvavo_only(root, tp, bp, lo, hi)

    out_path = out_dir / str(args.output_filename).strip()
    write_csv(out_path, rows)
    print(f"Geschreven: {out_path} ({len(rows)} EUR-rijen)")
    if skipped_other:
        print(
            f"Overgeslagen (niet-EUR symbolen in journal): {skipped_other}",
            file=sys.stderr,
        )
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    paths = [Path(p).resolve() for p in args.csv]
    labels = list(args.label or [])
    tables = []
    for i, p in enumerate(paths):
        label = labels[i] if i < len(labels) else p.stem
        tables.append(summarize_label(label, load_rows(p)))
    md = format_summary_md(tables)
    print(md)
    if args.output_md:
        Path(args.output_md).write_text(md, encoding="utf-8")
        print(f"\nOpgeslagen: {args.output_md}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Bitvavo: journal (JSONL) → CSV en eenvoudige metrics.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser(
        "journal-export",
        help="Lees trades.jsonl, houd alleen */EUR — schrijf genormaliseerde CSV.",
    )
    s1.add_argument(
        "--repo-root",
        default=str(_repo_root()),
        help="Root van de repo (default: automatisch).",
    )
    s1.add_argument(
        "--trades",
        default="",
        help="Pad naar trades.jsonl (default: <repo>/trades.jsonl).",
    )
    s1.add_argument(
        "--bitvavo-journal",
        default="",
        help="Extra bestand bv. bitvavo_trades.jsonl (merge met --trades).",
    )
    s1.add_argument("--start", default=None, help="Start UTC: 2026-03-01 of ISO8601.")
    s1.add_argument("--end", default=None, help="Einde UTC: 2026-03-31 of ISO8601.")
    s1.add_argument(
        "--output-dir",
        default="metrics/output",
        help="Uitvoermap (default: metrics/output).",
    )
    s1.add_argument(
        "--output-filename",
        default="bitvavo_journal.csv",
        help="Bestandsnaam in output-dir.",
    )
    s1.set_defaults(func=cmd_journal_export)

    s2 = sub.add_parser(
        "metrics",
        help="Tel buys/sells en PnL-schatting uit genormaliseerde CSV ('journal-export').",
    )
    s2.add_argument(
        "csv",
        nargs="+",
        help="Eén of meer CSV's.",
    )
    s2.add_argument(
        "--label",
        action="append",
        default=[],
        help="Optioneel label per CSV (herhaal per file).",
    )
    s2.add_argument("--output-md", default="", help="Schrijf markdown naar dit pad.")
    s2.set_defaults(func=cmd_metrics)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
