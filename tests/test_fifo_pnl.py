"""
Regressietests voor de FIFO-reconstructie van journal-PnL.

Het journal vulde `profit_usd` maandenlang met een vastgelopen entry_price
($2,5014 voor UNI, terwijl er op $3,20+ werd gekocht). De FIFO-matching moet
op de werkelijke buy-prijzen uitkomen, ook als het journal iets anders beweert.
"""

from __future__ import annotations

import pytest

from bot_live.config import (
    ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD,
    BITVAVO_MAKER_FEE_RATE,
)
from metrics.fifo_pnl import match_fifo, summarize


def _fill(symbol, side, qty, price, ts, **extra):
    row = {
        "timestamp": ts,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
    }
    row.update(extra)
    return row


def _side_fee(notional: float, qty_fraction: float = 1.0) -> float:
    return (
        notional * BITVAVO_MAKER_FEE_RATE
        + ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD * qty_fraction
    )


def test_eenvoudige_round_trip_bruto_en_netto():
    rows = [
        _fill("UNI/USD", "buy", 10.0, 10.0, "2026-08-01T00:00:00+00:00"),
        _fill("UNI/USD", "sell", 10.0, 11.0, "2026-08-02T00:00:00+00:00"),
    ]
    result = match_fifo(rows)
    assert len(result["round_trips"]) == 1

    trip = result["round_trips"][0]
    expected_fees = _side_fee(100.0) + _side_fee(110.0)
    assert trip["gross_usd"] == pytest.approx(10.0)
    assert trip["fees_usd"] == pytest.approx(expected_fees)
    assert trip["net_usd"] == pytest.approx(10.0 - expected_fees)
    assert trip["hold_hours"] == pytest.approx(24.0)


def test_fifo_pakt_de_oudste_buy_eerst():
    rows = [
        _fill("UNI/USD", "buy", 5.0, 10.0, "2026-08-01T00:00:00+00:00"),
        _fill("UNI/USD", "buy", 5.0, 20.0, "2026-08-02T00:00:00+00:00"),
        _fill("UNI/USD", "sell", 5.0, 15.0, "2026-08-03T00:00:00+00:00"),
    ]
    trips = match_fifo(rows)["round_trips"]
    assert len(trips) == 1
    assert trips[0]["buy_price"] == pytest.approx(10.0)
    assert trips[0]["gross_usd"] == pytest.approx(25.0)


def test_vaste_fee_wordt_niet_dubbel_gerekend_bij_deelverkoop():
    """Eén buy-fill draagt zijn vaste bedrag samen maar één keer af."""
    rows = [
        _fill("UNI/USD", "buy", 10.0, 10.0, "2026-08-01T00:00:00+00:00"),
        _fill("UNI/USD", "sell", 5.0, 11.0, "2026-08-02T00:00:00+00:00"),
        _fill("UNI/USD", "sell", 5.0, 12.0, "2026-08-03T00:00:00+00:00"),
    ]
    trips = match_fifo(rows)["round_trips"]
    assert len(trips) == 2

    pct_deel = (
        sum(t["buy_notional_usd"] for t in trips) * BITVAVO_MAKER_FEE_RATE
    )
    vaste_deel_buy = ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD
    vaste_deel_sells = ALPACA_CRYPTO_FEE_FIXED_PER_SIDE_USD * 2
    pct_deel_sells = (
        sum(t["sell_notional_usd"] for t in trips) * BITVAVO_MAKER_FEE_RATE
    )
    verwacht = pct_deel + vaste_deel_buy + pct_deel_sells + vaste_deel_sells

    assert sum(t["fees_usd"] for t in trips) == pytest.approx(verwacht)


def test_sell_zonder_buy_wordt_niet_meegeteld():
    """Posities van voor het journal mogen de win-rate niet vervuilen."""
    rows = [_fill("BCH/USD", "sell", 1.0, 500.0, "2026-03-14T00:00:00+00:00")]
    result = match_fifo(rows)
    assert result["round_trips"] == []
    assert len(result["unmatched_sells"]) == 1
    assert result["unmatched_sells"][0]["qty_unmatched"] == pytest.approx(1.0)


def test_restlot_blijft_open_staan():
    rows = [
        _fill("CRV/USD", "buy", 100.0, 0.25, "2026-08-01T00:00:00+00:00"),
        _fill("CRV/USD", "sell", 60.0, 0.26, "2026-08-02T00:00:00+00:00"),
    ]
    result = match_fifo(rows)
    assert len(result["round_trips"]) == 1
    assert len(result["open_lots"]) == 1
    assert result["open_lots"][0]["qty_open"] == pytest.approx(40.0)


def test_dust_na_verkoop_bezet_geen_lot():
    """Alpaca laat een paar duizendste munt staan; dat is geen open positie."""
    rows = [
        _fill("CRV/USD", "buy", 1000.0, 0.25, "2026-08-01T00:00:00+00:00"),
        _fill(
            "CRV/USD", "sell", 999.9999999, 0.26, "2026-08-02T00:00:00+00:00"
        ),
    ]
    result = match_fifo(rows)
    assert result["open_lots"] == []


def test_vastgelopen_entry_price_in_journal_wordt_genegeerd():
    """
    De UNI-bug: journal meldde $34 winst tegen entry $2,5014, terwijl er op
    $3,2085 was gekocht en op $3,276 verkocht.
    """
    rows = [
        _fill("UNI/USD", "buy", 45.1, 3.2085, "2026-08-17T01:12:00+00:00"),
        _fill(
            "UNI/USD",
            "sell",
            45.0,
            3.276,
            "2026-08-17T02:58:00+00:00",
            entry_price=2.5014,
            profit_usd=33.9992,
        ),
    ]
    trip = match_fifo(rows)["round_trips"][0]

    assert trip["buy_price"] == pytest.approx(3.2085)
    assert trip["journal_profit_usd"] == pytest.approx(33.9992)
    assert trip["gross_usd"] == pytest.approx(45.0 * (3.276 - 3.2085))
    assert trip["net_usd"] < 3.0


def test_summarize_win_rate_en_totalen():
    rows = [
        _fill("A/USD", "buy", 10.0, 10.0, "2026-08-01T00:00:00+00:00"),
        _fill("A/USD", "sell", 10.0, 12.0, "2026-08-02T00:00:00+00:00"),
        _fill("A/USD", "buy", 10.0, 10.0, "2026-08-03T00:00:00+00:00"),
        _fill("A/USD", "sell", 10.0, 9.0, "2026-08-04T00:00:00+00:00"),
    ]
    total = summarize(match_fifo(rows)["round_trips"])

    assert total["n"] == 2
    assert total["wins"] == 1
    assert total["losses"] == 1
    assert total["win_rate_pct"] == pytest.approx(50.0)
    assert total["net_usd"] == pytest.approx(
        total["gross_usd"] - total["fees_usd"]
    )


def test_summarize_leeg():
    assert summarize([])["n"] == 0
