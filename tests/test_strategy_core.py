"""Regressietests voor venue-neutrale range-logica (Alpaca + Kraken delen deze module)."""

from __future__ import annotations

import pytest

from bot_live.config import LEVELS_LOOKBACK_DAYS
from alpaca_bot.strategy_core import (
    build_levels_scored_from_symbol_rows,
    levels_passing_spread,
    levels_score_from_daily_rows,
    select_top_symbols_from_scores,
)


def _flat_daily(low: float, high: float, n: int) -> list[dict[str, float]]:
    return [{"open": low, "high": high, "low": low, "close": (low + high) / 2} for _ in range(n)]


def test_levels_score_returns_none_when_insufficient_rows():
    rows = _flat_daily(100.0, 110.0, LEVELS_LOOKBACK_DAYS - 1)
    assert levels_score_from_daily_rows(rows, min_spread_frac=0.0) is None


def test_levels_score_flat_three_day_band():
    """Constant low/high → bekende buy/sell uit BUY_ABOVE_LOW_PCT / SELL_BELOW_HIGH_PCT."""
    rows = _flat_daily(100.0, 110.0, LEVELS_LOOKBACK_DAYS)
    out = levels_score_from_daily_rows(rows, min_spread_frac=0.0)
    assert out is not None
    buy_level, sell_level, score = out
    assert buy_level == pytest.approx(100.0 * 1.005)
    assert sell_level == pytest.approx(110.0 * (1 - 0.02))
    assert score >= 0.0


def test_levels_passing_spread_none_when_min_spread_too_large():
    rows = _flat_daily(100.0, 110.0, LEVELS_LOOKBACK_DAYS)
    assert levels_passing_spread(rows, min_spread_frac=0.50) is None


def test_levels_passing_spread_returns_tuple_when_spread_ok():
    rows = _flat_daily(100.0, 120.0, LEVELS_LOOKBACK_DAYS)
    out = levels_passing_spread(rows, min_spread_frac=0.02)
    assert out is not None
    buy, sell = out
    assert sell >= buy * 1.02


def test_build_levels_scored_skips_missing_and_short_series():
    pool = ["AA", "BB"]
    symbol_rows = {
        "AA": _flat_daily(50.0, 55.0, LEVELS_LOOKBACK_DAYS),
        "BB": _flat_daily(1.0, 1.01, LEVELS_LOOKBACK_DAYS - 1),
    }
    scored = build_levels_scored_from_symbol_rows(symbol_rows, pool, min_spread_frac=0.0)
    assert "AA" in scored
    assert "BB" not in scored


def test_select_top_symbols_keeps_positions_and_respects_cap_n():
    levels_scored = {
        "ETH/USD": (100.0, 115.0, 0.50),
        "BTC/USD": (100.0, 105.0, 0.10),
        "SOL/USD": (100.0, 112.0, 0.40),
    }
    positions = {"BTC/USD"}
    selected, levels = select_top_symbols_from_scores(levels_scored, positions, n=2)

    assert selected[0] == "BTC/USD"
    assert len(selected) == 2
    assert set(levels.keys()) == set(selected)
