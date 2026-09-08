#!/usr/bin/env python3
"""
Reconstrueer per-trade PnL uit het Alpaca-journal met FIFO-matching.

De bot vult `profit_usd` alleen als hij de entry zelf nog in zijn state had
staan; na een herstart of cache-miss blijft dat veld leeg. Van de sells in
`data/alpaca_trades.jsonl` heeft daardoor maar een deel een PnL, waardoor
win-rate en gemiddelde winst uit het journal niet te vertrouwen zijn.

Dit script koppelt elke sell FIFO aan eerdere buys van hetzelfde symbool en
rekent bruto en netto door met het fee-model uit `bot_live.config`
(vast bedrag per zijde + maker-%). Sells zonder bijbehorende buy (positie
geopend voor het begin van het journal) worden apart gerapporteerd in plaats
van meegeteld.

Gebruik (repo-root):

    python -m metrics.fifo_pnl
    python -m metrics.fifo_pnl --start 2026-07-01
    python -m metrics.fifo_pnl --symbol UNI/USD
    python -m metrics.fifo_pnl --journal data/alpaca_trades.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

from bot_live.config import (
    ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD,
    BITVAVO_MAKER_FEE_RATE,
)

_REPO = Path(__file__).resolve().parent.parent
_JOURNAL = _REPO / "data" / "alpaca_trades.jsonl"
_OUT_DIR = _REPO / "metrics" / "output"

# Onder deze fractie van de oorspronkelijke lot-grootte is het restje dust:
# Alpaca laat bij een verkoop vaak een paar duizendste munt staan.
_DUST_FRACTION = 1e-6

_CSV_FIELDS = (
    "symbol",
    "buy_time",
    "sell_time",
    "hold_hours",
    "qty",
    "buy_price",
    "sell_price",
    "gross_usd",
    "fees_usd",
    "net_usd",
    "net_pct",
    "journal_profit_usd",
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


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _side_fee_usd(notional_usd: float, qty_fraction: float = 1.0) -> float:
    """
    Kosten van één zijde: maker-% over de notional + vast bedrag per fill.

    Bij een gedeeltelijke match schaalt het vaste bedrag mee met
    `qty_fraction`, zodat één fill zijn $0,25 niet meerdere keren afdraagt.
    """
    pct_part = abs(notional_usd) * BITVAVO_MAKER_FEE_RATE
    fixed_part = ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD * qty_fraction
    return pct_part + fixed_part


def match_fifo(rows: list[dict]) -> dict:
    """
    Koppel sells FIFO aan buys per symbool.

    Retourneert round-trips, sells zonder buy en de lots die aan het eind nog
    openstaan. `rows` moet chronologisch zijn.
    """
    lots: dict[str, deque] = {}
    round_trips: list[dict] = []
    unmatched: list[dict] = []

    for row in rows:
        symbol = row.get("symbol")
        side = str(row.get("side", "")).lower()
        qty = float(row.get("qty") or 0)
        price = float(row.get("price") or 0)
        if not symbol or qty <= 0 or price <= 0:
            continue

        if side == "buy":
            lots.setdefault(symbol, deque()).append(
                {
                    "qty_open": qty,
                    "qty_original": qty,
                    "price": price,
                    "timestamp": row.get("timestamp"),
                }
            )
            continue

        if side != "sell":
            continue

        remaining = qty
        sell_notional_total = qty * price
        queue = lots.setdefault(symbol, deque())

        while remaining > 0 and queue:
            lot = queue[0]
            matched = min(remaining, lot["qty_open"])
            if matched <= 0:
                queue.popleft()
                continue

            buy_notional = matched * lot["price"]
            sell_notional = matched * price
            gross = sell_notional - buy_notional

            buy_fee = _side_fee_usd(
                buy_notional, matched / lot["qty_original"]
            )
            sell_fee = _side_fee_usd(sell_notional, matched / qty)
            fees = buy_fee + sell_fee

            buy_ts = _parse_ts(lot["timestamp"])
            sell_ts = _parse_ts(row.get("timestamp"))
            hold_hours = (
                (sell_ts - buy_ts).total_seconds() / 3600
                if buy_ts and sell_ts
                else None
            )

            round_trips.append(
                {
                    "symbol": symbol,
                    "buy_time": lot["timestamp"],
                    "sell_time": row.get("timestamp"),
                    "hold_hours": hold_hours,
                    "qty": matched,
                    "buy_price": lot["price"],
                    "sell_price": price,
                    "buy_notional_usd": buy_notional,
                    "sell_notional_usd": sell_notional,
                    "gross_usd": gross,
                    "fees_usd": fees,
                    "net_usd": gross - fees,
                    "net_pct": (
                        (gross - fees) / buy_notional * 100
                        if buy_notional
                        else 0.0
                    ),
                    "journal_profit_usd": row.get("profit_usd"),
                }
            )

            lot["qty_open"] -= matched
            remaining -= matched
            if lot["qty_open"] <= lot["qty_original"] * _DUST_FRACTION:
                queue.popleft()

        if remaining > 1e-12:
            unmatched.append(
                {
                    "symbol": symbol,
                    "timestamp": row.get("timestamp"),
                    "qty_unmatched": remaining,
                    "price": price,
                    "notional_usd": remaining * price,
                    "sell_notional_total_usd": sell_notional_total,
                }
            )

    open_lots = [
        {
            "symbol": symbol,
            "timestamp": lot["timestamp"],
            "qty_open": lot["qty_open"],
            "price": lot["price"],
            "notional_usd": lot["qty_open"] * lot["price"],
        }
        for symbol, queue in lots.items()
        for lot in queue
        if lot["qty_open"] > 0
    ]

    return {
        "round_trips": round_trips,
        "unmatched_sells": unmatched,
        "open_lots": open_lots,
    }


def summarize(round_trips: list[dict]) -> dict:
    """Totalen en win-rate over de gekoppelde round-trips."""
    if not round_trips:
        return {"n": 0}

    nets = [r["net_usd"] for r in round_trips]
    gross = sum(r["gross_usd"] for r in round_trips)
    fees = sum(r["fees_usd"] for r in round_trips)
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    holds = [
        r["hold_hours"] for r in round_trips if r["hold_hours"] is not None
    ]
    pcts = sorted(r["net_pct"] for r in round_trips)
    mid = len(pcts) // 2
    median_pct = (
        pcts[mid] if len(pcts) % 2 else (pcts[mid - 1] + pcts[mid]) / 2
    )

    return {
        "n": len(round_trips),
        "gross_usd": gross,
        "fees_usd": fees,
        "net_usd": gross - fees,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(round_trips) * 100,
        "avg_win_usd": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss_usd": sum(losses) / len(losses) if losses else 0.0,
        "best_usd": max(nets),
        "worst_usd": min(nets),
        "median_net_pct": median_pct,
        "avg_hold_hours": sum(holds) / len(holds) if holds else None,
    }


def _per_symbol(round_trips: list[dict]) -> list[dict]:
    by_symbol: dict[str, list[dict]] = {}
    for r in round_trips:
        by_symbol.setdefault(r["symbol"], []).append(r)
    rows = [
        {"symbol": sym, **summarize(trips)} for sym, trips in by_symbol.items()
    ]
    rows.sort(key=lambda r: r["net_usd"], reverse=True)
    return rows


def _print_report(
    result: dict, journal_profit_count: int, n_rows: int
) -> None:
    trips = result["round_trips"]
    total = summarize(trips)

    print(f"Journal: {n_rows} fills")
    if total["n"] == 0:
        print("Geen round-trips te koppelen.")
        return

    print(
        f"FIFO-round-trips: {total['n']} "
        f"(journal had {journal_profit_count} sells met eigen PnL)"
    )
    print()
    print(f"  Netto:      ${total['net_usd']:+.2f}")
    print(f"  Bruto:      ${total['gross_usd']:+.2f}")
    print(f"  Fees:       ${total['fees_usd']:.2f}")
    print(
        f"  Win-rate:   {total['win_rate_pct']:.1f}% "
        f"({total['wins']} winst / {total['losses']} verlies)"
    )
    print(
        f"  Gem. winst: ${total['avg_win_usd']:+.2f} | "
        f"gem. verlies: ${total['avg_loss_usd']:+.2f}"
    )
    print(
        f"  Beste:      ${total['best_usd']:+.2f} | "
        f"slechtste: ${total['worst_usd']:+.2f}"
    )
    print(f"  Mediaan:    {total['median_net_pct']:+.2f}% per trade")
    if total["avg_hold_hours"] is not None:
        print(f"  Houdduur:   {total['avg_hold_hours']:.1f}h gemiddeld")

    print()
    print(f"{'symbool':<10} {'trips':>6} {'netto':>10} {'win-rate':>9}")
    print("-" * 39)
    for row in _per_symbol(trips):
        print(
            f"{row['symbol']:<10} {row['n']:>6} "
            f"{row['net_usd']:>+10.2f} {row['win_rate_pct']:>8.0f}%"
        )

    unmatched = result["unmatched_sells"]
    if unmatched:
        qty_usd = sum(u["notional_usd"] for u in unmatched)
        print()
        print(
            f"{len(unmatched)} sell(s) zonder bijbehorende buy "
            f"(~${qty_usd:.2f}): positie geopend voor het journal begint."
        )

    open_lots = result["open_lots"]
    if open_lots:
        open_usd = sum(o["notional_usd"] for o in open_lots)
        print(
            f"{len(open_lots)} lot(s) nog open op kostprijs "
            f"(~${open_usd:.2f})."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", default=str(_JOURNAL))
    parser.add_argument("--start", help="ISO-datum, inclusief")
    parser.add_argument("--end", help="ISO-datum, inclusief")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument(
        "--out-prefix",
        default="fifo_pnl",
        help="Basisnaam voor de bestanden in metrics/output/",
    )
    args = parser.parse_args()

    journal_path = Path(args.journal)
    rows = _load_jsonl(journal_path)
    if not rows:
        print(f"Geen fills gevonden in {journal_path}", file=sys.stderr)
        return 1

    rows.sort(key=lambda r: str(r.get("timestamp") or ""))
    if args.start:
        rows = [r for r in rows if str(r.get("timestamp", "")) >= args.start]
    if args.end:
        rows = [
            r for r in rows if str(r.get("timestamp", ""))[:10] <= args.end
        ]
    if args.symbols:
        wanted = set(args.symbols)
        rows = [r for r in rows if r.get("symbol") in wanted]

    journal_profit_count = sum(
        1
        for r in rows
        if str(r.get("side", "")).lower() == "sell"
        and r.get("profit_usd") is not None
    )

    result = match_fifo(rows)
    _print_report(result, journal_profit_count, len(rows))

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _OUT_DIR / f"{args.out_prefix}.json"
    csv_path = _OUT_DIR / f"{args.out_prefix}.csv"

    payload = {
        "source": str(journal_path),
        "fills": len(rows),
        "total": summarize(result["round_trips"]),
        "per_symbol": _per_symbol(result["round_trips"]),
        "round_trips": result["round_trips"],
        "unmatched_sells": result["unmatched_sells"],
        "open_lots": result["open_lots"],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp, fieldnames=_CSV_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        for trip in result["round_trips"]:
            writer.writerow({k: trip.get(k, "") for k in _CSV_FIELDS})

    print()
    print(f"  → {json_path}")
    print(f"  → {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
