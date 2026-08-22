"""FIFO metrics and venue comparison summaries."""

from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import Fill


def fifo_realized(
    fills: list[Fill],
    *,
    fallback_fee_rate: float = 0.0,
) -> dict[str, Any]:
    """Match buys→sells FIFO; fees from fill.fee_usd or fallback_fee_rate * notional."""
    # Each lot: [remaining_qty, price, remaining_buy_fee]
    books: dict[str, deque[list[float]]] = defaultdict(deque)
    roundtrips: list[dict[str, Any]] = []
    fees_total = 0.0

    for f in fills:
        sym = f["symbol"]
        qty = float(f["qty"])
        px = float(f["price"])
        fee = f.get("fee_usd")
        if fee is None:
            fee = qty * px * fallback_fee_rate
        else:
            fee = float(fee)
        fees_total += fee
        side = f["side"]
        ts = f.get("timestamp")

        if side == "buy":
            books[sym].append([qty, px, fee])
        else:
            rem = qty
            while rem > 1e-12 and books[sym]:
                lq, lp, lfee = books[sym][0]
                take = min(rem, lq)
                frac = take / lq if lq > 0 else 1.0
                buy_fee_part = lfee * frac
                sell_fee_part = fee * (take / qty) if qty > 0 else 0.0
                gross = take * (px - lp)
                net = gross - buy_fee_part - sell_fee_part
                roundtrips.append(
                    {
                        "symbol": sym,
                        "exit_ts": ts,
                        "month": (ts or "")[:7],
                        "qty": take,
                        "entry": lp,
                        "exit": px,
                        "gross": gross,
                        "fees": buy_fee_part + sell_fee_part,
                        "net": net,
                    }
                )
                lq -= take
                rem -= take
                if lq <= 1e-12:
                    books[sym].popleft()
                else:
                    books[sym][0][0] = lq
                    books[sym][0][2] = lfee * (1 - frac)

    wins = sum(1 for t in roundtrips if t["net"] > 0)
    losses = sum(1 for t in roundtrips if t["net"] <= 0)
    by_month: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"n": 0, "gross": 0.0, "fees": 0.0, "net": 0.0, "wins": 0}
    )
    by_symbol: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"n": 0, "gross": 0.0, "fees": 0.0, "net": 0.0, "wins": 0}
    )
    for t in roundtrips:
        m = by_month[t["month"] or "unknown"]
        m["n"] = int(m["n"]) + 1
        m["gross"] = float(m["gross"]) + t["gross"]
        m["fees"] = float(m["fees"]) + t["fees"]
        m["net"] = float(m["net"]) + t["net"]
        if t["net"] > 0:
            m["wins"] = int(m["wins"]) + 1
        s = by_symbol[t["symbol"]]
        s["n"] = int(s["n"]) + 1
        s["gross"] = float(s["gross"]) + t["gross"]
        s["fees"] = float(s["fees"]) + t["fees"]
        s["net"] = float(s["net"]) + t["net"]
        if t["net"] > 0:
            s["wins"] = int(s["wins"]) + 1

    open_notional = sum(q * p for lots in books.values() for q, p, _ in lots)
    return {
        "fills": len(fills),
        "buys": sum(1 for f in fills if f["side"] == "buy"),
        "sells": sum(1 for f in fills if f["side"] == "sell"),
        "roundtrips": len(roundtrips),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(100.0 * wins / len(roundtrips), 1) if roundtrips else 0.0,
        "gross": round(sum(t["gross"] for t in roundtrips), 2),
        "fees": round(fees_total, 2),
        "net": round(sum(t["net"] for t in roundtrips), 2),
        "open_notional": round(open_notional, 2),
        "by_month": {k: dict(v) for k, v in sorted(by_month.items())},
        "by_symbol": {
            k: dict(v)
            for k, v in sorted(by_symbol.items(), key=lambda kv: -float(kv[1]["net"]))
        },
        "first_ts": fills[0]["timestamp"] if fills else None,
        "last_ts": fills[-1]["timestamp"] if fills else None,
        "volume": round(sum(float(f["notional_usd"]) for f in fills), 2),
    }


