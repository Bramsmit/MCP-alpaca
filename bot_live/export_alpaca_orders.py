#!/usr/bin/env python3
"""
Exporteer alle **gevulde** (FILLED) Alpaca-orders in een periode voor vergelijking
met Bitvavo.

Bron: Alpaca Trading API (niet trades.jsonl).
Zie metrics/VERGELIJK_ALPACA_BITVAVO.md.

Voorbeelden (vanaf repo-root):

  python -m bot_live.export_alpaca_orders --start 2026-03-01 --end 2026-03-31
  python -m bot_live.export_alpaca_orders --start 2026-04-01 --output-dir metrics

Vereist: ALPACA_API_KEY, ALPACA_SECRET_KEY in .env (zelfde als live_trader).
Paper vs live volgt ALPACA_PAPER_TRADE (default paper).

Let op: Alpaca filtert API-requests op submitted_at. Oude limit-orders die pas in
de gekozen periode vullen, worden meegenomen via --submit-lookback-days.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# .env vóór Alpaca-clients (zelfde patroon als bot_range_1000.live_trader)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_env_path = _REPO_ROOT / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

from alpaca.common.enums import Sort
from alpaca.trading.enums import OrderStatus, QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from bot_live.alpaca_runtime import get_trading_clients

# Alpaca max per request; we pagineren met oplopende cursor op submitted_at
_PAGE = 500


def _parse_utc_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _utc_range_inclusive(start_d: date, end_d: date) -> tuple[datetime, datetime]:
    """Kalenderdagen [start_d, end_d] in UTC: [lo, hi_exclusive)."""
    if end_d < start_d:
        raise ValueError("end vóór start")
    lo = datetime(start_d.year, start_d.month, start_d.day, tzinfo=timezone.utc)
    hi_excl = (
        datetime(end_d.year, end_d.month, end_d.day, tzinfo=timezone.utc)
        + timedelta(days=1)
    )
    return lo, hi_excl


def _order_ts(o) -> datetime | None:
    return o.filled_at or o.submitted_at


def _is_in_window(o, lo: datetime, hi_exclusive: datetime) -> bool:
    ts = _order_ts(o)
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return lo <= ts < hi_exclusive


def _norm_symbol(sym: str) -> str:
    s = sym or ""
    if "/" in s:
        return s
    if s.endswith("USD"):
        return f"{s[:-3]}/USD"
    return f"{s}/USD"


def fetch_filled_orders(
    trading_client,
    lo: datetime,
    hi_exclusive: datetime,
    symbols_filter: set[str] | None,
    submit_lookback: timedelta,
) -> list:
    """
    Haal FILLED orders waarvan filled_at (fallback submitted_at) in window valt.
    API-query gebruikt submitted_at >= lo - submit_lookback voor late limit fills.
    """
    api_after = lo - submit_lookback
    after_cursor = api_after - timedelta(seconds=1)
    collected: list = []
    seen_ids: set[str] = set()
    guard = 0

    while guard < 5000:
        guard += 1
        req = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=after_cursor,
            until=hi_exclusive,
            limit=_PAGE,
            direction=Sort.ASC,
        )
        batch = trading_client.get_orders(req) or []
        if not batch:
            break

        for o in batch:
            if o.status != OrderStatus.FILLED:
                continue
            oid = str(o.id or "")
            if not oid or oid in seen_ids:
                continue
            sym = _norm_symbol(o.symbol or "")
            if symbols_filter is not None and sym not in symbols_filter:
                continue
            if not _is_in_window(o, lo, hi_exclusive):
                continue
            seen_ids.add(oid)
            collected.append(o)

        if len(batch) < _PAGE:
            break
        last = batch[-1]
        nxt = last.submitted_at
        if nxt is None:
            break
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        else:
            nxt = nxt.astimezone(timezone.utc)
        if nxt <= after_cursor:
            break
        after_cursor = nxt

    _min = datetime.min.replace(tzinfo=timezone.utc)
    collected.sort(key=lambda x: _order_ts(x) or _min)
    return collected


def _order_to_row(o) -> dict:
    ts = _order_ts(o)
    ts_iso = ts.astimezone(timezone.utc).isoformat() if ts else ""
    side = str(o.side.value if o.side else "").lower()
    return {
        "timestamp_utc": ts_iso,
        "filled_at_utc": (
            o.filled_at.astimezone(timezone.utc).isoformat() if o.filled_at else ""
        ),
        "submitted_at_utc": (
            o.submitted_at.astimezone(timezone.utc).isoformat()
            if o.submitted_at
            else ""
        ),
        "symbol": _norm_symbol(o.symbol or ""),
        "side": side,
        "filled_qty": float(o.filled_qty or 0),
        "filled_avg_price": float(o.filled_avg_price or 0),
        "order_id": str(o.id or ""),
        "status": str(o.status.value if o.status else ""),
    }


def _write_summary_md(path: Path, meta: dict, n_buys: int, n_sells: int) -> None:
    """Korte leesbare samenvatting voor naast CSV/JSON."""
    lines = [
        "# Alpaca — export voor vergelijking",
        "",
        f"- **Bron:** trading API (`meta.source` in JSON)",
        f"- **Paper trading:** {meta.get('paper_trading')}",
        f"- **Periode (UTC):** {meta['period_utc']['start_date_inclusive']} → "
        f"{meta['period_utc']['end_date_inclusive']} (inclusief)",
        f"- **Alleen SYMBOL_POOL:** {meta.get('only_config_symbols')}",
        f"- **Submit lookback (dagen):** {meta.get('submit_lookback_days')}",
        "",
        "## Tellingen",
        "",
        f"- Gevulde orders (FILLED): **{meta.get('n_filled_orders', 0)}**",
        f"- Waarvan buy: **{n_buys}** · sell: **{n_sells}**",
        "",
        "## Per symbool",
        "",
    ]
    cbs = meta.get("count_by_symbol") or {}
    for sym in sorted(cbs.keys()):
        lines.append(f"- `{sym}`: {cbs[sym]}")
    if not cbs:
        lines.append("- *(geen)*")
    lines.extend(["", "*Zie CSV/JSON voor detailregels.*", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export Alpaca FILLED orders (API) voor vergelijking."
    )
    p.add_argument(
        "--start",
        help="Startdatum UTC (YYYY-MM-DD), inclusief. "
        "Niet combineren met --days.",
    )
    p.add_argument(
        "--end",
        help="Einddatum UTC (YYYY-MM-DD), inclusief. Default: vandaag (UTC).",
    )
    p.add_argument(
        "--days",
        type=int,
        metavar="N",
        help=(
            "Laatste N UTC-kalenderdagen inclusief einddatum "
            "(default eind: vandaag). Alternatief voor --start."
        ),
    )
    p.add_argument(
        "--output-dir",
        default="metrics",
        help="Map voor CSV/JSON (default: metrics onder repo-root).",
    )
    p.add_argument(
        "--only-config-symbols",
        action="store_true",
        help=(
            "Alleen symbolen uit bot_live.config SYMBOL_POOL (range-bot universe)."
        ),
    )
    p.add_argument(
        "--submit-lookback-days",
        type=int,
        default=120,
        metavar="N",
        help=(
            "Hoe ver terug Alpaca submitted_at zoekt (dagen vóór startdatum). "
            "Nodig voor limit orders die eerder zijn geplaatst maar in deze periode "
            "vullen. Default: 120."
        ),
    )
    args = p.parse_args()

    if args.days is not None and args.days < 1:
        p.error("--days moet minstens 1 zijn.")
    if args.days is not None and args.start is not None:
        p.error("Kies --days N of --start/--end, niet beide.")

    if args.days is not None:
        end_d = (
            _parse_utc_date(args.end)
            if args.end
            else datetime.now(timezone.utc).date()
        )
        start_d = end_d - timedelta(days=args.days - 1)
    else:
        if not args.start:
            p.error("Geef --start YYYY-MM-DD of --days N.")
        start_d = _parse_utc_date(args.start)
        end_d = (
            _parse_utc_date(args.end)
            if args.end
            else datetime.now(timezone.utc).date()
        )

    lo, hi_excl = _utc_range_inclusive(start_d, end_d)

    symbols_filter: set[str] | None = None
    if args.only_config_symbols:
        from bot_live.config import SYMBOL_POOL

        symbols_filter = {_norm_symbol(s) for s in SYMBOL_POOL}

    trading_client, _ = get_trading_clients()
    paper = os.environ.get("ALPACA_PAPER_TRADE", "True").strip().lower() not in (
        "false",
        "0",
        "no",
    )
    lookback = timedelta(days=max(1, args.submit_lookback_days))

    orders = fetch_filled_orders(
        trading_client, lo, hi_excl, symbols_filter, lookback
    )
    rows = [_order_to_row(o) for o in orders]

    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = _REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    tag = f"{start_d.isoformat()}_{end_d.isoformat()}"
    base = f"alpaca_filled_orders_{tag}"
    csv_path = out_dir / f"{base}.csv"
    json_path = out_dir / f"{base}.json"

    _write_csv(csv_path, rows)

    by_sym = Counter(r["symbol"] for r in rows)
    payload = {
        "meta": {
            "source": "alpaca_trading_api",
            "paper_trading": paper,
            "period_utc": {
                "start_date_inclusive": start_d.isoformat(),
                "end_date_inclusive": end_d.isoformat(),
            },
            "window_utc": {
                "lo_iso": lo.isoformat(),
                "hi_exclusive_iso": hi_excl.isoformat(),
            },
            "submit_lookback_days": args.submit_lookback_days,
            "n_filled_orders": len(rows),
            "count_by_symbol": dict(sorted(by_sym.items())),
            "only_config_symbols": args.only_config_symbols,
        },
        "orders": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    n_buys = sum(1 for r in rows if r.get("side") == "buy")
    n_sells = sum(1 for r in rows if r.get("side") == "sell")
    md_path = out_dir / f"{base}_summary.md"
    _write_summary_md(md_path, payload["meta"], n_buys, n_sells)

    print(f"Exported {len(rows)} filled orders")
    print(f"  CSV:  {csv_path}")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print(f"  Mode: {'paper' if paper else 'LIVE'}")


if __name__ == "__main__":
    main()
