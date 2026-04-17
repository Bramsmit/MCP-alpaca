"""
Range-strategie, hourly variant voor het hybrid model.

Identieke logica als de daily range-bot in `bot/live_trader.py`, maar:
    - Levels uit de laatste RANGE_LOOKBACK_HOURS hourly candles
    - Stop-loss via ATR (i.p.v. vaste $/unit zoals op daily)
    - Retourneert een StrategySignal; de orchestrator voert het uit.

Koop: net boven gemiddelde low (BUY_ABOVE_LOW_PCT)
Verkoop: net onder gemiddelde high (SELL_BELOW_HIGH_PCT), min MIN_SPREAD_PCT
"""

from __future__ import annotations

import pandas as pd

from bot.config import (
    BUY_ABOVE_LOW_PCT,
    SELL_BELOW_HIGH_PCT,
    MIN_SPREAD_PCT,
    RANGE_LOOKBACK_HOURS,
    RANGE_STOP_ATR_MULT,
    RISK_PER_TRADE_PCT,
    ADX_PERIOD,
)
from bot.indicators import atr as atr_indicator
from bot.risk_manager import position_size, range_stop_profile
from bot.strategy_base import StrategyContext, StrategySignal


def compute_hourly_levels(df: pd.DataFrame, lookback: int = RANGE_LOOKBACK_HOURS) -> tuple[float, float, float] | None:
    """(buy_level, sell_level, atr_value) of None als spread onvoldoende / te weinig data."""
    if len(df) < max(lookback, ADX_PERIOD * 2):
        return None

    window = df.tail(lookback)
    low = float(window["low"].mean())
    high = float(window["high"].mean())
    buy_level = low * (1 + BUY_ABOVE_LOW_PCT)
    sell_level = high * (1 - SELL_BELOW_HIGH_PCT)

    if sell_level < buy_level * (1 + MIN_SPREAD_PCT):
        return None

    atr_series = atr_indicator(df, ADX_PERIOD)
    atr_value = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
    return buy_level, sell_level, atr_value


def generate_signal(
    df: pd.DataFrame,
    ctx: StrategyContext,
) -> StrategySignal:
    """Genereer één signaal voor het range-regime."""
    levels = compute_hourly_levels(df)
    if levels is None:
        return StrategySignal(
            action="skip",
            strategy="range",
            reason=f"onvoldoende spread of data (lookback={RANGE_LOOKBACK_HOURS}h)",
        )

    buy_level, sell_level, atr_value = levels

    if ctx.has_position:
        # Bestaande positie: target is sell_level. Orchestrator vergelijkt met
        # openstaande order en doet cancel+replace indien nodig.
        return StrategySignal(
            action="update_exit",
            strategy="range",
            exit_price=sell_level,
            stop_price=ctx.avg_entry_price - RANGE_STOP_ATR_MULT * atr_value if atr_value > 0 else None,
            reason=f"range sell @ {sell_level:.4f} (atr={atr_value:.4f})",
        )

    entry = buy_level
    profile = range_stop_profile(
        entry=entry,
        atr_value=atr_value,
        sell_level=sell_level,
        atr_mult=RANGE_STOP_ATR_MULT,
    )
    qty = position_size(
        equity=ctx.equity,
        entry=entry,
        stop=profile.stop_price,
        risk_pct=RISK_PER_TRADE_PCT,
        capital_cap=ctx.capital_cap,
    )
    if qty <= 0:
        return StrategySignal(
            action="skip",
            strategy="range",
            reason=(
                f"qty=0 na risk sizing (entry={entry:.4f}, "
                f"stop={profile.stop_price:.4f}, equity={ctx.equity:.2f})"
            ),
        )

    return StrategySignal(
        action="enter_long",
        strategy="range",
        entry_price=entry,
        exit_price=sell_level,
        stop_price=profile.stop_price,
        qty=qty,
        reason=f"hourly range buy @ {entry:.4f}, target {sell_level:.4f}, {profile.describe()}",
    )
