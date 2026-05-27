"""
Venue-neutrale range-logica: dagbars → buy/sell-levels en scores.

Numerieke constanten komen uit bot_live.config (zelfde drempels als Alpaca-runner).
"""

from __future__ import annotations

from bot_live.config import (
    BUY_ABOVE_LOW_PCT,
    LEVELS_LOOKBACK_DAYS,
    SELL_BELOW_HIGH_PCT,
)


def levels_score_from_daily_rows(
    rows: list[dict[str, float]],
    min_spread_frac: float,
) -> tuple[float, float, float] | None:
    """
    rows: chronologische OHLC (`high`, `low` verplicht), minstens LEVELS_LOOKBACK_DAYS rijen.
    Retourneert (buy_level, sell_level, score) of None bij te weinig data.
    """
    if len(rows) < LEVELS_LOOKBACK_DAYS:
        return None
    recent = rows[-LEVELS_LOOKBACK_DAYS:]
    low = sum(float(r["low"]) for r in recent) / len(recent)
    high = sum(float(r["high"]) for r in recent) / len(recent)
    buy_level = low * (1 + BUY_ABOVE_LOW_PCT)
    sell_level = high * (1 - SELL_BELOW_HIGH_PCT)
    spread_ok = sell_level >= buy_level * (1 + min_spread_frac)
    spread_pct = (sell_level - buy_level) / buy_level if spread_ok and buy_level else 0.0
    range_pct = (high - low) / low if low else 0.0
    score = spread_pct * (1 + range_pct)
    return buy_level, sell_level, score


def levels_passing_spread(
    rows: list[dict[str, float]],
    min_spread_frac: float,
) -> tuple[float, float] | None:
    """Alleen levels als minimale spread gehaald wordt (zoals get_24h_levels-filter)."""
    t = levels_score_from_daily_rows(rows, min_spread_frac)
    if t is None:
        return None
    buy_level, sell_level, _ = t
    if sell_level < buy_level * (1 + min_spread_frac):
        return None
    return buy_level, sell_level


def build_levels_scored_from_symbol_rows(
    symbol_rows: dict[str, list[dict[str, float]]],
    pool: list[str],
    min_spread_frac: float,
) -> dict[str, tuple[float, float, float]]:
    """pool-symbol → (buy, sell, score). Ontbrekende of te korte series worden overgeslagen."""
    result: dict[str, tuple[float, float, float]] = {}
    for symbol in pool:
        rows = symbol_rows.get(symbol)
        if not rows:
            continue
        t = levels_score_from_daily_rows(rows, min_spread_frac)
        if t is not None:
            result[symbol] = t
    return result


def select_top_symbols_from_scores(
    levels_scored: dict[str, tuple[float, float, float]],
    symbols_with_positions: set[str],
    n: int,
) -> tuple[list[str], dict[str, tuple[float, float]]]:
    """
    Selecteer top N op score; symbolen met open positie blijven altijd actief.
    """
    sorted_by_score = sorted(
        levels_scored.items(),
        key=lambda x: x[1][2],
        reverse=True,
    )
    selected = list(symbols_with_positions)
    for sym, (buy, sell, _) in sorted_by_score:
        if sym not in selected and len(selected) < n:
            selected.append(sym)
    levels = {
        sym: (buy, sell)
        for sym, (buy, sell, _) in sorted_by_score
        if sym in selected
    }
    return selected, levels
