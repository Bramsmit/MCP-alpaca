#!/usr/bin/env python3
"""
Genereer een handoff-pakket (JSON + Markdown) voor v2 / Cursor-context.

Leest uit projectroot (indien aanwezig):
  - trades.jsonl  - .alpaca_trade_state.json

Bevat GEEN API keys. Draai vanaf repo-root:

  python -m bot_range_1000.export_handoff
  python -m bot_range_1000.export_handoff --output-dir exports --max-trades-md 100
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S") + "Z"


def _load_state_summary(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"error": "could_not_parse", "path": str(path)}

    entries = data.get("entries") or {}
    notified = data.get("notified_order_ids") or []
    if not isinstance(entries, dict):
        entries = {}
    if not isinstance(notified, list):
        notified = []

    symbols = list(entries.keys())
    return {
        "path": str(path),
        "n_entry_symbols": len(symbols),
        "symbols_with_entry": symbols,
        "n_notified_order_ids": len(notified),
    }


def _config_snapshot() -> dict:
    import bot_live.config as c

    keys = [
        "SYMBOL_POOL",
        "SYMBOLS_ACTIVE",
        "SYMBOLS",
        "START_CAPITAL",
        "CAPITAL_PER_ASSET",
        "LEVELS_LOOKBACK_DAYS",
        "BUY_ABOVE_LOW_PCT",
        "SELL_BELOW_HIGH_PCT",
        "MIN_SPREAD_PCT",
        "STOP_LOSS_PER_UNIT",
        "ALPACA_CRYPTO_SINGLE_EXIT_ORDER",
        "ORDER_REPLACE_DELAY_SEC",
        "ORDER_UPDATE_THRESHOLD",
        "ORDER_MAX_AGE_HOURS",
        "ORDER_STALE_PRICE_THRESHOLD",
        "BACKTEST_MONTHS",
        "TIMEFRAME",
    ]
    out: dict = {}
    for k in keys:
        if hasattr(c, k):
            out[k] = getattr(c, k)
    return out


def _trade_summary(trades: list[dict]) -> dict:
    if not trades:
        return {"n_trades": 0}

    sells = [t for t in trades if t.get("side") == "sell"]
    buys = [t for t in trades if t.get("side") == "buy"]
    profits = [t["profit"] for t in sells if t.get("profit") is not None]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    profit_by_sym: dict[str, float] = {}
    for t in sells:
        if t.get("profit") is not None:
            sym = t.get("symbol", "")
            prev = profit_by_sym.get(sym, 0.0)
            profit_by_sym[sym] = prev + float(t["profit"])

    first_ts = trades[0].get("timestamp")
    last_ts = trades[-1].get("timestamp")

    return {
        "n_trades": len(trades),
        "n_buys": len(buys),
        "n_sells": len(sells),
        "n_sells_with_profit_field": len(profits),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate_pct": (
            round(len(wins) / len(profits) * 100, 2) if profits else None
        ),
        "total_profit": round(sum(profits), 4) if profits else None,
        "profit_by_symbol": {
            k: round(v, 4) for k, v in sorted(profit_by_sym.items())
        },
        "first_trade_utc": first_ts,
        "last_trade_utc": last_ts,
        "latest_portfolio_value": trades[-1].get("portfolio_value"),
    }


def _write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def _write_md(path: Path, payload: dict, max_trades_md: int) -> None:
    meta = payload["meta"]
    cfg = payload["config_snapshot"]
    ts = payload["trade_summary"]
    trades = payload.get("trades") or []

    lines = [
        f"# Alpaca range bot — handoff ({meta['generated_at_utc']})",
        "",
        "Automatisch gegenereerd; bevat geen API secrets.",
        "",
        "## Meta",
        "",
        f"- **Repo root:** `{meta.get('repo_root', '')}`",
        f"- **Generator:** `{meta.get('generator', '')}`",
        "",
        "## Config snapshot",
        "",
        "```json",
        json.dumps(cfg, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Trade summary",
        "",
        "```json",
        json.dumps(ts, indent=2, ensure_ascii=False),
        "```",
        "",
    ]

    st = payload.get("state_summary")
    if st:
        lines += [
            "## State file summary",
            "",
            "```json",
            json.dumps(st, indent=2, ensure_ascii=False),
            "```",
            "",
        ]

    if trades:
        tail = trades[-max_trades_md:] if max_trades_md > 0 else trades
        lines += [
            f"## Laatste trades (max {max_trades_md}, totaal {len(trades)})",
            "",
            "| UTC | Side | Symbol | Qty | Price | Profit | P&L % |",
            "|-----|------|--------|-----|-------|--------|-------|",
        ]
        row = "| {ts} | {side} | {sym} | {qty} | {price} | {profit} | {ppct} |"
        for t in tail:
            lines.append(
                row.format(
                    ts=t.get("timestamp", ""),
                    side=t.get("side", ""),
                    sym=t.get("symbol", ""),
                    qty=t.get("qty", ""),
                    price=t.get("price", ""),
                    profit=t.get("profit", ""),
                    ppct=t.get("profit_pct", ""),
                )
            )
        lines.append("")
    else:
        lines += [
            "## Trades",
            "",
            "_Geen `trades.jsonl` geladen (bestand ontbreekt of is leeg)._",
            "",
        ]

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    desc = "Export bot handoff JSON + MD"
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "exports",
        help="Directory voor uitvoer (default: ./exports)",
    )
    parser.add_argument(
        "--max-trades-md",
        type=int,
        default=80,
        help="Max rijen in MD-tabel (default: 80)",
    )
    args = parser.parse_args()

    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = _utc_stamp()
    base = f"alpaca_range_bot_v1_handoff_{stamp}"

    from bot_live.journal import load_trades

    trades_path = ROOT / "trades.jsonl"
    state_path = ROOT / ".alpaca_trade_state.json"

    trades = load_trades()
    payload = {
        "meta": {
            "generator": "bot_range_1000.export_handoff",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "repo_root": str(ROOT),
            "source_files": {
                "trades_jsonl": str(trades_path),
                "trade_state": str(state_path),
                "trades_jsonl_exists": trades_path.exists(),
                "trade_state_exists": state_path.exists(),
            },
        },
        "config_snapshot": _config_snapshot(),
        "trades": trades,
        "trade_summary": _trade_summary(trades),
        "state_summary": _load_state_summary(state_path),
    }

    json_path = out_dir / f"{base}.json"
    md_path = out_dir / f"{base}.md"
    _write_json(json_path, payload)
    _write_md(md_path, payload, max_trades_md=args.max_trades_md)

    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")


if __name__ == "__main__":
    main()
