"""
Markt-regime detector op basis van ADX + EMA-richting.

Regimes:
    - TRENDING_UP:   trending markt met ema_fast > ema_slow
    - TRENDING_DOWN: trending markt met ema_fast < ema_slow
    - RANGING:       zijwaartse markt (lage ADX)
    - UNCERTAIN:     tussenzone of te weinig data; behoud vorige regime

Hysteresis:
    - Schakel alleen naar TRENDING als ADX gedurende `confirmation_bars`
      achter elkaar > trend_threshold is.
    - Schakel alleen naar RANGING als ADX gedurende `confirmation_bars`
      achter elkaar < range_threshold is.
    - Anders: blijf in het vorige regime (dus niet elke minuscule ADX-flip
      leidt tot een strategie-wissel).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal

import pandas as pd

from bot_hybrid.indicators import adx as adx_indicator, ema


Regime = Literal["TRENDING_UP", "TRENDING_DOWN", "RANGING", "UNCERTAIN"]


@dataclass
class RegimeSnapshot:
    regime: Regime
    prev_regime: Regime
    adx: float
    plus_di: float
    minus_di: float
    ema_fast: float
    ema_slow: float
    close: float
    reason: str

    def as_log_line(self, symbol: str, strategy: str) -> str:
        return (
            f"{symbol} | regime={self.regime} "
            f"(adx={self.adx:.1f}, ema_fast={self.ema_fast:.4f} "
            f"{'>' if self.ema_fast > self.ema_slow else '<'} "
            f"ema_slow={self.ema_slow:.4f}) | strategy={strategy} | "
            f"reason=\"{self.reason}\""
        )


def detect_regime(
    df: pd.DataFrame,
    *,
    prev_regime: Regime = "UNCERTAIN",
    adx_period: int = 14,
    trend_threshold: float = 25.0,
    range_threshold: float = 20.0,
    confirmation_bars: int = 2,
    ema_fast_period: int = 20,
    ema_slow_period: int = 50,
) -> RegimeSnapshot:
    """Classificeer het huidige regime op basis van een OHLC DataFrame (1 rij per bar).

    `df` moet oplopend gesorteerd zijn, met kolommen ``high``, ``low``, ``close``.
    """
    if len(df) < max(adx_period * 2, ema_slow_period) + confirmation_bars:
        close = float(df["close"].iloc[-1]) if len(df) else 0.0
        return RegimeSnapshot(
            regime=prev_regime if prev_regime != "UNCERTAIN" else "UNCERTAIN",
            prev_regime=prev_regime,
            adx=0.0,
            plus_di=0.0,
            minus_di=0.0,
            ema_fast=close,
            ema_slow=close,
            close=close,
            reason=f"te weinig bars ({len(df)}) voor classificatie",
        )

    adx_df = adx_indicator(df, adx_period)
    ef = ema(df["close"].astype(float), ema_fast_period)
    es = ema(df["close"].astype(float), ema_slow_period)

    adx_last = float(adx_df["adx"].iloc[-1])
    plus_di = float(adx_df["plus_di"].iloc[-1])
    minus_di = float(adx_df["minus_di"].iloc[-1])
    ema_fast = float(ef.iloc[-1])
    ema_slow = float(es.iloc[-1])
    close = float(df["close"].iloc[-1])

    recent_adx = adx_df["adx"].tail(confirmation_bars)

    trending_confirmed = bool((recent_adx > trend_threshold).all())
    ranging_confirmed = bool((recent_adx < range_threshold).all())

    if trending_confirmed:
        if ema_fast >= ema_slow:
            regime: Regime = "TRENDING_UP"
            reason = f"ADX > {trend_threshold} ({confirmation_bars}x) + EMA{ema_fast_period} > EMA{ema_slow_period}"
        else:
            regime = "TRENDING_DOWN"
            reason = f"ADX > {trend_threshold} ({confirmation_bars}x) + EMA{ema_fast_period} < EMA{ema_slow_period}"
    elif ranging_confirmed:
        regime = "RANGING"
        reason = f"ADX < {range_threshold} ({confirmation_bars}x)"
    else:
        regime = prev_regime if prev_regime != "UNCERTAIN" else "UNCERTAIN"
        if prev_regime == "UNCERTAIN":
            reason = f"ADX={adx_last:.1f} in hysteresis-band {range_threshold}-{trend_threshold}, geen vorig regime"
        else:
            reason = f"ADX={adx_last:.1f} in hysteresis-band, behoud vorig regime ({prev_regime})"

    return RegimeSnapshot(
        regime=regime,
        prev_regime=prev_regime,
        adx=adx_last,
        plus_di=plus_di,
        minus_di=minus_di,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        close=close,
        reason=reason,
    )


def _default_state_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".alpaca_hybrid_state.json"


def load_regime_state(path: Path | None = None) -> dict[str, dict]:
    """Laad per-symbol regime snapshots uit disk (of lege dict bij ontbrekend bestand)."""
    path = path or _default_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data.get("regimes", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_regime_state(regimes: dict[str, RegimeSnapshot], path: Path | None = None) -> None:
    """Schrijf per-symbol regime snapshots naar disk (atomic: schrijf + rename)."""
    path = path or _default_state_path()
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}

    existing["regimes"] = {sym: asdict(snap) for sym, snap in regimes.items()}

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    tmp.replace(path)


def get_prev_regime(state: dict[str, dict], symbol: str) -> Regime:
    """Haal vorig regime voor symbol uit state (default UNCERTAIN)."""
    entry = state.get(symbol) or {}
    prev = entry.get("regime", "UNCERTAIN")
    if prev not in ("TRENDING_UP", "TRENDING_DOWN", "RANGING", "UNCERTAIN"):
        return "UNCERTAIN"
    return prev  # type: ignore[return-value]
