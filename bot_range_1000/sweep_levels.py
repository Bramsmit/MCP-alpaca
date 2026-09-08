#!/usr/bin/env python3
"""
Parametersweep voor de range-levels: lookback-dagen x sell-marge.

De live bot stond 17 dagen zonder fills terwijl maar ~31% van het kapitaal in
de markt zat. Deze sweep meet per combinatie niet alleen het rendement maar
ook het aantal fills: een instelling die niets verdient omdat ze nooit vult is
een ander probleem dan een instelling die verliest.

MIN_SPREAD_PCT blijft vast: dat is de fee-bodem, geen vrije parameter. Bij een
smalle sell-marge kan de spread-gate dus trades blokkeren — dat is precies het
gedrag dat de live bot ook heeft.

Gebruik:
    python -m bot_range_1000.sweep_levels
    python -m bot_range_1000.sweep_levels --months 6 --top 10
    python -m bot_range_1000.sweep_levels --lookbacks 3 5 --sell-margins 0.02
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_env_path = _REPO_ROOT / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

from bot_live.config import (  # noqa: E402
    BUY_ABOVE_LOW_PCT,
    CAPITAL_PER_ASSET,
    LEVELS_LOOKBACK_DAYS,
    MIN_SPREAD_PCT,
    SELL_BELOW_HIGH_PCT,
    STOP_LOSS_PER_UNIT,
    SYMBOL_POOL,
)
from bot_range_1000.backtest import fetch_data, run_backtest  # noqa: E402

DEFAULT_LOOKBACKS = [2, 3, 5, 7]
DEFAULT_SELL_MARGINS = [0.01, 0.02, 0.03]
_OUTPUT_DIR = _REPO_ROOT / "metrics" / "output"


def run_grid(
    data: dict,
    symbols: list[str],
    lookbacks: list[int],
    sell_margins: list[float],
    *,
    buy_above_low_pct: float = BUY_ABOVE_LOW_PCT,
    stop_loss_per_unit: float = STOP_LOSS_PER_UNIT,
    capital_per_asset: float = CAPITAL_PER_ASSET,
) -> list[dict]:
    """
    Draai elke (lookback, sell-marge)-combinatie over alle symbolen.

    Elk symbool krijgt hetzelfde startkapitaal en wordt los doorgerekend; de
    live slot-competitie tussen symbolen zit hier niet in. Deze sweep
    vergelijkt dus parameters onderling, hij voorspelt geen live equity.
    """
    results = []

    for lookback in lookbacks:
        for sell_margin in sell_margins:
            per_symbol = []
            for symbol in symbols:
                df = data.get(symbol)
                if df is None or df.empty or len(df) < lookback + 2:
                    continue
                res = run_backtest(
                    df,
                    symbol,
                    capital_per_asset,
                    stop_loss_per_unit,
                    lookback_days=lookback,
                    buy_above_low_pct=buy_above_low_pct,
                    sell_below_high_pct=sell_margin,
                )
                per_symbol.append(res)

            if not per_symbol:
                continue

            n_symbols = len(per_symbol)
            total_start = capital_per_asset * n_symbols
            total_end = sum(r["final_value"] for r in per_symbol)
            n_trades = sum(r["n_trades"] for r in per_symbol)
            traded = sum(1 for r in per_symbol if r["n_trades"] > 0)
            returns = sorted(r["return_pct"] for r in per_symbol)
            mid = n_symbols // 2
            median = (
                returns[mid]
                if n_symbols % 2
                else (returns[mid - 1] + returns[mid]) / 2
            )

            results.append(
                {
                    "lookback_days": lookback,
                    "sell_below_high_pct": sell_margin,
                    "total_return_pct": (total_end - total_start)
                    / total_start
                    * 100,
                    "median_symbol_return_pct": median,
                    "n_trades": n_trades,
                    "symbols_with_trades": traded,
                    "symbols_tested": n_symbols,
                    "is_live_config": (
                        lookback == LEVELS_LOOKBACK_DAYS
                        and abs(sell_margin - SELL_BELOW_HIGH_PCT) < 1e-9
                    ),
                    "per_symbol": [
                        {
                            "symbol": r["symbol"],
                            "return_pct": round(r["return_pct"], 2),
                            "n_trades": r["n_trades"],
                        }
                        for r in per_symbol
                    ],
                }
            )

    results.sort(key=lambda r: r["total_return_pct"], reverse=True)
    return results


def _print_table(results: list[dict], top: int, days: int) -> None:
    print()
    print(f"{'lookback':>9} {'sell-marge':>11} {'return':>9} "
          f"{'mediaan':>9} {'trades':>7} {'symb.':>6}")
    print("-" * 56)
    for r in results[:top]:
        marker = "  <- live" if r["is_live_config"] else ""
        print(
            f"{r['lookback_days']:>9} "
            f"{r['sell_below_high_pct'] * 100:>10.1f}% "
            f"{r['total_return_pct']:>+8.2f}% "
            f"{r['median_symbol_return_pct']:>+8.2f}% "
            f"{r['n_trades']:>7} "
            f"{r['symbols_with_trades']:>2}/{r['symbols_tested']:<3}"
            f"{marker}"
        )

    live = next((r for r in results if r["is_live_config"]), None)
    best = results[0] if results else None
    if live and best:
        rank = results.index(live) + 1
        print()
        print(
            f"Live config (lookback {live['lookback_days']}, "
            f"sell {live['sell_below_high_pct'] * 100:.0f}%) staat "
            f"{rank} van {len(results)}: {live['total_return_pct']:+.2f}% "
            f"met {live['n_trades']} trades over {days} dagen data."
        )
        if best is not live:
            print(
                f"Beste: lookback {best['lookback_days']}, "
                f"sell {best['sell_below_high_pct'] * 100:.0f}% → "
                f"{best['total_return_pct']:+.2f}% met "
                f"{best['n_trades']} trades."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument(
        "--lookbacks", type=int, nargs="+", default=DEFAULT_LOOKBACKS
    )
    parser.add_argument(
        "--sell-margins", type=float, nargs="+", default=DEFAULT_SELL_MARGINS
    )
    parser.add_argument("--symbols", nargs="+", default=SYMBOL_POOL)
    parser.add_argument(
        "--json-out",
        default=str(_OUTPUT_DIR / "sweep_levels.json"),
        help="Schrijf volledige uitkomst hierheen (leeg = niet schrijven)",
    )
    args = parser.parse_args()

    print("Range-level sweep")
    print(
        f"Vast: buy {BUY_ABOVE_LOW_PCT * 100:.1f}% boven low, "
        f"min spread {MIN_SPREAD_PCT * 100:.0f}%, "
        f"stop ${STOP_LOSS_PER_UNIT:.2f}/eenheid, "
        f"${CAPITAL_PER_ASSET:.0f} per symbool"
    )
    print(
        f"Data ophalen: {len(args.symbols)} symbolen, "
        f"{args.months} maanden..."
    )

    try:
        data = fetch_data(args.symbols, months=args.months)
    except Exception as e:
        print(f"Fout bij ophalen data: {e}")
        return

    usable = {
        s: df for s, df in data.items() if df is not None and not df.empty
    }
    if not usable:
        print("Geen bruikbare data ontvangen.")
        return
    days = max(len(df) for df in usable.values())
    print(f"  {len(usable)} symbolen met data, max {days} dagbars")

    results = run_grid(usable, list(usable), args.lookbacks, args.sell_margins)
    if not results:
        print("Geen combinaties doorgerekend (te weinig bars?).")
        return

    _print_table(results, args.top, days)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "months": args.months,
            "days_of_bars": days,
            "fixed": {
                "buy_above_low_pct": BUY_ABOVE_LOW_PCT,
                "min_spread_pct": MIN_SPREAD_PCT,
                "stop_loss_per_unit": STOP_LOSS_PER_UNIT,
                "capital_per_asset": CAPITAL_PER_ASSET,
            },
            "results": results,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nVolledige uitkomst → {out_path}")


if __name__ == "__main__":
    main()
