"""Regressietests voor kapitaalslots van de Alpaca range-bot.

Restposities van een paar dollar telden mee als volwaardige positie. Daardoor
groeide de selectie tot ver boven SYMBOLS_ACTIVE, werd `buying_power` door dat
aantal gedeeld en kromp elke order mee.
"""

from __future__ import annotations

from bot_live.config import (
    ALPACA_MIN_POSITION_NOTIONAL_USD,
    ALPACA_CRYPTO_ROUND_TRIP_FIXED_USD,
    ALPACA_RANGE_MAX_DEPLOYED_PCT,
    ALPACA_RANGE_SYMBOLS_ACTIVE,
    MIN_SPREAD_PCT,
    SAFETY_MAX_ALLOC_PCT,
)
from alpaca_bot.live_trader import compute_capital_per_usd, is_tradable_position
from alpaca_bot.strategy_core import select_top_symbols_from_scores


def test_drempel_ligt_waar_vaste_fee_de_spread_opeet():
    assert ALPACA_MIN_POSITION_NOTIONAL_USD == (
        ALPACA_CRYPTO_ROUND_TRIP_FIXED_USD / MIN_SPREAD_PCT
    )


def test_volwaardige_positie_telt_mee():
    assert is_tradable_position(qty=10.0, ref_price=15.0)


def test_restpositie_onder_drempel_telt_niet_mee():
    """$0,16 aan XRP haalt de qty-drempel wel, maar is economisch niets."""
    assert not is_tradable_position(qty=0.106421, ref_price=1.50)


def test_positie_onder_qty_drempel_telt_niet_mee():
    assert not is_tradable_position(qty=0.00001, ref_price=2200.0)


def test_lege_positie_telt_niet_mee():
    assert not is_tradable_position(qty=0.0, ref_price=100.0)
    assert not is_tradable_position(qty=-1.0, ref_price=100.0)


def test_restposities_bezetten_geen_slot():
    """Met alleen restjes open moet de bot alsnog n verse symbolen kunnen kiezen."""
    scored = {
        f"S{i}/USD": (10.0, 10.5, 1.0 - i / 100) for i in range(8)
    }
    posities = {
        "S6/USD": (0.106421, 1.50),  # $0,16
        "S7/USD": (0.000219, 2237.0),  # $0,49
    }
    met_positie = {
        sym for sym, (qty, entry) in posities.items() if is_tradable_position(qty, entry)
    }
    assert met_positie == set()

    selected, _ = select_top_symbols_from_scores(scored, met_positie, n=5)
    assert len(selected) == 5


def _capital_per(
    equity: float,
    cash: float,
    buy_slots: int,
    *,
    position_market: float = 0.0,
) -> float:
    per, _, _ = compute_capital_per_usd(
        portfolio_equity=equity,
        buying_power=cash,
        position_market_value=position_market,
        buy_slots=buy_slots,
        max_deployed_pct=ALPACA_RANGE_MAX_DEPLOYED_PCT,
    )
    return per


def test_open_buy_orders_tellen_niet_als_deployed():
    """Deadlock aug 2026: equity−cash leek 79% ingezet, maar dat waren open buys."""
    equity, cash = 1494.69, 308.80
    per = _capital_per(equity, cash, buy_slots=5, position_market=0.0)
    assert per > 10.0
    assert per == min(cash, equity * ALPACA_RANGE_MAX_DEPLOYED_PCT) / 5


def test_totale_inzet_blijft_onder_plafond():
    """Per-symbool-cap alleen is niet genoeg: n symbolen x 20% kan 100% worden."""
    assert ALPACA_RANGE_SYMBOLS_ACTIVE * SAFETY_MAX_ALLOC_PCT >= 1.0

    equity, cash = 1495.0, 1428.0
    per = _capital_per(equity, cash, buy_slots=ALPACA_RANGE_SYMBOLS_ACTIVE)
    totaal = per * ALPACA_RANGE_SYMBOLS_ACTIVE
    assert totaal <= equity * ALPACA_RANGE_MAX_DEPLOYED_PCT + 1e-9


def test_geen_kapitaal_meer_boven_plafond():
    equity = 1000.0
    position_mv = equity * ALPACA_RANGE_MAX_DEPLOYED_PCT
    cash = equity - position_mv
    assert _capital_per(equity, cash, buy_slots=3, position_market=position_mv) == 0.0


def test_restjes_verschralen_de_ordergrootte_niet():
    """De bug: delen door alle geselecteerde symbolen i.p.v. de koopbare."""
    equity, cash = 1495.0, 1428.0
    oud = _capital_per(equity, cash, buy_slots=10)
    nieuw = _capital_per(equity, cash, buy_slots=5)
    assert nieuw == oud * 2


def test_inzet_groeit_naar_het_plafond():
    """Simuleer fills: position_market groeit tot deploy-cap."""
    equity = 1495.0
    cash = equity
    position_mv = 0.0
    for _ in range(20):
        per = _capital_per(equity, cash, buy_slots=ALPACA_RANGE_SYMBOLS_ACTIVE, position_market=position_mv)
        if per <= 0:
            break
        add = per * ALPACA_RANGE_SYMBOLS_ACTIVE
        position_mv += add
        cash -= add
    assert position_mv / equity <= ALPACA_RANGE_MAX_DEPLOYED_PCT + 1e-9
    assert position_mv / equity > 0.19 * 2


def test_echte_posities_blijven_altijd_actief():
    """Anders krijgt een positie die uit de top-n valt nooit meer een exit-order."""
    scored = {f"S{i}/USD": (10.0, 10.5, 1.0 - i / 100) for i in range(8)}
    met_positie = {"S7/USD"}  # laagste score

    selected, levels = select_top_symbols_from_scores(scored, met_positie, n=3)
    assert "S7/USD" in selected
    assert "S7/USD" in levels