def compare_venues(
    alpaca: dict[str, Any],
    kraken: dict[str, Any],
    *,
    alpaca_start_capital: float = 1000.0,
    kraken_start_capital: float = 500.0,
    alpaca_equity_now: float | None = None,
    kraken_equity_now: float | None = None,
) -> str:
    lines = [
        "# Alpaca paper vs Kraken live — vergelijking",
        "",
        f"_Gegenereerd: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC_",
        "",
        "## Overzicht",
        "",
        "| Metric | Alpaca paper | Kraken live |",
        "|---|---:|---:|",
        f"| Fills | {alpaca['fills']} | {kraken['fills']} |",
        f"| Buys / sells | {alpaca['buys']} / {alpaca['sells']} | {kraken['buys']} / {kraken['sells']} |",
        f"| FIFO roundtrips | {alpaca['roundtrips']} | {kraken['roundtrips']} |",
        f"| Win-rate (net) | {alpaca['win_rate_pct']}% | {kraken['win_rate_pct']}% |",
        f"| Volume (notional) | ${alpaca['volume']:,.0f} | ${kraken['volume']:,.0f} |",
        f"| Gross PnL | ${alpaca['gross']:,.2f} | ${kraken['gross']:,.2f} |",
        f"| Fees | ${alpaca['fees']:,.2f} (paper=0) | ${kraken['fees']:,.2f} |",
        f"| Net PnL (FIFO) | ${alpaca['net']:,.2f} | ${kraken['net']:,.2f} |",
        f"| Open notional | ${alpaca['open_notional']:,.2f} | ${kraken['open_notional']:,.2f} |",
        f"| Eerste fill | {alpaca['first_ts']} | {kraken['first_ts']} |",
        f"| Laatste fill | {alpaca['last_ts']} | {kraken['last_ts']} |",
        "",
    ]

    if alpaca_equity_now is not None or kraken_equity_now is not None:
        a_txt = "—"
        k_txt = "—"
        if alpaca_equity_now is not None and alpaca_start_capital > 0:
            ar = (alpaca_equity_now / alpaca_start_capital - 1) * 100
            a_txt = (
                f"${alpaca_start_capital:,.0f}→${alpaca_equity_now:,.2f} "
                f"({ar:+.1f}%)"
            )
        if kraken_equity_now is not None and kraken_start_capital > 0:
            kr = (kraken_equity_now / kraken_start_capital - 1) * 100
            k_txt = (
                f"${kraken_start_capital:,.0f}→${kraken_equity_now:,.2f} "
                f"({kr:+.1f}%)"
            )
        lines.append(f"| Start → equity nu | {a_txt} | {k_txt} |")

    lines.extend(["", "## Per maand (FIFO net)", ""])
    months = sorted(
        set(alpaca["by_month"]) | set(kraken["by_month"])
    )
    lines.append("| Maand | Alpaca net | Kraken net | Alpaca # | Kraken # |")
    lines.append("|---|---:|---:|---:|---:|")
    for m in months:
        a = alpaca["by_month"].get(m, {})
        k = kraken["by_month"].get(m, {})
        lines.append(
            f"| {m} | ${float(a.get('net', 0)):.2f} | ${float(k.get('net', 0)):.2f} | "
            f"{int(a.get('n', 0))} | {int(k.get('n', 0))} |"
        )

    lines.extend(["", "## Diagnose-hints", ""])
    fill_ratio = (
        kraken["fills"] / alpaca["fills"] if alpaca["fills"] else 0.0
    )
    lines.append(
        f"- Fill-activiteit Kraken/Alpaca in venster: **{fill_ratio:.0%}** "
        f"({kraken['fills']} vs {alpaca['fills']} fills)."
    )
    if kraken["fees"] > 0 and kraken["gross"] != 0:
        lines.append(
            f"- Kraken fees als % van bruto: "
            f"**{100 * kraken['fees'] / abs(kraken['gross']):.0f}%** "
            f"(${kraken['fees']:.2f} fees op ${kraken['gross']:.2f} gross)."
        )
    if alpaca["fills"] > kraken["fills"] * 3:
        lines.append(
            "- Groot activiteitsverschil: paper vult sneller/vaker dan live "
            "(partial fills, post-only, of bot idle/dry-run perioden)."
        )
    lines.append(
        "- Vergelijk altijd **% return op startkapitaal**, niet alleen absolute dollars "
        f"(Alpaca ~${alpaca_start_capital:.0f} vs Kraken ~${kraken_start_capital:.0f})."
    )
    lines.append("")
    return "\n".join(lines)


def write_normalized_csv(path: Path, fills: list[Fill]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "venue",
        "timestamp",
        "symbol",
        "side",
        "qty",
        "price",
        "fee_usd",
        "portfolio_usd",
        "trade_id",
        "notional_usd",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in fills:
            w.writerow(row)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
