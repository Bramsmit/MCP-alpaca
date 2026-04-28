"""Samenvattende metrics uit genormaliseerde Bitvavo journal-CSV."""

from __future__ import annotations

import csv
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    out: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(dict(row))
    return out


def summarize_label(label: str, rows: list[dict[str, str]]) -> dict[str, float | int | str]:
    n_buys = sum(1 for x in rows if x.get("side", "").lower() == "buy")
    n_sells = sum(1 for x in rows if x.get("side", "").lower() == "sell")
    profits: list[float] = []
    for x in rows:
        if x.get("side", "").lower() != "sell":
            continue
        p = x.get("profit", "").strip()
        if not p:
            continue
        try:
            profits.append(float(p))
        except ValueError:
            continue

    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p < 0)
    flat = sum(1 for p in profits if p == 0)
    total_pnl = sum(profits)
    win_rate = (wins / len(profits) * 100.0) if profits else 0.0

    return {
        "label": label,
        "rows": len(rows),
        "buys": n_buys,
        "sells": n_sells,
        "sells_with_profit_field": len(profits),
        "win_count": wins,
        "loss_count": losses,
        "flat_count": flat,
        "total_pnl_est": round(total_pnl, 4),
        "avg_pnl_est": round(total_pnl / len(profits), 6) if profits else 0.0,
        "win_rate_pct": round(win_rate, 2),
    }


def format_summary_md(tables: list[dict[str, float | int | str]]) -> str:
    lines = [
        "## Bitvavo journal — samenvatting",
        "",
        "| bron | regels | buys | sells | sells m. profit | wins | losses | sum PnL | win rate % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for t in tables:
        lines.append(
            f"| {t['label']} | {t['rows']} | {t['buys']} | {t['sells']} | "
            f"{t['sells_with_profit_field']} | {t['win_count']} | {t['loss_count']} | "
            f"{t['total_pnl_est']} | {t['win_rate_pct']} |"
        )
    lines.extend(
        [
            "",
            "*PnL op basis van journaal op sells (`bot_live`); vergelijk met Bitvavo-export "
            "voor exacte fees.*",
        ]
    )
    return "\n".join(lines)
