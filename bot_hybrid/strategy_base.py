"""
Gedeelde types voor strategie-signalen.

Strategieën zijn *pure* functies: ze krijgen data + context en retourneren
één StrategySignal. De orchestrator (`hybrid_trader.py`) is verantwoordelijk
voor het daadwerkelijk plaatsen/cancellen van orders via de Alpaca client.
Dit houdt strategie-logica los van exchange-logica, en maakt backtesten
exact identiek aan live runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Action = Literal["enter_long", "update_exit", "exit_now", "hold", "skip"]


@dataclass
class StrategyContext:
    """Snapshot van marktstaat voor één symbool op één bar."""

    symbol: str
    current_price: float
    equity: float
    capital_cap: float
    has_position: bool
    position_qty: float
    avg_entry_price: float
    highest_close_since_entry: float  # 0 als onbekend; orchestrator houdt dit bij


@dataclass
class StrategySignal:
    """Wat de orchestrator moet doen voor dit symbool."""

    action: Action
    reason: str
    strategy: Literal["range", "trend", "none"] = "none"
    entry_price: float | None = None   # limit-buy prijs voor enter_long
    exit_price: float | None = None    # limit-sell prijs voor update_exit / exit_now
    stop_price: float | None = None    # adviesstop (voor logging / risk-check)
    qty: float | None = None           # al door risk_manager geschaald
    trailing_pct: float | None = None  # None = niet trailend

    def as_log_line(self) -> str:
        bits = [f"action={self.action}", f"strategy={self.strategy}"]
        if self.entry_price is not None:
            bits.append(f"entry={self.entry_price:.4f}")
        if self.exit_price is not None:
            bits.append(f"exit={self.exit_price:.4f}")
        if self.stop_price is not None:
            bits.append(f"stop={self.stop_price:.4f}")
        if self.qty is not None:
            bits.append(f"qty={self.qty:.6f}")
        bits.append(f'reason="{self.reason}"')
        return " ".join(bits)
