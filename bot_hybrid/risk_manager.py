"""
Risk management: position sizing en stop-loss profielen per strategie.

De core-regel: het bedrag dat je riskeert per trade (entry - stop) * qty
mag niet meer zijn dan RISK_PER_TRADE_PCT * equity.

Daarnaast geldt er altijd een harde cap op notioneel kapitaal per asset
(``CAPITAL_PER_ASSET``) zodat de bot niet per ongeluk het volledige cash
in één positie dumpt bij een erg krappe stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


StrategyName = Literal["range", "trend"]


@dataclass
class StopProfile:
    """Stop-loss en take-profit plan voor één trade.

    - ``stop_price`` = harde stop (of ATR-based).
    - ``take_profit`` = optionele TP; None voor trend-trades (gebruiken trailing).
    - ``trailing_pct`` = percentage trailing stop (None voor range).
    """

    stop_price: float
    take_profit: float | None
    trailing_pct: float | None

    def describe(self) -> str:
        parts = [f"stop=${self.stop_price:.4f}"]
        if self.take_profit is not None:
            parts.append(f"tp=${self.take_profit:.4f}")
        if self.trailing_pct is not None:
            parts.append(f"trail={self.trailing_pct*100:.1f}%")
        return " ".join(parts)


def position_size(
    *,
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float,
    capital_cap: float,
) -> float:
    """
    Bereken qty zo dat (entry - stop) * qty ≈ equity * risk_pct,
    maar de notional (entry * qty) nooit > capital_cap.

    Beide waarden moeten > 0 zijn. Als stop >= entry (ongeldig) retourneren
    we 0 zodat de caller de trade skipt.
    """
    if equity <= 0 or entry <= 0 or capital_cap <= 0:
        return 0.0
    if stop <= 0 or stop >= entry:
        # Ongeldige stop voor long trade; caller moet skippen.
        return 0.0

    risk_per_unit = entry - stop
    risk_budget = equity * max(risk_pct, 0.0)
    if risk_per_unit <= 0 or risk_budget <= 0:
        return 0.0

    qty_by_risk = risk_budget / risk_per_unit
    qty_by_cap = capital_cap / entry
    return float(min(qty_by_risk, qty_by_cap))


def range_stop_profile(
    *,
    entry: float,
    atr_value: float,
    sell_level: float,
    atr_mult: float,
) -> StopProfile:
    """Stop iets onder entry (ATR-gebaseerd), TP op het range-sell-niveau."""
    stop = max(entry - atr_mult * atr_value, 0.0)
    return StopProfile(stop_price=stop, take_profit=sell_level, trailing_pct=None)


def trend_stop_profile(
    *,
    entry: float,
    atr_value: float,
    atr_mult: float,
    trailing_pct: float,
) -> StopProfile:
    """Initieel ATR-gebaseerde stop; exits via trailing stop en/of death cross."""
    stop = max(entry - atr_mult * atr_value, 0.0)
    return StopProfile(stop_price=stop, take_profit=None, trailing_pct=trailing_pct)


def trailing_stop_price(
    *,
    highest_close_since_entry: float,
    trailing_pct: float,
) -> float:
    """Trailing stop = hoogste close sinds entry * (1 - trailing_pct)."""
    if highest_close_since_entry <= 0 or trailing_pct <= 0:
        return 0.0
    return highest_close_since_entry * (1.0 - trailing_pct)
