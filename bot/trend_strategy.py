"""
Trend-following strategie o.b.v. EMA-crossover + ADX-filter.

Long-only (Alpaca crypto):
    - Entry: EMA_FAST kruiste recent (≤ TREND_CROSSOVER_LOOKBACK_BARS) boven EMA_SLOW,
      huidige ADX > ADX_TREND_THRESHOLD, en plus_di > minus_di.
    - Exit (zet via orchestrator om in limit-sell of cancel):
        * Death cross: EMA_FAST < EMA_SLOW  -> exit_now
        * Trailing stop: prijs < highest_close_since_entry * (1 - trailing_pct) -> exit_now
        * Anders: trailing-stop limit net onder huidige prijs als update_exit,
          zodat bij een forse reversal het cancel+replace patroon hem meepakt.

Alpaca crypto heeft max 1 exit-order per positie, dus de "trailing stop" is
een discreet cancel+replace elke run, niet een echte exchange-native trailing.
"""

from __future__ import annotations

import pandas as pd

from bot.config import (
    EMA_FAST,
    EMA_SLOW,
    ADX_PERIOD,
    ADX_TREND_THRESHOLD,
    TREND_TRAILING_STOP_PCT,
    TREND_STOP_ATR_MULT,
    TREND_CROSSOVER_LOOKBACK_BARS,
    RISK_PER_TRADE_PCT,
)
from bot.indicators import adx as adx_indicator, atr as atr_indicator, ema
from bot.risk_manager import position_size, trend_stop_profile, trailing_stop_price
from bot.strategy_base import StrategyContext, StrategySignal


def _recent_golden_cross(fast: pd.Series, slow: pd.Series, lookback: int) -> bool:
    """True als EMA_FAST in de laatste `lookback` bars boven EMA_SLOW is gekruist."""
    if len(fast) < lookback + 2:
        return False
    diff = (fast - slow).tail(lookback + 1)
    # Teken-wissel van <=0 naar >0 binnen het window
    signs = diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0)).tolist()
    for i in range(1, len(signs)):
        if signs[i - 1] <= 0 and signs[i] > 0:
            return True
    return False


def generate_signal(
    df: pd.DataFrame,
    ctx: StrategyContext,
) -> StrategySignal:
    """Genereer signaal voor het trending regime."""
    if len(df) < max(EMA_SLOW * 2, ADX_PERIOD * 2):
        return StrategySignal(
            action="skip",
            strategy="trend",
            reason=f"te weinig bars ({len(df)}) voor EMA/ADX",
        )

    close = df["close"].astype(float)
    fast = ema(close, EMA_FAST)
    slow = ema(close, EMA_SLOW)
    adx_df = adx_indicator(df, ADX_PERIOD)
    atr_series = atr_indicator(df, ADX_PERIOD)

    ema_fast_last = float(fast.iloc[-1])
    ema_slow_last = float(slow.iloc[-1])
    adx_last = float(adx_df["adx"].iloc[-1])
    plus_di = float(adx_df["plus_di"].iloc[-1])
    minus_di = float(adx_df["minus_di"].iloc[-1])
    atr_value = float(atr_series.iloc[-1])
    price = ctx.current_price if ctx.current_price > 0 else float(close.iloc[-1])

    # ---------- Bestaande positie: bepaal exit / trailing update ----------
    if ctx.has_position:
        if ema_fast_last < ema_slow_last:
            return StrategySignal(
                action="exit_now",
                strategy="trend",
                exit_price=price,
                reason=f"death cross (ema{EMA_FAST}={ema_fast_last:.4f} < ema{EMA_SLOW}={ema_slow_last:.4f})",
            )

        highest = max(ctx.highest_close_since_entry, ctx.avg_entry_price, price)
        trail = trailing_stop_price(
            highest_close_since_entry=highest,
            trailing_pct=TREND_TRAILING_STOP_PCT,
        )
        if trail > 0 and price <= trail:
            return StrategySignal(
                action="exit_now",
                strategy="trend",
                exit_price=price,
                reason=(
                    f"trailing stop hit (price={price:.4f} <= "
                    f"{TREND_TRAILING_STOP_PCT*100:.1f}% onder hoogste close {highest:.4f})"
                ),
            )

        # Nog steeds in trend: stel een limit-sell iets boven huidige prijs in
        # zodat winst meegenomen wordt bij pieken; bij significante move update
        # de orchestrator de order via cancel+replace.
        target = highest * (1 + TREND_TRAILING_STOP_PCT)
        return StrategySignal(
            action="update_exit",
            strategy="trend",
            exit_price=target,
            stop_price=trail if trail > 0 else None,
            trailing_pct=TREND_TRAILING_STOP_PCT,
            reason=(
                f"trail update: highest={highest:.4f}, limit={target:.4f}, "
                f"stop~{trail:.4f}"
            ),
        )

    # ---------- Geen positie: zoek verse entry ----------
    if adx_last <= ADX_TREND_THRESHOLD:
        return StrategySignal(
            action="hold",
            strategy="trend",
            reason=f"ADX {adx_last:.1f} <= {ADX_TREND_THRESHOLD} (te zwak)",
        )
    if plus_di <= minus_di:
        return StrategySignal(
            action="hold",
            strategy="trend",
            reason=f"+DI {plus_di:.1f} <= -DI {minus_di:.1f} (geen bullish druk)",
        )
    if not _recent_golden_cross(fast, slow, TREND_CROSSOVER_LOOKBACK_BARS):
        if ema_fast_last > ema_slow_last:
            return StrategySignal(
                action="hold",
                strategy="trend",
                reason=f"geen verse cross (laatste {TREND_CROSSOVER_LOOKBACK_BARS} bars), trend loopt al",
            )
        return StrategySignal(
            action="hold",
            strategy="trend",
            reason=f"ema{EMA_FAST} {ema_fast_last:.4f} < ema{EMA_SLOW} {ema_slow_last:.4f}",
        )

    entry = price
    profile = trend_stop_profile(
        entry=entry,
        atr_value=atr_value,
        atr_mult=TREND_STOP_ATR_MULT,
        trailing_pct=TREND_TRAILING_STOP_PCT,
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
            strategy="trend",
            reason=(
                f"qty=0 na risk sizing (entry={entry:.4f}, "
                f"stop={profile.stop_price:.4f}, equity={ctx.equity:.2f})"
            ),
        )

    return StrategySignal(
        action="enter_long",
        strategy="trend",
        entry_price=entry,
        stop_price=profile.stop_price,
        qty=qty,
        trailing_pct=TREND_TRAILING_STOP_PCT,
        reason=(
            f"golden cross + ADX {adx_last:.1f} > {ADX_TREND_THRESHOLD}, "
            f"+DI {plus_di:.1f} > -DI {minus_di:.1f}, {profile.describe()}"
        ),
    )
