from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from bot_live import safety


def _daily_from_closes(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D", tz="UTC")
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000,
        },
        index=idx,
    )


def test_stop_distance_uses_minimum_when_atr_unavailable():
    assert safety.stop_distance_fraction(None, 100.0) == safety.SAFETY_STOP_MIN_PCT


def test_stop_distance_is_bounded_by_maximum():
    df = _daily_from_closes([100, 120, 90, 130, 80, 140] * 10)
    assert safety.stop_distance_fraction(df, 100.0) == safety.SAFETY_STOP_MAX_PCT


def test_symbol_gate_blocks_clear_downtrend():
    closes = list(range(120, 60, -1))
    ok, reason = safety._symbol_gate("TEST/USD", _daily_from_closes(closes))

    assert ok is False
    assert "downtrend" in reason


def test_symbol_gate_allows_uptrend():
    closes = list(range(60, 120))
    ok, _reason = safety._symbol_gate("TEST/USD", _daily_from_closes(closes))

    assert ok is True


def test_buy_cap_respects_risk_and_allocation_caps():
    decision = safety.SafetyDecision(stop_distances={"BCH/USD": 0.05})

    assert decision.buy_cap("BCH/USD", equity=1250.0, default_cap=500.0) == 250.0


def test_history_peak_equity_reads_local_journals(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "alpaca_trades.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"portfolio_value": 1250.0}),
                json.dumps({"portfolio_value_usd": 1360.02}),
                "not-json",
            ]
        )
    )
    monkeypatch.setattr(safety, "_REPO_ROOT", tmp_path)

    assert safety._history_peak_equity() == 1360.02


def test_cancel_buy_orders_only_touches_configured_symbols(monkeypatch):
    class Order:
        def __init__(self, order_id: str, symbol: str, side):
            self.id = order_id
            self.symbol = symbol
            self.side = side
            self.limit_price = 100

    class Client:
        def __init__(self):
            self.cancelled = []

        def cancel_order_by_id(self, order_id: str):
            self.cancelled.append(order_id)

    client = Client()
    monkeypatch.setattr(
        safety,
        "get_open_orders",
        lambda _client: [
            Order("range-buy", "BCHUSD", safety.OrderSide.BUY),
            Order("other-buy", "BTCUSD", safety.OrderSide.BUY),
            Order("range-sell", "BCHUSD", safety.OrderSide.SELL),
        ],
    )

    actions = safety._cancel_buy_orders(client, dry_run=False, symbols=["BCH/USD"])

    assert client.cancelled == ["range-buy"]
    assert actions == ["cancel buy BCHUSD @100"]


def test_apply_safety_guardrails_pauses_buys_from_historical_drawdown(
    monkeypatch,
    tmp_path,
):
    class Order:
        id = "bch-buy"
        symbol = "BCHUSD"
        side = safety.OrderSide.BUY
        limit_price = 200

    class Client:
        def __init__(self):
            self.cancelled = []

        def cancel_order_by_id(self, order_id: str):
            self.cancelled.append(order_id)

    client = Client()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "alpaca_trades.jsonl").write_text(
        json.dumps({"portfolio_value_usd": 1360.02}) + "\n"
    )
    daily = _daily_from_closes(list(range(60, 120)))
    sent = []

    monkeypatch.setattr(safety, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        safety,
        "_fetch_daily_bars",
        lambda _data_client, _symbols: {
            "BCH/USD": daily,
            "BTC/USD": daily,
            "ETH/USD": daily,
        },
    )
    monkeypatch.setattr(safety, "get_open_orders", lambda _client, symbol=None: [Order()])
    monkeypatch.setattr(safety, "get_current_prices", lambda _data_client, symbols: {})
    monkeypatch.setattr(safety, "get_positions", lambda _client, symbols=None: {})
    monkeypatch.setattr(safety, "send_telegram", sent.append)

    decision = safety.apply_safety_guardrails(
        client,
        object(),
        portfolio_equity=1250.0,
        symbols=["BCH/USD"],
    )

    assert decision.block_new_buys is True
    assert decision.peak_equity == 1360.02
    assert decision.drawdown_pct < -5
    assert client.cancelled == ["bch-buy"]
    assert "cancel buy BCHUSD" in decision.actions[0]
    assert "portfolio drawdown" in sent[0]
    state = json.loads((tmp_path / ".alpaca_safety_state.json").read_text())
    assert state["peak_equity"] == 1360.02
    assert "cooldown_until" in state


def test_apply_safety_guardrails_exits_position_on_software_stop(monkeypatch, tmp_path):
    class SellOrder:
        id = "bch-sell"
        symbol = "BCHUSD"
        side = safety.OrderSide.SELL
        limit_price = 110

    class Client:
        def __init__(self):
            self.cancelled = []

        def cancel_order_by_id(self, order_id: str):
            self.cancelled.append(order_id)

    client = Client()
    sent = []
    submitted = []
    daily = _daily_from_closes([100] * 60)

    monkeypatch.setattr(safety, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        safety,
        "_fetch_daily_bars",
        lambda _data_client, _symbols: {
            "BCH/USD": daily,
            "BTC/USD": daily,
            "ETH/USD": daily,
        },
    )
    monkeypatch.setattr(safety, "get_open_orders", lambda _client, symbol=None: [SellOrder()])
    monkeypatch.setattr(safety, "get_current_prices", lambda _data_client, symbols: {"BCH/USD": 93.0})
    monkeypatch.setattr(safety, "get_positions", lambda _client, symbols=None: {"BCH/USD": (1.0, 100.0)})
    monkeypatch.setattr(safety, "_find_position", lambda _client, symbol: object())
    monkeypatch.setattr(
        safety,
        "_submit_crypto_sell",
        lambda _client, symbol, _position, limit_price: submitted.append((symbol, limit_price)),
    )
    monkeypatch.setattr(safety, "send_telegram", sent.append)

    decision = safety.apply_safety_guardrails(
        client,
        object(),
        portfolio_equity=1300.0,
        symbols=["BCH/USD"],
    )

    assert decision.exit_symbols == {"BCH/USD"}
    assert client.cancelled == ["bch-sell"]
    assert submitted == [("BCH/USD", 93.0 * (1.0 - safety.SAFETY_AGGRESSIVE_SELL_DISCOUNT_PCT))]
    assert "software-stop exit BCH/USD" in decision.actions[0]
    assert "software-stop exit BCH/USD" in sent[0]
    state = json.loads((tmp_path / ".alpaca_safety_state.json").read_text())
    assert "BCH/USD" in state["symbol_cooldowns"]


def test_format_safety_status_shows_active_cooldowns(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    monkeypatch.setattr(
        safety,
        "_load_state",
        lambda: {
            "peak_equity": 1360.0,
            "cooldown_until": future.isoformat(),
            "symbol_cooldowns": {"BCH/USD": future.isoformat()},
        },
    )

    msg = safety.format_safety_status(1250.0)

    assert "Safety" in msg
    assert "buy-pauze" in msg
    assert "Symbol cooldowns: 1" in msg
