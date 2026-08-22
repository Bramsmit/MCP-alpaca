"""CLI: Alpaca vs Kraken fill comparison."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .load_alpaca import load_alpaca_jsonl
from .load_kraken import load_kraken_jsonl
from .metrics import compare_venues, fifo_realized, write_json, write_normalized_csv
from .schema import parse_ts


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _parse_bound(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    dt = parse_ts(value if "T" in value else f"{value}T00:00:00+00:00")
    if dt is None:
        raise SystemExit(f"Ongeldige datum: {value}")
    if end_of_day and "T" not in value:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def cmd_compare(args: argparse.Namespace) -> int:
    start = _parse_bound(args.start)
    end = _parse_bound(args.end, end_of_day=True)
    alpaca_path = Path(args.alpaca).expanduser().resolve()
    kraken_path = Path(args.kraken).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    alpaca_fills = load_alpaca_jsonl(alpaca_path, start=start, end=end)
    kraken_fills = load_kraken_jsonl(kraken_path, start=start, end=end)

    a_stats = fifo_realized(alpaca_fills)
    k_stats = fifo_realized(kraken_fills)

    md = compare_venues(
        a_stats,
        k_stats,
        alpaca_start_capital=args.alpaca_start,
        kraken_start_capital=args.kraken_start,
        alpaca_equity_now=args.alpaca_equity,
        kraken_equity_now=args.kraken_equity,
    )

    # Extra context block
    extra = [
        "",
        "## Bronnen",
        "",
        f"- Alpaca: `{alpaca_path}` ({len(alpaca_fills)} fills in venster)",
        f"- Kraken: `{kraken_path}` ({len(kraken_fills)} fills in venster)",
        f"- Venster: `{args.start or '…'}` → `{args.end or '…'}` UTC",
        "",
        "### Alpaca top symbolen (net)",
        "",
    ]
    for sym, s in list(a_stats["by_symbol"].items())[:8]:
        extra.append(
            f"- {sym}: n={s['n']} net=${float(s['net']):.2f} "
            f"gross=${float(s['gross']):.2f}"
        )
    extra.extend(["", "### Kraken top symbolen (net)", ""])
    for sym, s in list(k_stats["by_symbol"].items())[:8]:
        extra.append(
            f"- {sym}: n={s['n']} net=${float(s['net']):.2f} "
            f"gross=${float(s['gross']):.2f} fees_in_lots≈"
            f"${float(s['fees']):.2f}"
        )
    md = md + "\n".join(extra) + "\n"

    summary_path = out_dir / "kraken_compare_summary.md"
    summary_path.write_text(md, encoding="utf-8")
    write_normalized_csv(out_dir / "kraken_compare_alpaca.csv", alpaca_fills)
    write_normalized_csv(out_dir / "kraken_compare_kraken.csv", kraken_fills)
    write_json(
        out_dir / "kraken_compare_stats.json",
        {"alpaca": a_stats, "kraken": k_stats},
    )

    print(md)
    print(f"\nGeschreven: {summary_path}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    root = _repo_root()
    p = argparse.ArgumentParser(
        description="Vergelijk Alpaca paper fills met Kraken live fills.",
    )
    p.add_argument(
        "--alpaca",
        default=str(root / "data" / "alpaca_trades.jsonl"),
        help="Pad naar alpaca_trades.jsonl",
    )
    p.add_argument(
        "--kraken",
        default=str(root / "metrics" / "output" / "kraken_fills_api.jsonl"),
        help="Pad naar Kraken JSONL (API-export of bot journal)",
    )
    p.add_argument("--start", default=None, help="Start UTC YYYY-MM-DD")
    p.add_argument("--end", default=None, help="Einde UTC YYYY-MM-DD")
    p.add_argument(
        "--output-dir",
        default=str(root / "metrics" / "output"),
        help="Output directory (gitignored)",
    )
    p.add_argument("--alpaca-start", type=float, default=1000.0)
    p.add_argument("--kraken-start", type=float, default=500.0)
    p.add_argument("--alpaca-equity", type=float, default=None)
    p.add_argument("--kraken-equity", type=float, default=None)
    p.set_defaults(func=cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
