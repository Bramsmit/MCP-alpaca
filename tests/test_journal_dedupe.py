"""Journal dedupe voor fill-notificaties."""

from __future__ import annotations

import json

from bot_live.journal import known_order_ids, log_trade


def test_known_order_ids_reads_journal(tmp_path, monkeypatch):
    journal = tmp_path / "trades.jsonl"
    monkeypatch.setattr(
        "bot_live.journal._journal_path",
        lambda filename="trades.jsonl": journal,
    )
    log_trade(
        order_id="ord-1",
        symbol="UNI/USD",
        side="sell",
        qty=1.0,
        price=3.5,
        entry_price=3.4,
        profit=0.1,
        portfolio_value=1000.0,
    )
    log_trade(
        order_id="ord-2",
        symbol="CRV/USD",
        side="buy",
        qty=10.0,
        price=0.2,
        entry_price=None,
        profit=None,
        portfolio_value=1000.0,
    )
    assert known_order_ids() == frozenset({"ord-1", "ord-2"})

    journal.write_text('{"order_id": "legacy"}\n', encoding="utf-8")
    assert "legacy" in known_order_ids()
