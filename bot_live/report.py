#!/usr/bin/env python3
"""
Trade rapport: laad trades.jsonl en toon statistieken.

Gebruik:
    python -m bot_live.report            # console (laatste 7 dagen)
    python -m bot_live.report --days 30
    python -m bot_live.report --telegram
    python -m bot_live.report --all
"""

import sys
from datetime import datetime, timedelta, timezone

from bot_live.journal import load_trades
from bot_live.telegram import send_telegram


def _parse_args():
    days = 7
    send_tg = False
    show_all = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--telegram":
            send_tg = True
        elif args[i] == "--all":
            show_all = True
        elif args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 1
        i += 1
    return days, send_tg, show_all


def build_report(days: int = 7, show_all: bool = False) -> dict:
    trades = load_trades()

    if not trades:
        return {"empty": True, "days": days, "show_all": show_all}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if not show_all:
        trades = [
            t for t in trades
            if datetime.fromisoformat(t["timestamp"]) >= cutoff
        ]

    if not trades:
        return {"empty": True, "days": days, "show_all": show_all}

    sells = [t for t in trades if t["side"] == "sell"]
    buys = [t for t in trades if t["side"] == "buy"]

    profits = [t["profit"] for t in sells if t.get("profit") is not None]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    total_profit = sum(profits) if profits else 0.0
    avg_profit = total_profit / len(profits) if profits else 0.0
    win_rate = len(wins) / len(profits) * 100 if profits else 0.0

    profit_by_sym: dict[str, float] = {}
    for t in sells:
        if t.get("profit") is not None:
            sym = t["symbol"]
            profit_by_sym[sym] = profit_by_sym.get(sym, 0.0) + t["profit"]

    best_sym = (
        max(profit_by_sym, key=profit_by_sym.get)
        if profit_by_sym else None
    )
    worst_sym = (
        min(profit_by_sym, key=profit_by_sym.get)
        if profit_by_sym else None
    )

    return {
        "empty": False,
        "days": days,
        "show_all": show_all,
        "n_total": len(trades),
        "n_buys": len(buys),
        "n_sells": len(sells),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": win_rate,
        "total_profit": total_profit,
        "avg_profit": avg_profit,
        "best_sym": best_sym,
        "best_profit": profit_by_sym.get(best_sym) if best_sym else None,
        "worst_sym": worst_sym,
        "worst_profit": (
            profit_by_sym.get(worst_sym) if worst_sym else None
        ),
        "profit_by_sym": profit_by_sym,
        "latest_portfolio": trades[-1].get("portfolio_value"),
    }


def format_report(r: dict) -> str:
    period = "alle tijd" if r.get("show_all") else f"laatste {r['days']} dagen"

    if r.get("empty"):
        return (
            f"=== Trade Rapport ({period}) ===\n"
            "Geen trades gevonden."
        )

    lines = [
        f"=== Trade Rapport ({period}) ===",
        f"Trades:       {r['n_total']} ({r['n_buys']} buys, {r['n_sells']} sells)",
    ]

    if r["n_sells"] > 0:
        lines.append(
            f"Win rate:     {r['win_rate']:.0f}%"
            f" ({r['n_wins']} wins, {r['n_losses']} losses)"
        )
        lines.append(f"Totale P&L:   {r['total_profit']:+.2f} USD")
        lines.append(
            f"Gem. profit:  {r['avg_profit']:+.2f} USD per sell"
        )

    if r.get("profit_by_sym"):
        lines.append("")
        lines.append("Per symbol:")
        for sym, pnl in sorted(
            r["profit_by_sym"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"  {sym:12} {pnl:+.2f} USD")

    if r.get("best_sym"):
        lines.append(
            f"Best:         {r['best_sym']} ({r['best_profit']:+.2f} USD)"
        )
    if r.get("worst_sym") and r["worst_sym"] != r.get("best_sym"):
        lines.append(
            f"Worst:        {r['worst_sym']} ({r['worst_profit']:+.2f} USD)"
        )
    if r.get("latest_portfolio"):
        lines.append(f"Portfolio:    ${r['latest_portfolio']:.2f}")

    return "\n".join(lines)


def main():
    days, send_tg, show_all = _parse_args()
    r = build_report(days=days, show_all=show_all)
    text = format_report(r)
    print(text)
    if send_tg:
        send_telegram(text)


if __name__ == "__main__":
    main()
