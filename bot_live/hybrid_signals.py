"""
Signaalkeuze voor de hybrid bot (live + backtest).

Lost de routering uit die v1 (daily range) niet heeft: ADX-regimes + long-only.
V1 trade’t vaker omdat er geen ADX-gate is en daily levels een bredere
spreiding geven t.o.v. 72h hourly gemiddelden.
"""

from __future__ import annotations

from bot_hybrid import range_strategy, trend_strategy
from bot_hybrid.market_regime_detector import RegimeSnapshot
from bot_hybrid.strategy_base import StrategyContext, StrategySignal
from bot_live.config import HYBRID_UNCERTAINTY_MAX_ADX_FOR_RANGE


def pick_hybrid_signal(
    df,
    ctx: StrategyContext,
    snap: RegimeSnapshot,
) -> tuple[StrategySignal, str]:
    """
    Zelfde logica als `hybrid_trader.run_once` per symbool.
    `range_strategy` krijgt `hybrid_range=True` voor hourly-levels plus fee-floor-spread.

    Bij regime TRENDING_UP maar zonder verse trend-entry (golden cross enz.) wordt
    range-MR gebruikt — lost “stabil/chop maar ADX/regime nog uptrend” op.
    """
    has_position = ctx.has_position

    if snap.regime == "TRENDING_UP":
        trend_sig = trend_strategy.generate_signal(df, ctx)
        if has_position or trend_sig.action == "enter_long":
            return trend_sig, "trend"
        # Geen verse trend-entry maar regime kan blijven "up" (ADX-hysterese / consolidatie).
        rng = range_strategy.generate_signal(df, ctx, hybrid_range=True)
        if rng.action == "enter_long":
            return rng, "range_fallback"
        return trend_sig, "trend"

    if snap.regime == "RANGING":
        return (
            range_strategy.generate_signal(df, ctx, hybrid_range=True),
            "range",
        )

    if snap.regime == "TRENDING_DOWN":
        if has_position:
            return (
                StrategySignal(
                    action="exit_now",
                    strategy="trend",
                    exit_price=ctx.current_price,
                    reason=f"regime TRENDING_DOWN (ADX={snap.adx:.1f})",
                ),
                "trend",
            )
        return (
            StrategySignal(
                action="hold",
                strategy="none",
                reason="TRENDING_DOWN: long-only bot zit aan de kant",
            ),
            "none",
        )

    # UNCERTAIN
    if has_position:
        signal = range_strategy.generate_signal(df, ctx, hybrid_range=True)
        if signal.action == "enter_long":
            signal = StrategySignal(
                action="hold",
                reason=(
                    "UNCERTAIN regime: geen nieuwe entries "
                    "(wel exit onderhouden)"
                ),
                strategy="none",
            )
        return signal, "range"

    max_adx = HYBRID_UNCERTAINTY_MAX_ADX_FOR_RANGE
    if snap.adx <= max_adx:
        return (
            range_strategy.generate_signal(df, ctx, hybrid_range=True),
            "range_soft",
        )

    return (
        StrategySignal(
            action="hold",
            reason=(
                f"UNCERTAIN: ADX={snap.adx:.1f} boven chop-drempel "
                f"({HYBRID_UNCERTAINTY_MAX_ADX_FOR_RANGE})"
            ),
            strategy="none",
        ),
        "none",
    )
