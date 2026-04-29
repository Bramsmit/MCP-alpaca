#!/usr/bin/env python3
"""
Backtest voor range-only, trend-only en hybrid modus op hourly bars.

Gebruikt exact dezelfde functies als live (`market_regime_detector`,
`range_strategy.generate_signal`, `trend_strategy.generate_signal`,
`risk_manager`), zodat signalen in backtest en live identiek zijn.

Fill-semantiek per bar:
    1. Als er een pending limit-buy is: fill als bar.low <= buy_price.
    2. Als er een pending limit-sell is: fill als bar.high >= sell_price.
    3. Stop-loss / exit_now: als bar.low <= stop -> fill op stop.
    4. Na deze checks: detecteer regime op alle bars t/m dit punt, genereer
       nieuw signaal, en update pending orders voor de VOLGENDE bar.

Rapporteert per symbol én gecombineerd:
    total_return, n_trades, win_rate, Sharpe, max drawdown.
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

import pandas as pd

from bot_hybrid import range_strategy, trend_strategy
from bot_live.config import (
    SYMBOLS,
    START_CAPITAL,
    CAPITAL_PER_ASSET,
    BACKTEST_MONTHS,
    ADX_PERIOD,
    REGIME_CONFIRMATION_BARS,
    HYBRID_ADX_TREND_THRESHOLD,
    HYBRID_ADX_RANGE_THRESHOLD,
    HYBRID_REGIME_CONFIRMATION_BARS,
    HYBRID_RANGE_LOOKBACK_HOURS,
    RANGE_LOOKBACK_HOURS,
    EMA_FAST,
    EMA_SLOW,
)
from bot_hybrid.market_regime_detector import detect_regime
from bot_hybrid.strategy_base import StrategyContext, StrategySignal
from bot_live.hybrid_signals import pick_hybrid_signal


Mode = Literal["range_only", "trend_only", "hybrid"]


@dataclass
class SymbolResult:
    symbol: str
    mode: Mode
    start_capital: float
    final_value: float
    n_trades: int
    n_wins: int
    equity_curve: pd.Series
    trades: list[dict]

    @property
    def return_pct(self) -> float:
        return (self.final_value - self.start_capital) / self.start_capital * 100

    @property
    def win_rate(self) -> float:
        closed = [t for t in self.trades if t["side"] == "sell"]
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
        return wins / len(closed) * 100

    @property
    def max_drawdown(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        peak = self.equity_curve.cummax()
        dd = (self.equity_curve - peak) / peak
        return float(dd.min() * 100)

    @property
    def sharpe(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        returns = self.equity_curve.pct_change().dropna()
        if returns.empty or returns.std() == 0:
            return 0.0
        # Hourly -> jaarlijks: 24 * 365
        ann_factor = math.sqrt(24 * 365)
        return float(returns.mean() / returns.std() * ann_factor)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def fetch_hourly_data(symbols: list[str], months: int) -> dict[str, pd.DataFrame]:
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    client = CryptoHistoricalDataClient(api_key, secret) if api_key else CryptoHistoricalDataClient()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=months * 31)
    request = CryptoBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Hour,
        start=start,
        end=end,
    )
    bars = client.get_crypto_bars(request)
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        if bars.df is None or symbol not in bars.df.index.get_level_values(0):
            out[symbol] = pd.DataFrame()
            continue
        df = bars.df.loc[symbol].copy()
        df = df[["open", "high", "low", "close", "volume"]].sort_index()
        out[symbol] = df
    return out


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------


@dataclass
class _SimState:
    cash: float
    qty: float = 0.0
    avg_entry: float = 0.0
    highest_close: float = 0.0
    pending_buy: float | None = None
    pending_buy_qty: float | None = None
    pending_sell: float | None = None
    stop_price: float | None = None
    prev_regime: str = "UNCERTAIN"
    trades: list[dict] = field(default_factory=list)


def _pick_signal(mode: Mode, regime: str, df: pd.DataFrame, ctx: StrategyContext) -> tuple[StrategySignal, str]:
    """Alleen voor range_only / trend_only (hybrid gebruikt pick_hybrid_signal)."""
    if mode == "range_only":
        return range_strategy.generate_signal(df, ctx), "range"
    if mode == "trend_only":
        return trend_strategy.generate_signal(df, ctx), "trend"
    raise ValueError(f"onverwachte mode voor _pick_signal: {mode}")


def run_backtest(df: pd.DataFrame, symbol: str, capital: float, mode: Mode) -> SymbolResult:
    """Simuleer één symbool bar-voor-bar."""
    warm_lookback = max(RANGE_LOOKBACK_HOURS, HYBRID_RANGE_LOOKBACK_HOURS) if mode == "hybrid" else RANGE_LOOKBACK_HOURS
    warm_confirm = HYBRID_REGIME_CONFIRMATION_BARS if mode == "hybrid" else REGIME_CONFIRMATION_BARS
    warmup = max(EMA_SLOW * 2, ADX_PERIOD * 3, warm_lookback) + warm_confirm
    if len(df) <= warmup + 2:
        empty = pd.Series(dtype=float)
        return SymbolResult(symbol, mode, capital, capital, 0, 0, empty, [])

    st = _SimState(cash=capital)
    equity_points: list[tuple[pd.Timestamp, float]] = []

    for i in range(warmup, len(df)):
        bar = df.iloc[i]
        ts = df.index[i]
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])

        # ---------- Fill phase (pending orders van vorige bar) ----------
        if st.qty > 0:
            # Stop-loss check (bearish trigger eerst, conservatief)
            if st.stop_price is not None and low <= st.stop_price and st.stop_price > 0:
                proceeds = st.qty * st.stop_price
                st.cash += proceeds
                pnl = proceeds - st.qty * st.avg_entry
                st.trades.append({
                    "ts": ts.isoformat(),
                    "side": "sell",
                    "qty": st.qty,
                    "price": st.stop_price,
                    "type": "stop_loss",
                    "pnl": pnl,
                })
                st.qty = 0.0
                st.avg_entry = 0.0
                st.highest_close = 0.0
                st.stop_price = None
                st.pending_sell = None
            elif st.pending_sell is not None and high >= st.pending_sell:
                proceeds = st.qty * st.pending_sell
                st.cash += proceeds
                pnl = proceeds - st.qty * st.avg_entry
                st.trades.append({
                    "ts": ts.isoformat(),
                    "side": "sell",
                    "qty": st.qty,
                    "price": st.pending_sell,
                    "type": "take_profit",
                    "pnl": pnl,
                })
                st.qty = 0.0
                st.avg_entry = 0.0
                st.highest_close = 0.0
                st.stop_price = None
                st.pending_sell = None
        elif st.pending_buy is not None and st.pending_buy_qty and low <= st.pending_buy:
            cost = st.pending_buy_qty * st.pending_buy
            if cost <= st.cash:
                st.cash -= cost
                st.qty = st.pending_buy_qty
                st.avg_entry = st.pending_buy
                st.highest_close = close
                st.trades.append({
                    "ts": ts.isoformat(),
                    "side": "buy",
                    "qty": st.qty,
                    "price": st.pending_buy,
                    "type": "entry",
                })
            st.pending_buy = None
            st.pending_buy_qty = None

        # ---------- Track highest close voor trailing ----------
        if st.qty > 0:
            st.highest_close = max(st.highest_close, close)

        # ---------- Regime detect + signal ----------
        window = df.iloc[: i + 1]
        if mode == "hybrid":
            snap = detect_regime(
                window,
                prev_regime=st.prev_regime,
                adx_period=ADX_PERIOD,
                trend_threshold=HYBRID_ADX_TREND_THRESHOLD,
                range_threshold=HYBRID_ADX_RANGE_THRESHOLD,
                confirmation_bars=HYBRID_REGIME_CONFIRMATION_BARS,
                ema_fast_period=EMA_FAST,
                ema_slow_period=EMA_SLOW,
            )
            st.prev_regime = snap.regime
        elif mode == "range_only":
            st.prev_regime = "RANGING"
        else:
            st.prev_regime = "TRENDING_UP"

        equity = st.cash + st.qty * close
        ctx = StrategyContext(
            symbol=symbol,
            current_price=close,
            equity=equity,
            capital_cap=capital,
            has_position=st.qty > 0,
            position_qty=st.qty,
            avg_entry_price=st.avg_entry,
            highest_close_since_entry=st.highest_close,
        )
        if mode == "hybrid":
            signal, _strategy_label = pick_hybrid_signal(window, ctx, snap)
        else:
            regime = st.prev_regime
            signal, _strategy_label = _pick_signal(mode, regime, window, ctx)

        # ---------- Apply signal to pending orders for next bar ----------
        if signal.action == "enter_long" and st.qty == 0 and signal.entry_price and signal.qty:
            affordable_qty = min(signal.qty, st.cash / signal.entry_price)
            if affordable_qty > 0:
                st.pending_buy = float(signal.entry_price)
                st.pending_buy_qty = float(affordable_qty)
                st.stop_price = float(signal.stop_price) if signal.stop_price else None
        elif signal.action == "update_exit" and st.qty > 0 and signal.exit_price:
            st.pending_sell = float(signal.exit_price)
            if signal.stop_price is not None:
                st.stop_price = float(signal.stop_price)
        elif signal.action == "exit_now" and st.qty > 0:
            # Direct verkopen op close van deze bar (we laten het doorgaan naar volgende bar via pending_sell iets onder close)
            exit_px = float(signal.exit_price or close)
            proceeds = st.qty * exit_px
            st.cash += proceeds
            pnl = proceeds - st.qty * st.avg_entry
            st.trades.append({
                "ts": ts.isoformat(),
                "side": "sell",
                "qty": st.qty,
                "price": exit_px,
                "type": "exit_now",
                "pnl": pnl,
            })
            st.qty = 0.0
            st.avg_entry = 0.0
            st.highest_close = 0.0
            st.stop_price = None
            st.pending_sell = None

        equity_points.append((ts, st.cash + st.qty * close))

    # Mark-to-market met laatste close als er nog positie open is
    final_value = st.cash + st.qty * float(df["close"].iloc[-1])
    eq_series = pd.Series(
        [v for _, v in equity_points],
        index=pd.DatetimeIndex([t for t, _ in equity_points]),
        dtype=float,
    )
    n_wins = sum(1 for t in st.trades if t.get("pnl", 0) > 0 and t["side"] == "sell")
    n_trades_total = len(st.trades)
    return SymbolResult(
        symbol=symbol,
        mode=mode,
        start_capital=capital,
        final_value=final_value,
        n_trades=n_trades_total,
        n_wins=n_wins,
        equity_curve=eq_series,
        trades=st.trades,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_row(mode: Mode, results: list[SymbolResult]) -> dict:
    total_start = sum(r.start_capital for r in results)
    total_final = sum(r.final_value for r in results)
    total_return = (total_final - total_start) / total_start * 100 if total_start else 0.0
    total_trades = sum(r.n_trades for r in results)

    # Combined equity curve (simpele som, gesorteerd op timestamp)
    if results:
        combined = pd.concat([r.equity_curve for r in results if not r.equity_curve.empty], axis=1).sum(axis=1)
        if combined.empty:
            sharpe = 0.0
            max_dd = 0.0
        else:
            returns = combined.pct_change().dropna()
            ann = math.sqrt(24 * 365)
            sharpe = float(returns.mean() / returns.std() * ann) if returns.std() else 0.0
            peak = combined.cummax()
            dd = (combined - peak) / peak
            max_dd = float(dd.min() * 100)
    else:
        sharpe = 0.0
        max_dd = 0.0

    total_closed = sum(1 for r in results for t in r.trades if t["side"] == "sell")
    total_wins = sum(r.n_wins for r in results)
    win_rate = (total_wins / total_closed * 100) if total_closed else 0.0

    return {
        "mode": mode,
        "return_pct": total_return,
        "final_value": total_final,
        "n_trades": total_trades,
        "win_rate": win_rate,
        "sharpe": sharpe,
        "max_dd": max_dd,
    }


def _print_mode_results(mode: Mode, results: list[SymbolResult]) -> dict:
    print(f"\n=== Mode: {mode} ===")
    for r in results:
        print(
            f"  {r.symbol}: return={r.return_pct:+.2f}% "
            f"trades={r.n_trades} win_rate={r.win_rate:.1f}% "
            f"sharpe={r.sharpe:.2f} max_dd={r.max_drawdown:.2f}%"
        )
    combined = _format_row(mode, results)
    print(
        f"  TOTAL: return={combined['return_pct']:+.2f}% "
        f"trades={combined['n_trades']} win_rate={combined['win_rate']:.1f}% "
        f"sharpe={combined['sharpe']:.2f} max_dd={combined['max_dd']:.2f}%"
    )
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid bot backtest (hourly)")
    parser.add_argument("--months", type=int, default=BACKTEST_MONTHS,
                        help=f"Aantal maanden historische data (default={BACKTEST_MONTHS})")
    parser.add_argument("--symbols", type=str, default=",".join(SYMBOLS),
                        help="Comma-separated lijst; default uit config")
    parser.add_argument("--modes", type=str, default="range_only,trend_only,hybrid",
                        help="Welke modes te draaien")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    modes: list[Mode] = [m.strip() for m in args.modes.split(",") if m.strip()]  # type: ignore[assignment]

    print("=" * 70)
    print("Hybrid backtest (hourly)")
    print("=" * 70)
    print(f"Symbols: {symbols} | months: {args.months} | modes: {modes}")
    print(f"Per-asset capital: ${CAPITAL_PER_ASSET:.0f} | total: ${START_CAPITAL:.0f}")
    print()

    print("Ophalen data...")
    data = fetch_hourly_data(symbols, args.months)
    for s in symbols:
        print(f"  {s}: {len(data.get(s, pd.DataFrame()))} hourly bars")

    all_summaries: list[dict] = []
    for mode in modes:
        results = []
        for symbol in symbols:
            df = data.get(symbol, pd.DataFrame())
            if df.empty:
                continue
            res = run_backtest(df, symbol, CAPITAL_PER_ASSET, mode)
            results.append(res)
        summary = _print_mode_results(mode, results)
        all_summaries.append(summary)

    print()
    print("=" * 70)
    print(f"{'Mode':<12} {'Return':>9} {'Trades':>7} {'Win%':>7} {'Sharpe':>8} {'MaxDD%':>8}")
    print("-" * 70)
    for s in all_summaries:
        print(
            f"{s['mode']:<12} {s['return_pct']:>8.2f}% {s['n_trades']:>7d} "
            f"{s['win_rate']:>6.1f}% {s['sharpe']:>8.2f} {s['max_dd']:>7.2f}%"
        )
    print("=" * 70)


if __name__ == "__main__":
    main()
