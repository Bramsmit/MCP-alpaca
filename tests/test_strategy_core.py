"""Regressietests voor venue-neutrale range-logica (Alpaca + Kraken delen deze module)."""

from __future__ import annotations

import pytest

from bot_live.config import (
    BUY_ABOVE_LOW_PCT,
    LEVELS_LOOKBACK_DAYS,
    SELL_BELOW_HIGH_PCT,
)
from alpaca_bot.strategy_core import (
    build_levels_scored_from_symbol_rows,
    buy_level_distance_frac,
    is_buy_level_reachable,
    levels_passing_spread,
    levels_score_from_daily_rows,
    select_top_symbols_from_scores,
)


def _flat_daily(low: float, high: float, n: int) -> list[dict[str, float]]:
    return [{"open": low, "high": high, "low": low, "close": (low + high) / 2} for _ in range(n)]


def test_levels_score_returns_none_when_insufficient_rows():
    rows = _flat_daily(100.0, 110.0, LEVELS_LOOKBACK_DAYS - 1)
    assert levels_score_from_daily_rows(rows, min_spread_frac=0.0) is None


def test_levels_score_flat_band():
    """Constant low/high → bekende buy/sell uit BUY_ABOVE_LOW_PCT / SELL_BELOW_HIGH_PCT."""
    rows = _flat_daily(100.0, 110.0, LEVELS_LOOKBACK_DAYS)
    out = levels_score_from_daily_rows(rows, min_spread_frac=0.0)
    assert out is not None
    buy_level, sell_level, score = out
    assert buy_level == pytest.approx(100.0 * (1 + BUY_ABOVE_LOW_PCT))
    assert sell_level == pytest.approx(110.0 * (1 - SELL_BELOW_HIGH_PCT))
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


def test_buy_level_distance_positief_boven_level():
    """DOT 8 sep: markt $1,2342 tegen buy-level $0,9770 = ruim 26% erboven."""
    d = buy_level_distance_frac(1.23417, 0.9770124249999999)
    assert d == pytest.approx(0.2632, abs=1e-4)


def test_buy_level_distance_none_zonder_prijs():
    assert buy_level_distance_frac(None, 10.0) is None
    assert buy_level_distance_frac(10.0, None) is None
    assert buy_level_distance_frac(0.0, 10.0) is None
    assert buy_level_distance_frac(10.0, 0.0) is None


def test_onbekende_prijs_filtert_niet():
    """Een ontbrekende quote mag geen symbool uit de selectie duwen."""
    assert is_buy_level_reachable(None, 10.0, 0.10)


def test_bereikbaarheid_op_de_grens():
    assert is_buy_level_reachable(11.0, 10.0, 0.10)
    assert not is_buy_level_reachable(11.01, 10.0, 0.10)


def test_dode_buy_kandidaat_krijgt_geen_slot():
    """
    De DOT-situatie: hoogste score, maar de koers staat 26% boven het
    buy-level. Dat slot hoort naar AVAX te gaan, dat 5,9% eronder zit.
    """
    levels_scored = {
        "DOT/USD": (0.9770, 1.0913, 0.90),
        "AVAX/USD": (7.5910, 7.9363, 0.20),
    }
    prices = {"DOT/USD": 1.23417, "AVAX/USD": 8.039875}

    selected, levels = select_top_symbols_from_scores(
        levels_scored,
        symbols_with_positions=set(),
        n=1,
        current_prices=prices,
        max_buy_distance_frac=0.10,
    )

    assert selected == ["AVAX/USD"]
    assert "DOT/USD" not in levels


def test_positie_blijft_actief_ook_buiten_bereik():
    """Anders verliest een open positie haar exit-order."""
    levels_scored = {"DOT/USD": (0.9770, 1.0913, 0.90)}
    prices = {"DOT/USD": 1.23417}

    selected, _ = select_top_symbols_from_scores(
        levels_scored,
        symbols_with_positions={"DOT/USD"},
        n=1,
        current_prices=prices,
        max_buy_distance_frac=0.10,
    )

    assert selected == ["DOT/USD"]


def test_selectie_zonder_afstandsfilter_blijft_ongewijzigd():
    """Kraken roept deze functie met drie argumenten; gedrag mag niet wijzigen."""
    levels_scored = {
        "DOT/USD": (0.9770, 1.0913, 0.90),
        "AVAX/USD": (7.5910, 7.9363, 0.20),
    }
    selected, _ = select_top_symbols_from_scores(levels_scored, set(), 1)
    assert selected == ["DOT/USD"]
