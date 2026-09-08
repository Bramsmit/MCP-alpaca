"""
Regressietests voor de levenscyclus van buy-orders.

De bug van september 2026: DOT handelde 26% boven zijn buy-level. De runner zag
alleen "prijs is weggelopen van de order", cancelde en plaatste dezelfde
onbereikbare order terug. Elke run opnieuw, terwijl die order ~$156 cash en een
van de vijf koopslots bezet hield zonder realistische kans op een fill.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from alpaca.trading.enums import OrderSide

from bot_live.config import (
    ALPACA_RANGE_MAX_BUY_DISTANCE_PCT,
    ORDER_MAX_AGE_HOURS,
    ORDER_STALE_PRICE_THRESHOLD,
    ORDER_UPDATE_THRESHOLD,
)
from alpaca_bot.live_trader import _cancel_buy_orders, _order_age_hours
from alpaca_bot.strategy_core import (
    BUY_ORDER_ABANDON,
    BUY_ORDER_KEEP,
    BUY_ORDER_PLACE,
    BUY_ORDER_REPLACE_AGED,
    BUY_ORDER_REPLACE_STALE_PRICE,
    BUY_ORDER_UPDATE_LEVEL,
    decide_buy_order_action,
)


def _decide(**kwargs) -> str:
    params = {
        "buy_level": 10.0,
        "current_price": 10.2,
        "existing_order_price": 10.0,
        "order_age_hours": 1.0,
        "max_buy_distance_frac": ALPACA_RANGE_MAX_BUY_DISTANCE_PCT,
    }
    params.update(kwargs)
    return decide_buy_order_action(**params)


class _FakeOrder:
    def __init__(self, side, order_id="oid", limit_price=None):
        self.side = side
        self.id = order_id
        self.limit_price = limit_price


class _FakeClient:
    def __init__(self, fail_on: set[str] | None = None):
        self.cancelled: list[str] = []
        self._fail_on = fail_on or set()

    def cancel_order_by_id(self, order_id):
        if order_id in self._fail_on:
            raise RuntimeError("order already filled")
        self.cancelled.append(order_id)


def test_zonder_order_wordt_er_geplaatst():
    assert _decide(existing_order_price=None) == BUY_ORDER_PLACE


def test_order_binnen_marges_blijft_staan():
    assert _decide(current_price=10.05, existing_order_price=10.0) == (
        BUY_ORDER_KEEP
    )


def test_weggelopen_koers_vervangt_de_order():
    prijs = 10.0 * (1 + ORDER_STALE_PRICE_THRESHOLD) + 0.01
    assert _decide(current_price=prijs, existing_order_price=10.0) == (
        BUY_ORDER_REPLACE_STALE_PRICE
    )


def test_oude_order_wordt_vervangen():
    assert _decide(order_age_hours=ORDER_MAX_AGE_HOURS) == (
        BUY_ORDER_REPLACE_AGED
    )


def test_verschoven_level_werkt_de_order_bij():
    nieuw_level = 10.0 * (1 + ORDER_UPDATE_THRESHOLD * 2)
    assert _decide(buy_level=nieuw_level, current_price=10.1) == (
        BUY_ORDER_UPDATE_LEVEL
    )


def test_onbereikbaar_level_wordt_opgegeven():
    prijs = 10.0 * (1 + ALPACA_RANGE_MAX_BUY_DISTANCE_PCT) + 0.01
    assert _decide(buy_level=10.0, current_price=prijs) == BUY_ORDER_ABANDON


def test_opgeven_gaat_voor_vervangen():
    """
    De kern van de bug: beide condities zijn waar. Vervangen zet dezelfde
    onbereikbare order terug, opgeven maakt cash en het slot vrij.
    """
    actie = _decide(
        buy_level=0.9770124249999999,
        current_price=1.23417,
        existing_order_price=0.9770124249999999,
        order_age_hours=2.0,
    )
    assert actie == BUY_ORDER_ABANDON


def test_dot_situatie_8_september():
    """Log: 'DOT/USD: Buy order vervangen (prijs $1.23 is 26.3% boven)'."""
    assert (
        _decide(
            buy_level=0.9770124249999999,
            current_price=1.23417,
            existing_order_price=0.9770124249999999,
        )
        == BUY_ORDER_ABANDON
    )


def test_avax_situatie_blijft_gewoon_vervangen():
    """AVAX stond 5,9% boven de order: binnen bereik, dus wel herplaatsen."""
    assert (
        _decide(
            buy_level=7.590988053887499,
            current_price=8.039874999999999,
            existing_order_price=7.590988053887499,
        )
        == BUY_ORDER_REPLACE_STALE_PRICE
    )


def test_zonder_koers_geen_opgave():
    """Een ontbrekende quote mag geen order opruimen."""
    assert _decide(current_price=None, existing_order_price=10.0) == (
        BUY_ORDER_KEEP
    )
    assert _decide(current_price=None, existing_order_price=None) == (
        BUY_ORDER_PLACE
    )


def test_cancel_raakt_alleen_buy_orders():
    client = _FakeClient()
    orders = [
        _FakeOrder(OrderSide.BUY, "buy-1"),
        _FakeOrder(OrderSide.SELL, "sell-1"),
        _FakeOrder(OrderSide.BUY, "buy-2"),
    ]
    assert _cancel_buy_orders(client, "DOT/USD", orders) == 2
    assert client.cancelled == ["buy-1", "buy-2"]


def test_cancel_gaat_door_na_een_fout():
    """Een order die net gevuld is mag de rest niet blokkeren."""
    client = _FakeClient(fail_on={"buy-1"})
    orders = [
        _FakeOrder(OrderSide.BUY, "buy-1"),
        _FakeOrder(OrderSide.BUY, "buy-2"),
    ]
    assert _cancel_buy_orders(client, "DOT/USD", orders) == 1
    assert client.cancelled == ["buy-2"]


def test_cancel_zonder_orders():
    client = _FakeClient()
    assert _cancel_buy_orders(client, "DOT/USD", []) == 0


def test_order_ouderdom_uit_aware_timestamp():
    order = _FakeOrder(OrderSide.BUY)
    order.submitted_at = datetime.now(timezone.utc) - timedelta(hours=13)
    assert _order_age_hours(order) == pytest.approx(13.0, abs=0.05)


def test_order_ouderdom_uit_naive_timestamp():
    order = _FakeOrder(OrderSide.BUY)
    order.submitted_at = datetime.now(timezone.utc).replace(
        tzinfo=None
    ) - timedelta(hours=5)
    assert _order_age_hours(order) == pytest.approx(5.0, abs=0.05)


def test_order_ouderdom_uit_string():
    order = _FakeOrder(OrderSide.BUY)
    ts = datetime.now(timezone.utc) - timedelta(hours=2)
    order.submitted_at = ts.isoformat().replace("+00:00", "Z")
    assert _order_age_hours(order) == pytest.approx(2.0, abs=0.05)


def test_order_zonder_timestamp_is_nul_uur():
    assert _order_age_hours(_FakeOrder(OrderSide.BUY)) == 0.0
